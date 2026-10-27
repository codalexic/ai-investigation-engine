from collections.abc import Iterable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import uuid4

import numpy as np
from sqlalchemy import select

from app.core.errors import DocumentNotFoundError, IngestionError
from app.core.logging import get_logger
from app.ingest.chunking import Chunker
from app.ingest.dedup import LSHIndex, MinHasher, content_hash
from app.ingest.metadata import extract_metadata
from app.ingest.models import Chunk, ParsedDocument, Section
from app.ingest.parsers import get_parser, normalize_text
from app.ingest.registry import DocumentRecord, DocumentRegistry

logger = get_logger(__name__)


class ChunkSink(Protocol):
    def upsert_chunks(self, chunks: list[Chunk]) -> None: ...

    def delete_document(self, doc_id: str) -> None: ...


class InMemoryChunkSink:
    def __init__(self) -> None:
        self.chunks: dict[str, Chunk] = {}

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        self.chunks.update((chunk.chunk_id, chunk) for chunk in chunks)

    def delete_document(self, doc_id: str) -> None:
        self.chunks = {key: chunk for key, chunk in self.chunks.items() if chunk.doc_id != doc_id}


@dataclass
class IngestResult:
    doc_id: str
    status: Literal["created", "duplicate", "near_duplicate", "unchanged", "updated"]
    duplicate_of: str | None = None
    version: int = 1
    chunk_count: int = 0
    warnings: list[str] = field(default_factory=list)


