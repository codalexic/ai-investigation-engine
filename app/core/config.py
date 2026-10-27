from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", env_file_encoding="utf-8")

    app_env: Literal["local", "prod", "test"] = "local"
    log_level: str = "INFO"
    qdrant_url: str = ":memory:"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "documents"
    database_url: str = "sqlite:///./data/app.db"
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_primary_model: str = "llama-3.3-70b-versatile"
    llm_fallback_model: str = "gemini-2.0-flash"
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
    request_timeout_s: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
