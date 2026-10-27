from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client import models as m

from app.core.config import Settings
from app.core.errors import RetrievalError
from app.ingest.models import Chunk
from app.retrieval.bm25 import Bm25Encoder, Bm25StatsRepository
from app.retrieval.embeddings import Embedder
from app.retrieval.text import analyze


class QueryFilters(BaseModel):
    doc_ids: list[str] | None = None
    doc_types: list[str] | None = None
    services: list[str] | None = None
    change_ids: list[str] | None = None
    incident_ids: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None

    def to_qdrant(self) -> m.Filter:
        conditions = []
        for field, key in [
            ("doc_ids", "doc_id"),
            ("doc_types", "doc_type"),
            ("services", "entities.services"),
            ("change_ids", "entities.change_ids"),
            ("incident_ids", "entities.incident_ids"),
        ]:
            values = getattr(self, field)
            if values is not None:
                conditions.append(m.FieldCondition(key=key, match=m.MatchAny(any=values)))
        if self.date_from or self.date_to:
            conditions.append(
                m.FieldCondition(
                    key="created_at",
                    range=m.DatetimeRange(
                        gte=self.date_from.isoformat() + "T00:00:00Z" if self.date_from else None,
                        lte=self.date_to.isoformat() + "T23:59:59.999999Z"
                        if self.date_to
                        else None,
                    ),
                )
            )
        return m.Filter(must=conditions)


@dataclass
class ScoredChunk:
    chunk_id: str
    score: float
    payload: dict[str, Any]
    vector: list[float] | None = None


P = ParamSpec("P")
T = TypeVar("T")


def _guard(method: Callable[P, T]) -> Callable[P, T]:
    @wraps(method)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return method(*args, **kwargs)
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError(f"Vector store operation failed: {method.__name__}") from exc

    return wrapped


@_guard
def make_qdrant_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url == ":memory:":
        return QdrantClient(":memory:")
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
        timeout=settings.request_timeout_s,
    )


class QdrantStore:
    def __init__(
        self,
        client: QdrantClient,
        collection: str,
        embedder: Embedder,
        bm25: Bm25Encoder,
        stats_repo: Bm25StatsRepository,
        embedding_batch_size: int = 64,
    ) -> None:
        if embedding_batch_size < 1:
            raise RetrievalError("Embedding batch size must be positive")
        self.client, self.collection, self.embedder = client, collection, embedder
        self.bm25, self.stats_repo = bm25, stats_repo
        self.embedding_batch_size = embedding_batch_size

    @_guard
    def ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config={
                    "dense": m.VectorParams(size=self.embedder.dim, distance=m.Distance.COSINE)
                },
                sparse_vectors_config={"bm25": m.SparseVectorParams()},
            )
        for key in [
            "doc_id",
            "doc_type",
            "entities.services",
            "entities.change_ids",
            "entities.incident_ids",
        ]:
            self.client.create_payload_index(self.collection, key, m.PayloadSchemaType.KEYWORD)
        self.client.create_payload_index(
            self.collection, "created_at", m.PayloadSchemaType.DATETIME
        )

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, chunk_id))

    @staticmethod
    def _scored(point: m.Record | m.ScoredPoint) -> ScoredChunk:
        payload = point.payload or {}
        vectors = point.vector if isinstance(point.vector, dict) else {}
        return ScoredChunk(
            payload["chunk_id"], getattr(point, "score", 0.0), payload, vectors.get("dense")
        )

    @_guard
    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise RetrievalError("Duplicate chunk IDs in upsert")
        for start in range(0, len(chunks), self.embedding_batch_size):
            batch = chunks[start : start + self.embedding_batch_size]
            vectors = self.embedder.embed_documents([c.text for c in batch])
            old_chunks = self.get_chunks([c.chunk_id for c in batch])
            for old in old_chunks:
                self.bm25.stats.remove_document(analyze(old.payload["text"]))
            for chunk in batch:
                self.bm25.stats.add_document(analyze(chunk.text))
            try:
                points = []
                for chunk, vector in zip(batch, vectors, strict=True):
                    payload = {
                        "title": "",
                        "doc_type": "other",
                        "source": "",
                        "created_at": None,
                        "entities": {},
                        **chunk.metadata,
                        "chunk_id": chunk.chunk_id,
                        "text": chunk.text,
                        "doc_id": chunk.doc_id,
                        "version": chunk.version,
                        "index": chunk.index,
                        "section_path": chunk.section_path,
                        "token_count": chunk.token_count,
                    }
                    created = payload.get("created_at")
                    if created:
                        payload["created_at"] = (
                            created.isoformat()
                            if isinstance(created, (date, datetime))
                            else str(created)
                        )
                        if len(payload["created_at"]) == 10:
                            payload["created_at"] += "T00:00:00Z"
                    points.append(
                        m.PointStruct(
                            id=self._point_id(chunk.chunk_id),
                            vector={
                                "dense": vector.tolist(),
                                "bm25": self.bm25.encode_document(chunk.text),
                            },
                            payload=payload,
                        )
                    )
                self.client.upsert(self.collection, points, wait=True)
            except Exception:
                for chunk in batch:
                    self.bm25.stats.remove_document(analyze(chunk.text))
                for old in old_chunks:
                    self.bm25.stats.add_document(analyze(old.payload["text"]))
                raise
            self.stats_repo.save(self.bm25.stats)
        self.stats_repo.save(self.bm25.stats)

    @_guard
    def delete_document(self, doc_id: str) -> None:
        chunks = self.get_document_chunks(doc_id)
        self.client.delete(
            self.collection,
            m.FilterSelector(filter=QueryFilters(doc_ids=[doc_id]).to_qdrant()),
            wait=True,
        )
        for chunk in chunks:
            self.bm25.stats.remove_document(analyze(chunk.payload["text"]))
        self.stats_repo.save(self.bm25.stats)

    @_guard
    def dense_search(
        self,
        vector: np.ndarray | list[float],
        limit: int,
        filters: QueryFilters | None = None,
        with_vectors: bool = False,
    ) -> list[ScoredChunk]:
        points = self.client.query_points(
            self.collection,
            query=list(vector),
            using="dense",
            limit=limit,
            query_filter=filters.to_qdrant() if filters else None,
            with_payload=True,
            with_vectors=with_vectors,
        ).points
        return [self._scored(p) for p in points]

    @_guard
    def sparse_search(
        self,
        sparse_vector: m.SparseVector,
        limit: int,
        filters: QueryFilters | None = None,
        with_vectors: bool = False,
    ) -> list[ScoredChunk]:
        if not sparse_vector.indices:
            return []
        points = self.client.query_points(
            self.collection,
            query=sparse_vector,
            using="bm25",
            limit=limit,
            query_filter=filters.to_qdrant() if filters else None,
            with_payload=True,
            with_vectors=with_vectors,
        ).points
        return [self._scored(p) for p in points]

    @_guard
    def get_chunks(self, chunk_ids: list[str]) -> list[ScoredChunk]:
        if not chunk_ids:
            return []
        return [
            self._scored(p)
            for p in self.client.retrieve(
                self.collection,
                [self._point_id(c) for c in chunk_ids],
                with_payload=True,
                with_vectors=True,
            )
        ]

    @_guard
    def get_document_chunks(self, doc_id: str) -> list[ScoredChunk]:
        result = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                scroll_filter=QueryFilters(doc_ids=[doc_id]).to_qdrant(),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            result.extend(self._scored(p) for p in points)
            if offset is None:
                break
        return sorted(result, key=lambda c: c.payload["index"])

    @_guard
    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count
