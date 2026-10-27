from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.retrieval.hybrid import RetrievalConfig
from app.retrieval.store import QueryFilters


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20000)
    filters: QueryFilters | None = None
    retrieval: RetrievalConfig | None = None

    @field_validator("question")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    mode: Literal["dense", "sparse", "hybrid"] | None = None
    rerank: bool | None = None
    mmr: bool | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    filters: QueryFilters | None = None

    @field_validator("query")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query must not be blank")
        return value


class DocumentSummary(BaseModel):
    doc_id: str
    source: str
    format: str
    title: str
    doc_type: str
    created_at: date | None
    content_hash: str
    version: int
    status: str
    duplicate_of: str | None
    entities: dict
    extra: dict
    chunk_count: int
    chunk_strategy: str
    ingested_at: datetime
    updated_at: datetime
    origin: str


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int


class DocumentDetail(DocumentSummary):
    metadata: DocumentSummary
    versions: list[dict[str, Any]]


class SearchChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    payload: dict[str, Any]
    score: float
    explain: dict[str, Any]


class SearchResponse(BaseModel):
    chunks: list[SearchChunk]
    timings_ms: dict[str, float]


class TraceResponse(BaseModel):
    id: str
    created_at: datetime
    question: str
    abstained: bool
    answer_excerpt: str
    citations_count: int
    contradictions_count: int
    usage: dict
    timings: dict[str, float]
    trace: list[dict]
    error: str | None


class StatsResponse(BaseModel):
    documents: dict[str, Any]
    chunks: int
    collection: str
    embedding_model: str
    chunk_strategy: str
    llm_providers: list[str]
    cache: dict[str, int | float]
