from datetime import date

import pytest
from sqlalchemy import select

from app.core.errors import DocumentNotFoundError
from app.ingest.dedup import MinHasher
from app.ingest.registry import DocumentRecord, DocumentRegistry, DocumentVersion, make_engine


def test_registry_crud(tmp_path):
    path = tmp_path / "nested" / "registry.db"
    registry = DocumentRegistry(make_engine(f"sqlite:///{path.as_posix()}"))
    registry.create_all()
    assert path.exists()
    fields = dict(
        doc_id="id",
        source="x.md",
        format="md",
        title="Operations handbook",
        doc_type="runbook",
        created_at=date(2024, 3, 14),
        content_hash="hash",
        version=1,
        status="active",
        minhash=MinHasher().signature("test").tobytes(),
        entities={"services": ["payments-api"]},
        extra={"a": 1},
        chunk_count=2,
        chunk_strategy="structure",
    )
    registry.upsert(fields)
    record = registry.get("id")
    assert record.title == "Operations handbook"
    assert registry.get_by_hash("hash").doc_id == "id"
    assert registry.list(doc_type="runbook", q="HANDBOOK")[0].doc_id == "id"
    assert registry.list(offset=1) == []
    assert registry.list(doc_type="ticket") == []
    record.title = "Changed"
    registry.upsert(record)
    assert registry.get("id").title == "Changed"
    registry.add_version("id", 1, "hash")
    with registry.session() as session:
        assert session.scalar(select(DocumentVersion)).version == 1
    assert next(iter(registry.iter_signatures()))[0] == "id"
    registry.mark_deleted("id")
    assert registry.get("id").status == "deleted"
    assert registry.get_by_hash("hash") is None
    assert registry.list() == [] and list(registry.iter_signatures()) == []
    assert registry.get("missing") is None
    with pytest.raises(DocumentNotFoundError):
        registry.mark_deleted("missing")
    with pytest.raises(RuntimeError), registry.session() as session:
        session.add(DocumentRecord(**{**fields, "doc_id": "rollback"}))
        raise RuntimeError("rollback")
    assert registry.get("rollback") is None
    registry.engine.dispose()
