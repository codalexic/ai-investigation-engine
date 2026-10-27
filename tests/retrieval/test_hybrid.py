import numpy as np
import pytest

from app.core.errors import RetrievalError
from app.ingest.chunking import FixedWindowChunker
from app.ingest.dedup import LSHIndex, MinHasher
from app.ingest.pipeline import IngestionPipeline
from app.ingest.registry import DocumentRegistry
from app.retrieval.hybrid import RetrievalConfig
from app.retrieval.store import QueryFilters


class SemanticEmbedder:
    name = "semantic-fake"
    dim = 2

    def embed_documents(self, texts):
        return np.array(
            [[1, 0] if "automobile" in text else [0, 1] for text in texts], dtype=np.float32
        )

    def embed_query(self, text):
        return np.array([1, 0], dtype=np.float32)


def test_modes_and_explanations(retrieval, chunk):
    store, retriever = retrieval
    store.embedder = retriever.embedder = SemanticEmbedder()
    # A separate two-dimensional collection exercises complementary candidate retrieval.
    store.collection = "semantic"
    store.ensure_collection()
    store.upsert_chunks(
        [
            chunk("keyword", "car repair", doc_id="keyword"),
            chunk("semantic", "automobile maintenance", doc_id="semantic"),
        ]
    )
    base = {"candidate_k": 1, "top_k": 2, "rerank": False, "mmr": False}
    dense = retriever.search("car", {**base, "mode": "dense"})
    sparse = retriever.search("car", {**base, "mode": "sparse"})
    hybrid = retriever.search("car", base)
    assert [c.chunk_id for c in dense.chunks] == ["semantic"]
    assert [c.chunk_id for c in sparse.chunks] == ["keyword"]
    assert {c.chunk_id for c in hybrid.chunks} == {"semantic", "keyword"}
    for c in hybrid.chunks:
        assert set(c.explain) == {
            "dense_rank",
            "sparse_rank",
            "rrf_score",
            "boost",
            "rerank_score",
            "mmr_selected",
        }
    assert all(t >= 0 for t in hybrid.timings_ms.values())
    assert retriever.search("car", base, QueryFilters(doc_ids=["absent"])).chunks == []


def test_reranking_mmr_cap_and_overrides(retrieval, chunk):
    store, retriever = retrieval
    store.upsert_chunks(
        [
            chunk("one", "car", doc_id="same"),
            chunk("two", "car repair", doc_id="same"),
            chunk("three", "car repair garage", doc_id="other"),
        ]
    )
    result = retriever.search(
        "car repair garage", {"rerank": True, "mmr": False, "max_chunks_per_doc": 1}
    )
    assert result.chunks[0].chunk_id == "three"
    assert result.chunks[0].explain["rerank_score"] == 3
    assert len(result.chunks) == 2
    mmr_result = retriever.search("car repair", RetrievalConfig(rerank=False))
    assert all(c.explain["mmr_selected"] for c in mmr_result.chunks)
    assert retriever.config.rerank is True
    with pytest.raises(RetrievalError):
        retriever.search("  ")


def test_ingestion_lifecycle(retrieval):
    store, retriever = retrieval
    registry = DocumentRegistry(store.stats_repo.engine)
    pipeline = IngestionPipeline(
        registry, store, FixedWindowChunker(30, 5), MinHasher(), LSHIndex()
    )
    first = pipeline.ingest(
        b"# Runbook\nRestore payment-service via rollback CHG-1042", "runbook.md"
    )
    assert retriever.search("CHG-1042").chunks[0].doc_id == first.doc_id
    old_ids = [c.chunk_id for c in store.get_document_chunks(first.doc_id)]
    pipeline.update(first.doc_id, b"# Updated\nDatabase failover recovery INC-55", "runbook.md")
    assert store.get_chunks(old_ids) == []
    assert all(c.payload["version"] == 2 for c in store.get_document_chunks(first.doc_id))
    assert retriever.search("CHG-1042", {"mode": "sparse"}).chunks == []
    assert retriever.search("INC-55").chunks
    pipeline.delete(first.doc_id)
    assert retriever.search("recovery").chunks == []
    assert store.bm25.stats.N == 0


def test_reranking_changes_dense_order(retrieval, monkeypatch):
    from app.retrieval.store import ScoredChunk

    store, retriever = retrieval
    first = ScoredChunk("first", 0.9, {"doc_id": "one", "text": "unrelated background"})
    second = ScoredChunk("second", 0.3, {"doc_id": "two", "text": "rollback payment-service"})
    monkeypatch.setattr(store, "dense_search", lambda *args, **kw: [first, second])
    options = {"mode": "dense", "mmr": False, "rerank": False}
    assert retriever.search("rollback", options).chunks[0].chunk_id == "first"
    result = retriever.search("rollback", {**options, "rerank": True})
    assert result.chunks[0].chunk_id == "second"
    assert result.chunks[0].explain["rerank_score"] == 1.0
