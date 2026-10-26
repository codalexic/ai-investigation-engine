from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.retrieval.bm25 import Bm25Encoder, Bm25StatsRepository
from app.retrieval.embeddings import FastEmbedEmbedder, HashingEmbedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.rerank import CrossEncoderReranker, FakeReranker
from app.retrieval.store import QdrantStore, make_qdrant_client


def build_retrieval(settings: Settings, engine: Engine) -> tuple[QdrantStore, HybridRetriever]:
    embedder = (
        HashingEmbedder()
        if settings.app_env == "test"
        else FastEmbedEmbedder(
            settings.embedding_model,
            settings.embedding_batch_size,
            query_cache_size=settings.query_cache_size,
        )
    )
    reranker = (
        FakeReranker()
        if settings.app_env == "test"
        else CrossEncoderReranker(settings.reranker_model)
    )
    repository = Bm25StatsRepository(engine)
    bm25 = Bm25Encoder(repository.load(), settings.bm25_k1, settings.bm25_b)
    store = QdrantStore(
        make_qdrant_client(settings),
        settings.qdrant_collection,
        embedder,
        bm25,
        repository,
        settings.embedding_batch_size,
    )
    try:
        store.ensure_collection()
    except Exception:
        store.client.close()
        raise
    return store, HybridRetriever(store, embedder, bm25, reranker, settings)
