from functools import lru_cache
from hashlib import blake2b
from itertools import pairwise
from typing import Any, Protocol

import numpy as np

from app.core.config import get_settings
from app.core.errors import RetrievalError
from app.retrieval.text import analyze


class Embedder(Protocol):
    name: str

    @property
    def dim(self) -> int: ...
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def normalize(rows: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return rows / np.maximum(norms, 1e-12)


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 64) -> None:
        if dim < 1:
            raise RetrievalError("Embedding dimension must be positive")
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in zip(rows, texts, strict=True):
            words = analyze(text)
            for term in words + [" ".join(pair) for pair in pairwise(words)]:
                digest = blake2b(term.encode(), digest_size=8).digest()
                row[int.from_bytes(digest[:4], "little") % self.dim] += 1 if digest[4] & 1 else -1
        return normalize(rows)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


class FastEmbedEmbedder:
    def __init__(
        self,
        model_name: str,
        batch_size: int = 64,
        cache_dir: str | None = None,
        query_cache_size: int | None = None,
    ) -> None:
        self.name, self.batch_size, self.cache_dir = model_name, batch_size, cache_dir
        self._model = None
        self._cached_query = lru_cache(
            maxsize=get_settings().query_cache_size
            if query_cache_size is None
            else query_cache_size
        )(self._query)

    @property
    def model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.name, cache_dir=self.cache_dir)
        return self._model

    @property
    def dim(self) -> int:
        return self.model.embedding_size

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        try:
            return normalize(np.array(list(self.model.embed(texts, batch_size=self.batch_size))))
        except Exception as exc:
            raise RetrievalError("Passage embedding failed") from exc

    def _query(self, text: str) -> np.ndarray:
        try:
            return normalize(np.array(list(self.model.query_embed(text))))[0]
        except Exception as exc:
            raise RetrievalError("Query embedding failed") from exc

    def embed_query(self, text: str) -> np.ndarray:
        return self._cached_query(text).copy()
