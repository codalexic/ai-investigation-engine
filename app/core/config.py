from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", env_file_encoding="utf-8")

    app_env: Literal["local", "prod", "test"] = "local"
    model_cache_dir: str | None = None
    warmup: bool | None = None
    hf_token: SecretStr | None = None
    log_level: str = "INFO"
    qdrant_url: str = ":memory:"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "documents"
    database_url: str = "sqlite:///./data/app.db"
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_primary_model: str = "llama-3.3-70b-versatile"
    llm_fallback_model: str = "gemini-2.0-flash"
    llm_provider_order: list[str] = ["groq", "gemini"]
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = Field(default=1200, ge=1)
    llm_max_retries: int = Field(default=4, ge=0)
    llm_context_budget_tokens: int = Field(default=6000, ge=1)
    llm_cache_enabled: bool = True
    agent_max_steps: int = Field(default=5, ge=0)
    agent_max_tool_calls: int = Field(default=10, ge=0)
    nli_model: str = "Xenova/nli-deberta-v3-xsmall"
    nli_enabled: bool = True
    support_threshold: float = Field(default=0.5, ge=0, le=1)
    contradiction_threshold: float = Field(default=0.8, ge=0, le=1)
    abstain_min_evidence_score: float = 0.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    chunk_strategy: Literal["structure", "fixed"] = "structure"
    chunk_size: int = 400
    chunk_min_tokens: int = 80
    chunk_overlap: int = 60
    retrieval_top_k: int = 10
    embedding_batch_size: int = 64
    candidate_k: int = 50
    rrf_k: int = 60
    dense_weight: float = 1.0
    sparse_weight: float = 1.0
    mmr_lambda: float = 0.7
    max_chunks_per_doc: int = 3
    rerank_enabled: bool = True
    rerank_top_n: int = 30
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    entity_boost: float = 0.15
    query_cache_size: int = 1024
    max_upload_mb: int = Field(default=20, ge=1)
    admin_token: SecretStr | None = None
    answer_cache_ttl_s: int = Field(default=86400, ge=0)
    rate_limit_per_minute: int = Field(default=10, ge=1)
    request_timeout_s: float = 30.0

    @field_validator("model_cache_dir", "warmup", mode="before")
    @classmethod
    def empty_optional(cls, value: str | bool | None) -> str | bool | None:
        return None if value == "" else value

    @field_validator("admin_token", mode="before")
    @classmethod
    def empty_admin_token(cls, value: str | SecretStr | None) -> str | SecretStr | None:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
