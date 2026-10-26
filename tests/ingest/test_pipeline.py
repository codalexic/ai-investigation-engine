from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.errors import DocumentNotFoundError, IngestionError
from app.ingest.chunking import FixedWindowChunker
from app.ingest.dedup import LSHIndex, MinHasher
from app.ingest.pipeline import IngestionPipeline, InMemoryChunkSink
from app.ingest.registry import DocumentRegistry, DocumentVersion, make_engine


@pytest.fixture
def pipeline():
    registry = DocumentRegistry(make_engine("sqlite:///:memory:"))
    result = IngestionPipeline(
        registry, InMemoryChunkSink(), FixedWindowChunker(30, 5), MinHasher(), LSHIndex()
    )
    yield result
    registry.engine.dispose()


def test_lifecycle(pipeline, caplog):
    with caplog.at_level("INFO"):
        first = pipeline.ingest(
            b"# Heading\nINC-42 payments-api", "x.md", extra_metadata={"owner": "Team"}
        )
    assert first.status == "created" and first.chunk_count == 1
    assert caplog.records[-1].doc_id == first.doc_id
    assert caplog.records[-1].duration_ms >= 0
    assert pipeline.registry.get(first.doc_id).extra["owner"] == "Team"
    duplicate = pipeline.ingest(b"# Heading\nINC-42 payments-api", "other.md")
    assert duplicate.status == "duplicate" and duplicate.duplicate_of == first.doc_id
    assert len(pipeline.registry.list()) == 1
    unchanged = pipeline.update(first.doc_id, b"# Heading\nINC-42 payments-api", "x.md")
    assert unchanged.status == "unchanged" and unchanged.version == 1
    updated = pipeline.update(first.doc_id, b"Entirely different content", "x.txt")
    assert pipeline.registry.get(first.doc_id).extra["owner"] == "Team"
    assert pipeline.registry.get(first.doc_id).format == "txt"
    assert updated.status == "updated" and updated.version == 2
    assert all(c.version == 2 for c in pipeline.sink.chunks.values())
    with pipeline.registry.session() as session:
        assert [
            v.version for v in session.scalars(select(DocumentVersion).order_by(DocumentVersion.id))
        ] == [1, 2]
    pipeline.lsh.remove(first.doc_id)
    pipeline.rebuild_lsh()
    assert first.doc_id in pipeline.lsh.signatures
    pipeline.delete(first.doc_id)
    assert not pipeline.sink.chunks and not pipeline.lsh.signatures
    assert pipeline.registry.get(first.doc_id).status == "deleted"
    pipeline.rebuild_lsh()
    assert not pipeline.lsh.signatures
    assert pipeline.ingest(b"Entirely different content", "new.txt").status == "created"
    for call in (
        lambda: pipeline.update("missing", b"x", "x.txt"),
        lambda: pipeline.delete("missing"),
    ):
        with pytest.raises(DocumentNotFoundError):
            call()


@pytest.mark.parametrize("policy", ["flag", "skip"])
def test_near_duplicate(pipeline, policy):
    pipeline.near_dup_policy = policy
    text = " ".join(f"word{i}" for i in range(300))
    first = pipeline.ingest(text.encode(), "x.txt")
    result = pipeline.ingest(text.replace("word150", "edited").encode(), "y.txt")
    assert result.status == "near_duplicate" and result.duplicate_of == first.doc_id
    assert result.warnings
    assert (pipeline.registry.get(result.doc_id) is None) == (policy == "skip")
    assert (result.chunk_count == 0) == (policy == "skip")


def test_bulk(pipeline):
    pipeline.ingest(b"existing", "x.txt")
    records = [
        {"text": "existing"},
        {"text": "new one", "metadata": {"title": "One"}},
        {"text": "new two"},
        {"text": "new one"},
        {"text": "new three"},
    ]
    with patch.object(
        pipeline.registry, "bulk_upsert", wraps=pipeline.registry.bulk_upsert
    ) as bulk:
        result = pipeline.ingest_records(iter(records), 2)
        assert bulk.call_count == 2
    assert result == {"created": 3, "duplicate": 2, "chunk_count": 3}
    assert len(pipeline.registry.list()) == 4
    assert len(pipeline.lsh.signatures) == 4
    pipeline.rebuild_lsh()
    assert len(pipeline.lsh.signatures) == 4
    assert pipeline.ingest_records([], 2)["created"] == 0
    with pytest.raises(IngestionError):
        pipeline.ingest_records([], 0)


def test_bulk_provided_ids(pipeline):
    with patch("app.ingest.pipeline.uuid4", side_effect=AssertionError("Unexpected UUID")):
        result = pipeline.ingest_records(
            [{"doc_id": "stable-one", "text": "first"}, {"doc_id": "stable-two", "text": "second"}],
            batch_size=1,
        )
    assert result["created"] == 2
    assert pipeline.registry.get("stable-one").doc_id == "stable-one"
    assert pipeline.registry.get("stable-two").doc_id == "stable-two"
    assert set(pipeline.lsh.signatures) == {"stable-one", "stable-two"}
    assert {chunk.doc_id for chunk in pipeline.sink.chunks.values()} == {"stable-one", "stable-two"}


@pytest.mark.parametrize("text", ["first", "second"])
def test_bulk_repeated_ids_rejected(pipeline, text):
    with pytest.raises(IngestionError, match="Duplicate document id"):
        pipeline.ingest_records(
            [{"doc_id": "same", "text": "first"}, {"doc_id": "same", "text": text}],
            batch_size=1,
        )


@pytest.mark.parametrize("doc_id", [None, "", 123])
def test_bulk_invalid_ids(pipeline, doc_id):
    with pytest.raises(IngestionError, match="nonempty string"):
        pipeline.ingest_records([{"doc_id": doc_id, "text": "first"}])


def test_bulk_batch_logging(pipeline, caplog):
    with caplog.at_level("INFO"):
        pipeline.ingest_records(
            [{"text": text} for text in ["first", "first", "second", "second"]], batch_size=2
        )
    logs = [record for record in caplog.records if record.name == "app.ingest.pipeline"]
    assert [record.message for record in logs] == [
        "ingestion_batch",
        "ingestion_batch",
        "ingestion_summary",
    ]
    assert [(r.records, r.duplicates, r.chunks) for r in logs] == [(3, 1, 2), (1, 1, 0), (4, 2, 2)]
    assert all(record.duration_ms >= 0 for record in logs)
