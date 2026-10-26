from typing import Any, Protocol

from app.core.errors import RetrievalError
from app.retrieval.store import ScoredChunk
from app.retrieval.text import analyze


class Reranker(Protocol):
    def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[tuple[ScoredChunk, float]]: ...


class NoopReranker:
    def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[tuple[ScoredChunk, float]]:
        return [(c, c.score) for c in chunks[:top_n]]


class FakeReranker:
    def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[tuple[ScoredChunk, float]]:
        terms = set(analyze(query))
        scored = [(c, float(len(terms & set(analyze(c.payload["text"]))))) for c in chunks]
        return sorted(scored, key=lambda pair: pair[1], reverse=True)[:top_n]


class CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self.name = model_name
        self._model = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            model_name = (
                "Xenova/ms-marco-MiniLM-L-6-v2"
                if self.name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
                else self.name
            )
            self._model = TextCrossEncoder(model_name=model_name)
        return self._model

    def rerank(
        self, query: str, chunks: list[ScoredChunk], top_n: int
    ) -> list[tuple[ScoredChunk, float]]:
        if not chunks:
            return []
        try:
            scores = self.model.rerank(query, [c.payload["text"] for c in chunks])
            return sorted(
                zip(chunks, map(float, scores), strict=True), key=lambda pair: pair[1], reverse=True
            )[:top_n]
        except Exception as exc:
            raise RetrievalError("Cross encoder reranking failed") from exc
