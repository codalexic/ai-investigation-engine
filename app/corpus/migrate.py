"""Copy an index to remote stores without modifying either source."""

import json
from pathlib import Path

from qdrant_client import QdrantClient, models
from sqlalchemy import MetaData, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.errors import MigrationError
from app.ingest.registry import Base
from app.retrieval.bm25 import Bm25StatsRepository
from app.retrieval.store import QdrantStore

TABLES = ("documents", "document_versions", "bm25_terms", "bm25_meta", "meta")


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=8), reraise=True)
def _upsert(client: QdrantClient, collection: str, points: list[models.PointStruct]) -> None:
    client.upsert(collection, points, wait=True)


def migrate_vectors(
    source: QdrantClient,
    target: QdrantClient,
    source_collection: str,
    target_collection: str,
    checkpoint: Path,
    batch: int = 256,
    identity: str = "",
    replace: bool = False,
) -> int:
    if source is target and source_collection == target_collection:
        raise MigrationError("Source and target collection must differ")
    if batch < 1:
        raise MigrationError("Batch must be positive")
    try:
        info = source.get_collection(source_collection)
        signature = [identity, source_collection, target_collection]
        state = json.loads(checkpoint.read_text()) if checkpoint.exists() and not replace else {}
        if state and state.get("identity") != signature:
            raise MigrationError("Checkpoint belongs to another migration")
        if replace and target.collection_exists(target_collection):
            target.delete_collection(target_collection)
        if not target.collection_exists(target_collection):
            if state:
                raise MigrationError("Checkpoint target no longer exists; use --replace")
            target.create_collection(
                target_collection,
                vectors_config=info.config.params.vectors,
                sparse_vectors_config=info.config.params.sparse_vectors,
            )
        target_info = target.get_collection(target_collection)
        if (
            target_info.config.params.vectors != info.config.params.vectors
            or target_info.config.params.sparse_vectors != info.config.params.sparse_vectors
        ):
            raise MigrationError("Target vector configuration differs from source")
        QdrantStore.ensure_payload_indexes(target, target_collection)
        for key, schema in info.payload_schema.items():
            target.create_payload_index(target_collection, key, schema.params or schema.data_type)
        offset = state.get("offset")
        if not state.get("complete"):
            while True:
                points, offset = source.scroll(
                    source_collection,
                    limit=batch,
                    offset=offset,
                    with_vectors=True,
                    with_payload=True,
                )
                if points:
                    _upsert(
                        target,
                        target_collection,
                        [
                            models.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                            for p in points
                        ],
                    )
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                temporary = checkpoint.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "identity": signature,
                            "offset": offset,
                            "complete": offset is None,
                        }
                    )
                )
                temporary.replace(checkpoint)
                if offset is None:
                    break
        count = source.count(source_collection, exact=True).count
        if target.count(target_collection, exact=True).count != count:
            raise MigrationError("Vector counts differ; stop indexing and retry with --replace")
        return count
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("Vector migration failed") from exc


def migrate_sql(source: Engine, target: Engine, replace: bool = False) -> dict[str, int]:
    if source.url == target.url:
        raise MigrationError("Source and target database must differ")
    try:
        metadata = MetaData()
        for name in ("documents", "document_versions", "meta"):
            Base.metadata.tables[name].to_metadata(metadata)
        repository = Bm25StatsRepository(source, read_only=True)
        repository.terms.to_metadata(metadata)
        repository.meta.to_metadata(metadata)
        tables = list(metadata.sorted_tables)
        metadata.create_all(target)
        counts = {}
        insert = pg_insert if target.dialect.name == "postgresql" else sqlite_insert
        with source.connect() as reader, reader.begin(), target.begin() as writer:
            if replace:
                for table in reversed(tables):
                    writer.execute(table.delete())
            duplicates = []
            for table in tables:
                count = 0
                rows = (
                    reader.execution_options(stream_results=True)
                    .execute(select(table).order_by(*table.primary_key.columns))
                    .mappings()
                )
                for batch in rows.partitions(5000):
                    statement = insert(table)
                    statement = statement.on_conflict_do_update(
                        index_elements=list(table.primary_key.columns),
                        set_={
                            c.name: statement.excluded[c.name]
                            for c in table.columns
                            if not c.primary_key
                        },
                    )
                    values = [dict(row) for row in batch]
                    if table.name == "documents":
                        for row in values:
                            if row["duplicate_of"]:
                                duplicates.append((row["doc_id"], row["duplicate_of"]))
                                row["duplicate_of"] = None
                    writer.execute(statement, values)
                    count += len(batch)
                actual = writer.scalar(select(func.count()).select_from(table))
                if actual != count:
                    raise MigrationError(f"Row count differs for {table.name}; use --replace")
                counts[table.name] = count
            documents = metadata.tables["documents"]
            for doc_id, duplicate_of in duplicates:
                writer.execute(
                    update(documents)
                    .where(documents.c.doc_id == doc_id)
                    .values(duplicate_of=duplicate_of)
                )
            if target.dialect.name == "postgresql":
                from sqlalchemy import text

                writer.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('document_versions', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM document_versions), 1), "
                        "EXISTS(SELECT 1 FROM document_versions))"
                    )
                )
        return counts
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("SQL migration failed") from exc
