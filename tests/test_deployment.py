import json
from contextlib import closing
from unittest.mock import Mock

import pytest
from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine, select

from app.core.config import Settings
from app.core.errors import MigrationError
from app.corpus import migrate
from app.ingest.registry import DocumentRegistry, DocumentVersion, IndexMeta
from app.retrieval.bm25 import Bm25Statistics, Bm25StatsRepository
from scripts.deploy_space import ALLOW_PATTERNS, deploy_space
from scripts.download_models import download_models


def configuration(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_downloads_use_configured_cache(monkeypatch):
    embedding, reranking, nli = Mock(), Mock(), Mock()
    monkeypatch.setattr("scripts.download_models.FastEmbedEmbedder", embedding)
    monkeypatch.setattr("app.retrieval.rerank.CrossEncoderReranker", reranking)
    monkeypatch.setattr("app.agent.nli.OnnxNliModel", nli)
    settings = configuration(model_cache_dir="cache")
    download_models(settings)
    embedding.assert_called_once_with(settings.embedding_model, cache_dir="cache")
    reranking.assert_called_once_with(settings.reranker_model, cache_dir="cache")
    nli.assert_called_once_with(settings.nli_model, "cache")
    nli.return_value._load.assert_called_once()


def test_model_wrappers_are_lazy_and_honor_cache(monkeypatch):
    from app.agent.nli import OnnxNliModel
    from app.retrieval.embeddings import FastEmbedEmbedder
    from app.retrieval.rerank import CrossEncoderReranker

    embedding, reranking = Mock(), Mock()
    monkeypatch.setattr("fastembed.TextEmbedding", embedding)
    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", reranking)
    embedder = FastEmbedEmbedder("embedding", cache_dir="cache")
    reranker = CrossEncoderReranker("reranker", cache_dir="cache")
    assert not embedding.called and not reranking.called
    assert embedder.model is embedding.return_value
    assert reranker.model is reranking.return_value
    assert embedding.call_args.kwargs["cache_dir"] == "cache"
    assert reranking.call_args.kwargs["cache_dir"] == "cache"
    assert OnnxNliModel("nli", "cache").cache_dir == "cache"


def test_vector_resume_and_counts(tmp_path, monkeypatch):
    with closing(QdrantClient(":memory:")) as source, closing(QdrantClient(":memory:")) as target:
        source.create_collection(
            "source",
            vectors_config={"dense": models.VectorParams(size=2, distance=models.Distance.COSINE)},
            sparse_vectors_config={"bm25": models.SparseVectorParams()},
        )
        source.upsert(
            "source",
            [
                models.PointStruct(
                    id=i,
                    vector={
                        "dense": [1.0, 0.0],
                        "bm25": models.SparseVector(indices=[1], values=[1.0]),
                    },
                    payload={"text": str(i)},
                )
                for i in range(5)
            ],
        )
        checkpoint = tmp_path / "checkpoint.json"
        original = migrate._upsert
        calls = []

        def interrupted(client, collection, points):
            calls.append(points)
            if len(calls) == 2:
                raise OSError("interrupted")
            original(client, collection, points)

        monkeypatch.setattr(migrate, "_upsert", interrupted)
        with pytest.raises(MigrationError):
            migrate.migrate_vectors(source, target, "source", "target", checkpoint, batch=2)
        assert target.count("target").count == 2
        assert json.loads(checkpoint.read_text())["offset"] == 2
        monkeypatch.setattr(migrate, "_upsert", original)
        assert migrate.migrate_vectors(source, target, "source", "target", checkpoint, 2) == 5
        assert migrate.migrate_vectors(source, target, "source", "target", checkpoint, 2) == 5
        assert target.retrieve("target", [4], with_vectors=True)[0].payload == {"text": "4"}
        assert source.count("source").count == 5
        target.delete("target", models.PointIdsList(points=[4]))
        with pytest.raises(MigrationError, match="counts differ"):
            migrate.migrate_vectors(source, target, "source", "target", checkpoint)
        assert (
            migrate.migrate_vectors(source, target, "source", "target", checkpoint, replace=True)
            == 5
        )


def test_sql_copy_idempotent_and_replace(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path}/source.db")
    target = create_engine(f"sqlite:///{tmp_path}/target.db")
    try:
        registry = DocumentRegistry(source)
        Bm25StatsRepository(source).save(Bm25Statistics(N=3, total_length=7))
        registry.upsert(
            {
                "doc_id": "example",
                "source": "x",
                "format": "txt",
                "title": "Example",
                "doc_type": "other",
                "content_hash": "hash",
                "minhash": b"binary",
                "chunk_strategy": "fixed",
                "entities": {},
                "extra": {},
            }
        )
        with source.begin() as connection:
            connection.execute(
                DocumentVersion.__table__.insert().values(
                    doc_id="example", version=1, content_hash="hash"
                )
            )
        counts = migrate.migrate_sql(source, target)
        assert counts["documents"] == 1
        assert counts["document_versions"] == 1
        assert counts == migrate.migrate_sql(source, target)
        assert DocumentRegistry(target).get("example").minhash == b"binary"
        with target.begin() as connection:
            connection.execute(IndexMeta.__table__.insert().values(key="extra", value=2))
        with pytest.raises(MigrationError, match="Row count"):
            migrate.migrate_sql(source, target)
        assert migrate.migrate_sql(source, target, replace=True) == counts
        with source.connect() as connection:
            assert connection.scalar(select(IndexMeta.value)) == 1
    finally:
        source.dispose()
        target.dispose()


def test_deploy_dry_run_and_upload(tmp_path, monkeypatch, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text("pass")
    settings = configuration(
        hf_token="token-value",
        groq_api_key="provider-value",
        admin_token="admin-value",
        qdrant_url="https://target.example",
        database_url="postgresql+psycopg://secret-database",
    )
    api = Mock()
    monkeypatch.setattr("scripts.deploy_space.HfApi", api)
    deploy_space("user/space", tmp_path, settings, dry_run=True)
    assert not api.called
    output = capsys.readouterr().out
    assert "GROQ_API_KEY" in output and "app/main.py" in output
    for secret in ("token-value", "provider-value", "admin-value", "secret-database"):
        assert secret not in output
    deploy_space("user/space", tmp_path, settings)
    assert api.return_value.upload_folder.call_args.kwargs["allow_patterns"] == ALLOW_PATTERNS
    names = {call.kwargs["key"] for call in api.return_value.add_space_secret.call_args_list}
    assert {"GROQ_API_KEY", "QDRANT_URL", "DATABASE_URL", "ADMIN_TOKEN"} <= names
    assert "HF_TOKEN" not in names


def test_warmup_loads_models_and_logs_failure(monkeypatch):
    from app.agent.nli import OnnxNliModel
    from app.container import Container

    container = Mock()
    container.settings.rerank_enabled = True
    container.investigator.nli = OnnxNliModel("test", "cache")
    load = Mock()
    monkeypatch.setattr(container.investigator.nli, "_load", load)
    Container.warm_models(container)
    container.store.embedder.embed_query.assert_called_once_with("warmup")
    load.assert_called_once()
    logger = Mock()
    monkeypatch.setattr("app.container.get_logger", lambda name: logger)
    container.store.embedder.embed_query.side_effect = RuntimeError("failure")
    Container.warm_models(container)
    logger.exception.assert_called_once_with("model_warmup_failed")


def test_warmup_does_not_block_health(tmp_path, monkeypatch):
    from threading import Event

    from fastapi.testclient import TestClient

    from app.api.main import create_app

    started, release = Event(), Event()

    def warm(container):
        started.set()
        assert release.wait(10)

    monkeypatch.setattr("app.container.Container.warm_models", warm)
    settings = configuration(
        app_env="test",
        warmup=True,
        database_url=f"sqlite:///{tmp_path}/warm.db",
        qdrant_url=":memory:",
        qdrant_collection="warm_test",
    )
    with TestClient(create_app(settings)) as client:
        try:
            assert started.wait(5)
            assert client.get("/health").status_code == 200
        finally:
            release.set()


def test_migration_cli_opens_source_read_only(tmp_path, monkeypatch, capsys):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from scripts import migrate_to_cloud

    source_path = tmp_path / "cli_source.db"
    engine = create_engine(f"sqlite:///{source_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sentinel (id INTEGER)"))
    engine.dispose()
    monkeypatch.setattr(
        "sys.argv",
        [
            "migrate_to_cloud",
            "--source-qdrant",
            "http://source",
            "--target-qdrant",
            "https://target",
            "--source-db",
            f"sqlite:///{source_path}",
            "--target-db",
            f"sqlite:///{tmp_path}/target.db",
        ],
    )
    monkeypatch.setattr(migrate_to_cloud, "Settings", lambda: configuration())
    monkeypatch.setattr(migrate_to_cloud, "QdrantClient", Mock())
    monkeypatch.setattr(migrate_to_cloud, "migrate_vectors", Mock(return_value=0))

    def check_source(source, target, replace):
        with source.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM sentinel")).scalar() == 0
            with pytest.raises(OperationalError, match="readonly"):
                connection.execute(text("CREATE TABLE forbidden (id INTEGER)"))
        return {"documents": 0}

    monkeypatch.setattr(migrate_to_cloud, "migrate_sql", check_source)
    migrate_to_cloud.main()
    assert "Verified 0 vectors" in capsys.readouterr().out


def test_vector_batch_retries(monkeypatch):
    from tenacity import wait_none

    client = Mock()
    client.upsert.side_effect = [OSError("temporary"), None]
    monkeypatch.setattr(migrate._upsert.retry, "wait", wait_none())
    migrate._upsert(client, "isolated_target", [])
    assert client.upsert.call_count == 2
