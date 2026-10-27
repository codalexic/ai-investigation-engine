from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine, make_url

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.retrieval.bm25 import Bm25Encoder, Bm25StatsRepository
from app.retrieval.embeddings import FastEmbedEmbedder, HashingEmbedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.rerank import CrossEncoderReranker, FakeReranker
from app.retrieval.store import QdrantStore, make_qdrant_client


@dataclass
class EvaluationConnection:
    settings: Settings
    engine: Engine
    store: QdrantStore
    retriever: HybridRetriever


@contextmanager
def connect(settings: Settings) -> Iterator[EvaluationConnection]:
    """Open existing indexes without schema initialization or vector writes."""
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        if not url.database or not Path(url.database).is_file():
            raise ConfigurationError("Evaluation requires an existing registry database")
        database = Path(url.database).resolve().as_posix()
        engine = create_engine(f"sqlite:///file:{database}?mode=ro&uri=true")
    else:
        engine = create_engine(url)

        @event.listens_for(engine, "begin")
        def read_only(connection: Connection) -> None:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    client = None
    try:
        client = make_qdrant_client(settings)
        if not client.collection_exists(settings.qdrant_collection):
            raise ConfigurationError("Evaluation collection does not exist")
        repository = Bm25StatsRepository(engine, read_only=True)
        embedder = (
            HashingEmbedder()
            if settings.app_env == "test"
            else FastEmbedEmbedder(settings.embedding_model, settings.embedding_batch_size)
        )
        reranker = (
            FakeReranker()
            if settings.app_env == "test"
            else CrossEncoderReranker(settings.reranker_model)
        )
        store = QdrantStore(
            client,
            settings.qdrant_collection,
            embedder,
            Bm25Encoder(repository.load(), settings.bm25_k1, settings.bm25_b),
            repository,
            settings.embedding_batch_size,
        )
        yield EvaluationConnection(
            settings,
            engine,
            store,
            HybridRetriever(store, embedder, store.bm25, reranker, settings),
        )
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            engine.dispose()
