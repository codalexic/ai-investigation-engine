import argparse
import json
import re
from collections import Counter
from pathlib import Path
from time import perf_counter

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import ConfigurationError, IngestionError
from app.core.logging import get_logger
from app.ingest.chunking import build_chunker
from app.ingest.dedup import LSHIndex, MinHasher
from app.ingest.pipeline import IngestionPipeline
from app.ingest.registry import DocumentRecord, DocumentRegistry, make_engine
from app.retrieval.bm25 import Bm25Encoder, Bm25StatsRepository
from app.retrieval.embeddings import FastEmbedEmbedder, HashingEmbedder
from app.retrieval.store import QdrantStore, make_qdrant_client

logger = get_logger(__name__)
SOURCES = ("hotpotqa", "postmortems", "synthetic")


def index_sources(
    pipeline: IngestionPipeline,
    sources: list[str],
    root: Path = Path("."),
    limit: int | None = None,
    batch_size: int = 100,
) -> dict:
    if batch_size < 1 or (limit is not None and limit < 0) or set(sources) - set(SOURCES):
        raise ConfigurationError("Invalid corpus sources, limit, or batch size")
    started = perf_counter()
    pipeline.rebuild_lsh()
    with pipeline.registry.session() as session:
        active = {
            record.doc_id: record.version
            for record in session.scalars(
                select(DocumentRecord).where(DocumentRecord.status == "active")
            )
        }
    counts = {source: 0 for source in sources}
    totals: Counter = Counter()
    processed = 0
    for source in sources:
        if source == "synthetic":
            directory = root / "data/synthetic"
            if not directory.is_dir():
                raise IngestionError(f"Missing corpus directory: {directory}")
            for path in sorted(directory.iterdir()):
                if not path.is_file():
                    continue
                stem = path.stem
                updated = stem.endswith(".v2")
                key = "syn:" + (stem[:-3] if updated else stem)
                if active.get(key, 0) >= (2 if updated else 1):
                    continue
                if limit is not None and processed >= limit:
                    break
                result = (
                    pipeline.update(key, path.read_bytes(), path.name)
                    if updated
                    else pipeline.ingest(path.read_bytes(), path.name, key)
                )
                if result.chunk_count:
                    active[key] = result.version
                counts[source] += int(result.status != "duplicate")
                totals["duplicates"] += int(result.status == "duplicate")
                totals["near_duplicates"] += int(
                    result.duplicate_of is not None and result.status != "duplicate"
                )
                totals["chunks"] += result.chunk_count
                processed += 1
                if processed % batch_size == 0:
                    elapsed = perf_counter() - started
                    logger.info(
                        "corpus_progress",
                        extra={"records": processed, "records_per_sec": processed / elapsed},
                    )
        else:
            path = root / f"data/corpus/{source}.jsonl"
            batch = []

            def flush(batch: list[dict] = batch, source: str = source) -> None:
                nonlocal processed
                if not batch:
                    return
                result = pipeline.ingest_records(batch, batch_size=batch_size)
                counts[source] += result["created"]
                totals["duplicates"] += result["duplicate"]
                totals["chunks"] += result["chunk_count"]
                processed += len(batch)
                batch.clear()
                elapsed = perf_counter() - started
                logger.info(
                    "corpus_progress",
                    extra={"records": processed, "records_per_sec": processed / elapsed},
                )

            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record["doc_id"] in active:
                        continue
                    if limit is not None and processed + len(batch) >= limit:
                        break
                    batch.append(record)
                    if len(batch) >= batch_size:
                        flush()
                flush()
    elapsed = perf_counter() - started
    return {
        "counts_per_source": counts,
        "duplicates": totals["duplicates"],
        "near_duplicates": totals["near_duplicates"],
        "chunks": totals["chunks"],
        "seconds": elapsed,
        "records_per_sec": processed / elapsed,
    }


def run(
    settings: Settings,
    sources: list[str],
    root: Path = Path("."),
    limit: int | None = None,
    batch_size: int = 100,
    recreate: bool = False,
) -> dict:
    engine = make_engine(settings.database_url)
    client = make_qdrant_client(settings)
    try:
        registry = DocumentRegistry(engine)
        repository = Bm25StatsRepository(engine)
        if recreate:
            if client.collection_exists(settings.qdrant_collection):
                client.delete_collection(settings.qdrant_collection)
            from app.ingest.registry import Base

            Base.metadata.drop_all(engine)
            registry.create_all()
            with engine.begin() as connection:
                connection.execute(repository.terms.delete())
                connection.execute(repository.meta.delete())
        embedder = (
            HashingEmbedder()
            if settings.app_env == "test"
            else FastEmbedEmbedder(settings.embedding_model, settings.embedding_batch_size)
        )
        store = QdrantStore(
            client,
            settings.qdrant_collection,
            embedder,
            Bm25Encoder(repository.load(), settings.bm25_k1, settings.bm25_b),
            repository,
            settings.embedding_batch_size,
            bulk=True,
            bulk_timeout_s=settings.request_timeout_s,
        )
        store.ensure_collection()
        pipeline = IngestionPipeline(
            registry, store, build_chunker(settings), MinHasher(), LSHIndex()
        )
        result = index_sources(pipeline, sources, root, limit, batch_size)
        store.finish_bulk()
        point_count = store.count()
        with registry.session() as session:
            expected = (
                session.scalar(
                    select(func.sum(DocumentRecord.chunk_count)).where(
                        DocumentRecord.status == "active"
                    )
                )
                or 0
            )
        if point_count != expected:
            raise IngestionError(f"Registry/vector count mismatch: {expected} != {point_count}")
        result.update(
            embedding_model=settings.embedding_model,
            chunk_strategy=settings.chunk_strategy,
            qdrant_point_count=point_count,
        )
        path = root / f"eval/results/indexing_{settings.qdrant_collection}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        client.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Index reproducible investigation corpora")
    parser.add_argument("--sources", default=",".join(SOURCES))
    parser.add_argument("--collection", default="documents")
    parser.add_argument("--chunk-strategy", choices=("structure", "fixed"), default="structure")
    parser.add_argument("--embedding-model")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--qdrant-url")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.collection):
        raise ConfigurationError(
            "Collection must contain only letters, numbers, underscores, hyphens"
        )
    overrides = {
        "qdrant_collection": args.collection,
        "chunk_strategy": args.chunk_strategy,
        "database_url": args.database_url or f"sqlite:///./data/registry_{args.collection}.db",
    }
    for key in ("embedding_model", "qdrant_url"):
        if getattr(args, key):
            overrides[key] = getattr(args, key)
    run(
        Settings(**overrides),
        args.sources.split(","),
        limit=args.limit,
        batch_size=args.batch_size,
        recreate=args.recreate,
    )
