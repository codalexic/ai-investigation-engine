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
        "llm_provider_order": ["groq", "gemini"],
        "groq_base_url": "https://api.groq.com/openai/v1",
        "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "openrouter_api_key": None,
        "openrouter_base_url": "https://openrouter.ai/api/v1",
        "openrouter_model": "meta-llama/llama-3.3-70b-instruct:free",
        "llm_temperature": 0.1,
        "llm_max_output_tokens": 1200,
        "llm_max_retries": 4,
        "llm_context_budget_tokens": 6000,
        "llm_cache_enabled": True,
        "agent_max_steps": 5,
        "agent_max_tool_calls": 10,
        "nli_model": "Xenova/nli-deberta-v3-xsmall",
        "nli_enabled": True,
        "support_threshold": 0.5,
        "contradiction_threshold": 0.8,
        "abstain_min_evidence_score": 0.0,
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "chunk_strategy": "structure",
        "chunk_size": 400,
        "chunk_min_tokens": 80,
        "chunk_overlap": 60,
        "retrieval_top_k": 10,
        "embedding_batch_size": 64,
        "candidate_k": 50,
        "rrf_k": 60,
        "dense_weight": 1.0,
        "sparse_weight": 1.0,
        "mmr_lambda": 0.7,
        "max_chunks_per_doc": 3,
        "rerank_enabled": True,
        "rerank_top_n": 30,
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "entity_boost": 0.15,
        "query_cache_size": 1024,
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
