import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.container import Container
from app.core.config import Settings
from scripts.download_models import download_models


@pytest.mark.parametrize(
    "profile,batch,steps,enabled", [("full", 64, 5, True), ("lite", 8, 3, False)]
)
def test_profile_defaults(profile, batch, steps, enabled):
    settings = Settings(_env_file=None, deployment_profile=profile)
    assert settings.embedding_batch_size == batch
    assert settings.agent_max_steps == steps
    assert settings.rerank_enabled == settings.nli_enabled == enabled
    assert settings.lsh_rebuild_on_startup == enabled
    if profile == "lite":
        assert settings.warmup is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "lite")
    for name, value in {
        "RERANK_ENABLED": "true",
        "NLI_ENABLED": "true",
        "WARMUP": "true",
        "LSH_REBUILD_ON_STARTUP": "true",
        "EMBEDDING_BATCH_SIZE": "16",
        "AGENT_MAX_STEPS": "7",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.rerank_enabled and settings.nli_enabled and settings.warmup
    assert settings.lsh_rebuild_on_startup
    assert settings.embedding_batch_size == 16 and settings.agent_max_steps == 7


def test_empty_lsh_retains_exact_dedup(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        deployment_profile="lite",
        database_url=f"sqlite:///{tmp_path}/lite.db",
        qdrant_url=":memory:",
    )
    first = Container.build(settings)
    try:
        result = first.pipeline.ingest(b"A persistent document with sufficient text.", "source.txt")
        assert result.doc_id in first.lsh.signatures
    finally:
        first.close()
    second = Container.build(settings)
    try:
        assert not second.lsh.signatures
        duplicate = second.pipeline.ingest(
            b"A persistent document with sufficient text.", "copy.txt"
        )
        assert duplicate.status == "duplicate"
        assert duplicate.duplicate_of == result.doc_id
    finally:
        second.close()


def test_lite_container_does_not_import_models():
    code = """
import sys
from app.container import Container
from app.core.config import Settings
from unittest.mock import Mock
import app.container
app.container.build_llm = lambda settings: Mock()
container = Container.build(Settings(_env_file=None, app_env='test', deployment_profile='lite',
    database_url='sqlite:///:memory:', qdrant_url=':memory:', groq_api_key='test'))
try:
    assert container.investigator.nli is None
    assert container.store.embedder is container.retriever.embedder
    assert 'app.agent.nli' not in sys.modules
    assert 'app.retrieval.rerank' not in sys.modules
finally:
    container.close()
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_lite_model_download(monkeypatch):
    embedding = Mock()
    monkeypatch.setattr("scripts.download_models.FastEmbedEmbedder", embedding)
    download_models(Settings(_env_file=None, deployment_profile="lite"))
    embedding.assert_called_once()


def test_deployment_files():
    docker = Path("Dockerfile.lite").read_text()
    assert "ARG PROFILE=lite" in docker and "DEPLOYMENT_PROFILE=lite" in docker
    assert "${PORT:-7860}" in docker
    blueprint = Path("render.yaml").read_text()
    assert "dockerfilePath: ./Dockerfile.lite" in blueprint
    assert "healthCheckPath: /health" in blueprint and "plan: free" in blueprint
    for name in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "DATABASE_URL",
        "ADMIN_TOKEN",
    ):
        assert f"key: {name}\n        sync: false" in blueprint
    assert blueprint.count("value:") == 3


@pytest.mark.parametrize("available", [True, False])
def test_memory_tool(monkeypatch, capsys, available):
    from scripts import measure_memory

    monkeypatch.setattr(sys, "argv", ["measure_memory", "--profile", "lite"])
    container = Mock()
    build = Mock(return_value=container)
    monkeypatch.setattr(measure_memory.Container, "build", build)
    psutil = Mock()
    psutil.Process.return_value.memory_info.return_value.rss = 1024**2
    monkeypatch.setitem(sys.modules, "psutil", psutil if available else None)
    measure_memory.main()
    if available:
        settings = build.call_args.args[0]
        assert settings.qdrant_url == ":memory:"
        assert settings.database_url == "sqlite:///:memory:"
        assert settings.deployment_profile == "lite"
        container.warm_models.assert_called_once()
        container.close.assert_called_once()
        assert "peak_rss_mib=1.0" in capsys.readouterr().out
    else:
        build.assert_not_called()
        assert "Skipped" in capsys.readouterr().out
