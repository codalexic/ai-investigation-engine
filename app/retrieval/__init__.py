from app.retrieval.bm25 import Bm25Encoder, Bm25Statistics, Bm25StatsRepository, bm25_scores
from app.retrieval.embeddings import Embedder, FastEmbedEmbedder, HashingEmbedder
from app.retrieval.factory import build_retrieval
from app.retrieval.hybrid import HybridRetriever, RetrievalConfig, RetrievalResult, RetrievedChunk
from app.retrieval.store import QdrantStore, QueryFilters, ScoredChunk, make_qdrant_client

__all__ = [
    "Bm25Encoder",
    "Bm25Statistics",
    "Bm25StatsRepository",
    "CrossEncoderReranker",
    "Embedder",
    "FakeReranker",
    "FastEmbedEmbedder",
    "HashingEmbedder",
    "HybridRetriever",
    "NoopReranker",
    "QdrantStore",
    "QueryFilters",
    "Reranker",
    "RetrievalConfig",
    "RetrievalResult",
    "RetrievedChunk",
    "ScoredChunk",
    "bm25_scores",
    "build_retrieval",
    "make_qdrant_client",
]


def __getattr__(name: str):
    if name in {"CrossEncoderReranker", "FakeReranker", "NoopReranker", "Reranker"}:
        from app.retrieval import rerank

        return getattr(rerank, name)
    raise AttributeError(name)