class IngestionPipeline:
    def __init__(
        self,
        registry: DocumentRegistry,
        sink: ChunkSink,
        chunker: Chunker,
        minhasher: MinHasher,
        lsh: LSHIndex,
        near_dup_threshold: float = 0.9,
        near_dup_policy: Literal["flag", "skip"] = "flag",
    ) -> None:
        if near_dup_policy not in ("flag", "skip") or not 0 <= near_dup_threshold <= 1:
            raise IngestionError("Invalid near duplicate policy or threshold")
        if minhasher.num_perm != lsh.num_perm:
            raise IngestionError("MinHash and LSH sizes must match")
        self.registry, self.sink, self.chunker = registry, sink, chunker
        self.minhasher, self.lsh = minhasher, lsh
        self.near_dup_threshold, self.near_dup_policy = near_dup_threshold, near_dup_policy

    def _log(self, result: IngestResult, started: float) -> IngestResult:
        logger.info(
            "document_ingested",
            extra={
                "doc_id": result.doc_id,
                "status": result.status,
                "chunk_count": result.chunk_count,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )
        return result

    def ingest(
        self,
        data: bytes,
        filename: str,
        doc_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        started = perf_counter()
        old = self.registry.get(doc_id) if doc_id else None
        key = doc_id or uuid4().hex
        parsed = get_parser(filename).parse(data, filename)
        if extra_metadata:
            parsed.metadata.update(extra_metadata)
        metadata = extract_metadata(parsed, filename, key)
        digest = content_hash(parsed.text)
        version = old.version + 1 if old else 1
        if old and old.status == "active" and old.content_hash == digest:
            return self._log(
                IngestResult(key, "unchanged", old.duplicate_of, old.version, old.chunk_count),
                started,
            )
        duplicate = self.registry.get_by_hash(digest)
        if duplicate and duplicate.doc_id != key:
            return self._log(IngestResult(key, "duplicate", duplicate.doc_id, version), started)
        signature = self.minhasher.signature(parsed.text)
        near = [
            (candidate, score)
            for candidate, score in self.lsh.find_near_duplicates(
                signature, self.near_dup_threshold
            )
            if candidate != key
        ]
        duplicate_of = near[0][0] if near else None
        if near and self.near_dup_policy == "skip":
            return self._log(
                IngestResult(
                    key,
                    "near_duplicate",
                    duplicate_of,
                    version,
                    warnings=["Near duplicate skipped"],
                ),
                started,
            )
        chunks = self.chunker.chunk(key, version, parsed, metadata)
        if old:
            self.sink.delete_document(key)
        self.sink.upsert_chunks(chunks)
        fields = metadata.model_dump(mode="json")
        fields["created_at"] = metadata.created_at
        record = DocumentRecord(
            **fields,
            content_hash=digest,
            version=version,
            status="active",
            duplicate_of=duplicate_of,
            minhash=signature.astype("<u8").tobytes(),
            chunk_count=len(chunks),
            chunk_strategy=self.chunker.name,
        )
        if old:
            record.ingested_at = old.ingested_at
        self.registry.upsert(record)
        self.registry.add_version(key, version, digest)
        self.lsh.add(key, signature)
        status = "updated" if old else ("near_duplicate" if near else "created")
        return self._log(
            IngestResult(
                key,
                status,
                duplicate_of,
                version,
                len(chunks),
                ["Near duplicate indexed"] if near else [],
            ),
            started,
        )

    def update(self, doc_id: str, data: bytes, filename: str) -> IngestResult:
        record = self.registry.get(doc_id)
        if record is None or record.status != "active":
            raise DocumentNotFoundError(doc_id)
        return self.ingest(data, filename, doc_id)

    def delete(self, doc_id: str) -> None:
        if self.registry.get(doc_id) is None:
            raise DocumentNotFoundError(doc_id)
        self.sink.delete_document(doc_id)
        self.registry.mark_deleted(doc_id)
        self.lsh.remove(doc_id)

    def rebuild_lsh(self) -> None:
        for key in list(self.lsh.signatures):
            self.lsh.remove(key)
        for key, signature in self.registry.iter_signatures():
            self.lsh.add(key, signature)

    def ingest_records(self, records: Iterable[dict], batch_size: int = 100) -> dict[str, int]:
        if batch_size < 1:
            raise IngestionError("Batch size must be positive")
        started = perf_counter()
        batch_started = started
        batch_records = batch_duplicates = 0
        seen_ids: set[str] = set()
        counts = {"created": 0, "duplicate": 0, "chunk_count": 0}
        known = set()
        with self.registry.session() as session:
            known.update(
                session.scalars(
                    select(DocumentRecord.content_hash).where(DocumentRecord.status == "active")
                )
            )
        batch: list[DocumentRecord] = []
        chunks: list[Chunk] = []

        def flush() -> None:
            nonlocal batch_started, batch_records, batch_duplicates
            chunk_count = len(chunks)
            if batch:
                self.sink.upsert_chunks(chunks)
                self.registry.bulk_upsert(batch)
                for record in batch:
                    self.lsh.add(record.doc_id, np.frombuffer(record.minhash, dtype="<u8"))
                batch.clear()
                chunks.clear()
            if batch_records:
                logger.info(
                    "ingestion_batch",
                    extra={
                        "records": batch_records,
                        "duplicates": batch_duplicates,
                        "chunks": chunk_count,
                        "duration_ms": round((perf_counter() - batch_started) * 1000, 3),
                    },
                )
                batch_records = batch_duplicates = 0
                batch_started = perf_counter()

        for item in records:
            key = item["doc_id"] if "doc_id" in item else uuid4().hex
            if not isinstance(key, str) or not key:
                raise IngestionError("Document id must be a nonempty string")
            if key in seen_ids:
                raise IngestionError(f"Duplicate document id in run: {key}")
            seen_ids.add(key)
            batch_records += 1
            text = normalize_text(str(item.get("text", "")))
            digest = content_hash(text)
            if digest in known:
                counts["duplicate"] += 1
                batch_duplicates += 1
                continue
            parsed = ParsedDocument(
                text, [Section(None, 0, text)], {"format": "txt", **item.get("metadata", {})}
            )
            source = item.get("source", parsed.metadata.get("source", f"{key}.txt"))
            metadata = extract_metadata(parsed, str(source), key)
            new_chunks = self.chunker.chunk(key, 1, parsed, metadata)
            signature = self.minhasher.signature(text)
            fields = metadata.model_dump(mode="json")
            fields["created_at"] = metadata.created_at
            batch.append(
                DocumentRecord(
                    **fields,
                    content_hash=digest,
                    version=1,
                    status="active",
                    minhash=signature.astype("<u8").tobytes(),
                    chunk_count=len(new_chunks),
                    chunk_strategy=self.chunker.name,
                )
            )
            chunks.extend(new_chunks)
            known.add(digest)
            counts["created"] += 1
            counts["chunk_count"] += len(new_chunks)
            if len(batch) >= batch_size:
                flush()
        flush()
        logger.info(
            "ingestion_summary",
            extra={
                "records": counts["created"] + counts["duplicate"],
                "duplicates": counts["duplicate"],
                "chunks": counts["chunk_count"],
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        )
        return counts
