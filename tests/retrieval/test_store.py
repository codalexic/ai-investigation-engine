from datetime import date
from unittest.mock import Mock

import pytest

from app.core.errors import RetrievalError
from app.retrieval.store import QueryFilters


def test_store_lifecycle(retrieval, chunk):
    store, _ = retrieval
    store.ensure_collection()
    chunks = [
        chunk("b", index=1),
        chunk("a", index=0),
        chunk("c", doc_id="other", doc_type="ticket", entities={"services": ["other-service"]}),
    ]
    store.upsert_chunks(chunks)
    assert store.count() == store.bm25.stats.N == 3
    assert [c.chunk_id for c in store.get_document_chunks("doc")] == ["a", "b"]
    assert {c.chunk_id for c in store.get_chunks(["b", "a"])} == {"a", "b"}
    query = store.bm25.encode_query("rollback")
    for filters, expected in [
        (QueryFilters(doc_types=["ticket"]), {"c"}),
        (QueryFilters(services=["payment-service"]), {"a", "b"}),
        (QueryFilters(date_from=date(2025, 3, 1), date_to=date(2025, 3, 31)), {"a", "b", "c"}),
        (QueryFilters(date_from=date(2026, 1, 1)), set()),
        (QueryFilters(change_ids=["CHG-1042"], doc_ids=["doc"]), {"a", "b"}),
        (QueryFilters(incident_ids=["INC-1"]), set()),
    ]:
        assert {c.chunk_id for c in store.sparse_search(query, 10, filters)} == expected
        assert {
            c.chunk_id
            for c in store.dense_search(store.embedder.embed_query("rollback"), 10, filters)
        } == expected
    store.upsert_chunks([chunk("a", text="new content")])
    assert store.bm25.stats.N == 3
    assert store.bm25.stats.df["rollback"] == 2
    store.delete_document("doc")
    assert store.count() == store.bm25.stats.N == 1
    assert store.stats_repo.load().N == 1
    store.delete_document("other")
    assert store.count() == store.bm25.stats.N == 0
    assert not store.bm25.stats.df
    store.delete_document("missing")


def test_errors_wrapped(retrieval):
    store, _ = retrieval
    store.client = Mock()
    store.client.count.side_effect = RuntimeError("offline")
    with pytest.raises(RetrievalError, match="count"):
        store.count()


def test_scroll_pagination(retrieval, chunk):
    store, _ = retrieval
    store.upsert_chunks([chunk(str(i), index=i) for i in range(270)])
    assert len(store.get_document_chunks("doc")) == 270
    store.delete_document("doc")
    assert store.bm25.stats.N == 0


def test_failed_upsert_preserves_statistics(retrieval, chunk, monkeypatch):
    store, _ = retrieval
    store.upsert_chunks([chunk()])
    previous = store.stats_repo.load()
    with monkeypatch.context() as scoped:
        scoped.setattr(store.embedder, "embed_documents", Mock(side_effect=RuntimeError("failed")))
        with pytest.raises(RetrievalError):
            store.upsert_chunks([chunk(text="replacement")])
    assert store.bm25.stats == previous
    with monkeypatch.context() as scoped:
        scoped.setattr(store.client, "upsert", Mock(side_effect=RuntimeError("failed")))
        with pytest.raises(RetrievalError):
            store.upsert_chunks([chunk(text="replacement")])
    assert store.bm25.stats.N == previous.N
    assert store.bm25.stats.df == previous.df
    assert store.stats_repo.load() == previous
    assert store.get_chunks(["a"])[0].payload["text"] == "payment-service rollback CHG-1042"


def test_client_configuration(monkeypatch):
    from app.core.config import Settings
    from app.retrieval.store import make_qdrant_client

    constructor = Mock()
    monkeypatch.setattr("app.retrieval.store.QdrantClient", constructor)
    make_qdrant_client(Settings(_env_file=None))
    constructor.assert_called_once_with(":memory:")
    constructor.reset_mock()
    make_qdrant_client(
        Settings(
            _env_file=None,
            qdrant_url="http://localhost:6333",
            qdrant_api_key="secret",
            request_timeout_s=12,
        )
    )
    constructor.assert_called_once_with(url="http://localhost:6333", api_key="secret", timeout=12)
