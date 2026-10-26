from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.agent.nli import FakeNli
from app.container import Container
from app.core.config import Settings
from app.core.errors import RetrievalError
from app.ingest.registry import make_engine
from app.llm.cache import CachedClient


def settings(tmp_path, **kwargs):
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path}/container.db",
        qdrant_collection="container_test",
        **kwargs,
    )


def test_container_rebuild_and_no_provider(tmp_path):
    configuration = settings(tmp_path)
    first = Container.build(configuration)
    try:
        result = first.pipeline.ingest(b"Persisted indexed content for startup", "startup.txt")
        assert first.llm is None and first.investigator is None
        assert first.bm25_stats.N >= 1
        assert first.chunker is first.pipeline.chunker
        assert first.minhasher is first.pipeline.minhasher
    finally:
        first.close()
    second = Container.build(configuration)
    try:
        assert result.doc_id in second.lsh.signatures
    finally:
        second.close()


def test_container_cache_and_cleanup(tmp_path, monkeypatch):
    client = Mock()
    client.model = "fake"
    monkeypatch.setattr("app.container.build_llm", lambda configuration: client)
    container = Container.build(settings(tmp_path, groq_api_key="test-key"))
    assert isinstance(container.llm, CachedClient)
    assert container.llm.engine is container.engine
    assert isinstance(container.investigator.nli, FakeNli)
    container.close()
    client.close.assert_called_once()


def test_startup_failure_disposes_engine(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path}/failed.db")
    dispose = Mock(wraps=engine.dispose)
    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr("app.container.make_engine", lambda url: engine)
    monkeypatch.setattr("app.container.build_retrieval", Mock(side_effect=RetrievalError("failed")))
    with pytest.raises(RetrievalError):
        Container.build(settings(tmp_path))
    dispose.assert_called_once()


def test_memory_database_shared_across_threads():
    from concurrent.futures import ThreadPoolExecutor

    engine = make_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE sample (value INTEGER)"))
            connection.execute(text("INSERT INTO sample VALUES (7)"))

        def read():
            with engine.connect() as connection:
                return connection.scalar(text("SELECT value FROM sample"))

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(read).result() == 7
    finally:
        engine.dispose()
