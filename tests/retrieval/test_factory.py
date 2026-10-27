from unittest.mock import Mock

from app.core.config import Settings
from app.retrieval.factory import build_retrieval


def test_normal_factory_uses_configured_models(monkeypatch):
    embedder = Mock()
    embedder.dim = 7
    embedding_constructor = Mock(return_value=embedder)
    reranking_constructor = Mock()
    store_constructor = Mock()
    monkeypatch.setattr("app.retrieval.factory.FastEmbedEmbedder", embedding_constructor)
    monkeypatch.setattr("app.retrieval.factory.CrossEncoderReranker", reranking_constructor)
    monkeypatch.setattr("app.retrieval.factory.QdrantStore", store_constructor)
    monkeypatch.setattr("app.retrieval.factory.make_qdrant_client", Mock())
    monkeypatch.setattr("app.retrieval.factory.Bm25StatsRepository", Mock())
    settings = Settings(_env_file=None, query_cache_size=17, embedding_batch_size=12)
    store, retriever = build_retrieval(settings, Mock())
    embedding_constructor.assert_called_once_with(
        settings.embedding_model, 12, query_cache_size=17, cache_dir=None
    )
    reranking_constructor.assert_called_once_with(settings.reranker_model, cache_dir=None)
    store.ensure_collection.assert_called_once_with()
    assert retriever.store is store
    assert retriever.config.candidate_k == settings.candidate_k
