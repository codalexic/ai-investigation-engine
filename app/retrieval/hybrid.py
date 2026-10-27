from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.errors import RetrievalError
from app.ingest.metadata import extract_entities
from app.retrieval.bm25 import Bm25Encoder
from app.retrieval.embeddings import Embedder
from app.retrieval.fusion import (
    cap_per_document,
    date_proximity_boost,
    entity_boost,
    mmr,
    weighted_rrf,
)

if TYPE_CHECKING:
    from app.retrieval.rerank import Reranker
from app.retrieval.store import QdrantStore, QueryFilters


class RetrievalConfig(BaseModel):
    mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    rerank: bool = True
    mmr: bool = True
    top_k: int = Field(default=10, ge=1)
    candidate_k: int = Field(default=50, ge=1)
    weights: dict[str, float] = Field(default_factory=lambda: {"dense": 1.0, "sparse": 1.0})
    rrf_k: int = Field(default=60, ge=0)
    mmr_lambda: float = Field(default=0.7, ge=0, le=1)
    max_chunks_per_doc: int = Field(default=3, ge=1)
    rerank_top_n: int = Field(default=30, ge=1)
    entity_boost: float = Field(default=0.15, ge=0)

    @classmethod
    def from_settings(cls, settings: Settings) -> RetrievalConfig:
        return cls(
            top_k=settings.retrieval_top_k,
            candidate_k=settings.candidate_k,
            rerank=settings.rerank_enabled,
            weights={"dense": settings.dense_weight, "sparse": settings.sparse_weight},
            rrf_k=settings.rrf_k,
            mmr_lambda=settings.mmr_lambda,
            max_chunks_per_doc=settings.max_chunks_per_doc,
            rerank_top_n=settings.rerank_top_n,
            entity_boost=settings.entity_boost,
        )


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    text: str
    payload: dict[str, Any]
    score: float
    explain: dict[str, Any]


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)


class HybridRetriever:
    def __init__(
        self,
        store: QdrantStore,
        embedder: Embedder,
        bm25: Bm25Encoder,
        reranker: Reranker | None,
        settings: Settings,
    ) -> None:
        self.store, self.embedder, self.bm25, self.reranker = store, embedder, bm25, reranker
        self.config = RetrievalConfig.from_settings(settings)
        self.observe: Callable[[str, float], None] | None = None

    def search(
        self,
        query: str,
        config: RetrievalConfig | dict[str, Any] | None = None,
        filters: QueryFilters | None = None,
        date_range: tuple[date, date] | None = None,
    ) -> RetrievalResult:
        if not query.strip():
            raise RetrievalError("Query must not be empty")
        cfg = (
            self.config
            if config is None
            else RetrievalConfig.model_validate(
                {
                    **self.config.model_dump(),
                    **(
                        config
                        if isinstance(config, dict)
                        else config.model_dump(exclude_unset=True)
                    ),
                }
            )
        )
        started = perf_counter()
        timings = {}
        dense, sparse = [], []
        query_vec = None
        if cfg.mode != "sparse":
            query_vec = self.embedder.embed_query(query)
            dense = self.store.dense_search(
                query_vec, cfg.candidate_k, filters, with_vectors=cfg.mmr
            )
        timings["dense"] = (perf_counter() - started) * 1000
        stage = perf_counter()
        if cfg.mode != "dense":
            sparse = self.store.sparse_search(
                self.bm25.encode_query(query), cfg.candidate_k, filters, with_vectors=cfg.mmr
            )
        timings["sparse"] = (perf_counter() - stage) * 1000
        stage = perf_counter()
        rankings = {"dense": [c.chunk_id for c in dense], "sparse": [c.chunk_id for c in sparse]}
        candidates = {c.chunk_id: c for c in [*dense, *sparse]}
        fused = (
            weighted_rrf(rankings, cfg.weights, cfg.rrf_k)
            if cfg.mode == "hybrid"
            else {c.chunk_id: c.score for c in dense + sparse}
        )
        entities = extract_entities(query)
        explanations = {}
        for key, chunk in candidates.items():
            boost = entity_boost(
                entities, chunk.payload.get("entities", {}), cfg.entity_boost
            ) * date_proximity_boost(query, chunk.payload, cfg.entity_boost, date_range)
            explanations[key] = {
                "dense_rank": rankings["dense"].index(key) + 1
                if key in rankings["dense"]
                else None,
                "sparse_rank": rankings["sparse"].index(key) + 1
                if key in rankings["sparse"]
                else None,
                "rrf_score": fused[key] if cfg.mode == "hybrid" else None,
                "boost": boost,
                "rerank_score": None,
                "mmr_selected": False,
            }
            candidates[key] = replace(chunk, score=fused[key] * boost)
        ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
        timings["fusion"] = (perf_counter() - stage) * 1000
        stage = perf_counter()
        if cfg.rerank and ranked and self.reranker is not None:
            head = self.reranker.rerank(query, ranked[: cfg.rerank_top_n], cfg.rerank_top_n)
            for chunk, score in head:
                candidates[chunk.chunk_id] = replace(chunk, score=score)
                explanations[chunk.chunk_id]["rerank_score"] = score
            ranked = [candidates[c.chunk_id] for c, _ in head]
        timings["rerank"] = (perf_counter() - stage) * 1000
        stage = perf_counter()
        if cfg.mmr and ranked:
            if query_vec is None:
                query_vec = self.embedder.embed_query(query)
            vectors = {c.chunk_id: np.asarray(c.vector) for c in ranked if c.vector is not None}
            missing = [c for c in ranked if c.chunk_id not in vectors]
            if missing:
                vectors.update(
                    zip(
                        [c.chunk_id for c in missing],
                        self.embedder.embed_documents([c.payload["text"] for c in missing]),
                        strict=True,
                    )
                )
            keys = mmr(
                [(c.chunk_id, c.score) for c in ranked],
                query_vec,
                vectors,
                cfg.mmr_lambda,
                len(ranked),
            )
            ranked = [candidates[key] for key in keys]
            for key in keys:
                explanations[key]["mmr_selected"] = True
        ranked = cap_per_document(ranked, cfg.max_chunks_per_doc)[: cfg.top_k]
        timings["mmr"] = (perf_counter() - stage) * 1000
        timings["total"] = (perf_counter() - started) * 1000
        if self.observe:
            for stage, duration in timings.items():
                self.observe(stage, duration / 1000)
        return RetrievalResult(
            [
                RetrievedChunk(
                    c.chunk_id,
                    c.payload["doc_id"],
                    c.payload["text"],
                    c.payload,
                    c.score,
                    explanations[c.chunk_id],
                )
                for c in ranked
            ],
            timings,
        )
