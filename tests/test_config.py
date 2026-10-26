from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.model_dump() == {
        "app_env": "local",
        "log_level": "INFO",
        "qdrant_url": ":memory:",
        "qdrant_api_key": None,
        "qdrant_collection": "documents",
        "database_url": "sqlite:///./data/app.db",
        "groq_api_key": None,
        "gemini_api_key": None,
        "llm_primary_model": "llama-3.3-70b-versatile",
        "llm_fallback_model": "gemini-2.0-flash",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "chunk_strategy": "structure",
        "chunk_size": 400,
        "chunk_min_tokens": 80,
        "chunk_overlap": 60,
        "retrieval_top_k": 10,
        "request_timeout_s": 30.0,
    }


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("CHUNK_SIZE", "500")
    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    settings = Settings(_env_file=None)
    assert settings.app_env == "prod"
    assert settings.chunk_size == 500
    assert settings.groq_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)


def test_dotenv_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("APP_ENV=prod\nCHUNK_STRATEGY=fixed\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    first = get_settings()
    assert first.app_env == "prod"
    assert first.chunk_strategy == "fixed"
    assert get_settings() is first
    get_settings.cache_clear()


@pytest.mark.parametrize("field", ["app_env", "chunk_strategy"])
def test_invalid_choice(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: "invalid"})
