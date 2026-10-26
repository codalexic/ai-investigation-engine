from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from hashlib import blake2b
from math import log
from threading import RLock
from typing import Any, ParamSpec, TypeVar

from qdrant_client.models import SparseVector
from sqlalchemy import Column, Integer, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import RetrievalError
from app.retrieval.text import analyze

P = ParamSpec("P")
T = TypeVar("T")


def locked(method: Callable[P, T]) -> Callable[P, T]:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> T:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


@dataclass
class Bm25Statistics:
    _lock: object = field(default_factory=RLock, repr=False, init=False, compare=False)
    N: int = 0
    total_length: int = 0
    df: Counter[str] = field(default_factory=Counter)
    dirty: set[str] = field(default_factory=set, repr=False)

    @property
    @locked
    def avgdl(self) -> float:
        return self.total_length / self.N if self.N else 0.0

    @locked
    def add_document(self, tokens: list[str]) -> None:
        self.N += 1
        self.total_length += len(tokens)
        self.df.update(set(tokens))
        self.dirty.update(tokens)

    @locked
    def remove_document(self, tokens: list[str]) -> None:
        if self.N < 1 or any(self.df[t] < 1 for t in set(tokens)):
            raise RetrievalError("Cannot remove an unindexed document")
        self.N -= 1
        self.total_length -= len(tokens)
        for term in set(tokens):
            self.df[term] -= 1
            if self.df[term] == 0:
                del self.df[term]
        self.dirty.update(tokens)

    @locked
    def idf(self, term: str) -> float:
        return log(1 + (self.N - self.df[term] + 0.5) / (self.df[term] + 0.5))


class Bm25StatsRepository:
    def __init__(self, engine: Engine, *, read_only: bool = False) -> None:
        self.engine = engine
        self._save_lock = RLock()
        metadata = MetaData()
        self.terms = Table(
            "bm25_terms", metadata, Column("term", String, primary_key=True), Column("df", Integer)
        )
        self.meta = Table(
            "bm25_meta", metadata, Column("key", String, primary_key=True), Column("value", Integer)
        )
        try:
            if not read_only:
                metadata.create_all(engine)
        except SQLAlchemyError as exc:
            raise RetrievalError("Cannot initialize BM25 statistics") from exc

    def load(self) -> Bm25Statistics:
        try:
            with self.engine.connect() as conn:
                meta = dict(conn.execute(select(self.meta)).all())
                return Bm25Statistics(
                    meta.get("N", 0),
                    meta.get("total_length", 0),
                    Counter(dict(conn.execute(select(self.terms)).all())),
                )
        except SQLAlchemyError as exc:
            raise RetrievalError("Cannot load BM25 statistics") from exc

    def save(self, stats: Bm25Statistics) -> None:
        with self._save_lock:
            with stats._lock:
                dirty, stats.dirty = stats.dirty, set()
                rows = [{"term": t, "df": stats.df[t]} for t in dirty if stats.df[t]]
                count, length = stats.N, stats.total_length
            try:
                with self.engine.begin() as conn:
                    if dirty:
                        conn.execute(delete(self.terms).where(self.terms.c.term.in_(dirty)))
                        if rows:
                            conn.execute(insert(self.terms), rows)
                    conn.execute(delete(self.meta))
                    conn.execute(
                        insert(self.meta),
                        [
                            {"key": "N", "value": count},
                            {"key": "total_length", "value": length},
                        ],
                    )
            except SQLAlchemyError as exc:
                with stats._lock:
                    stats.dirty.update(dirty)
                raise RetrievalError("Cannot save BM25 statistics") from exc


def term_id(term: str) -> int:
    """Stable uint32 hash; rare collisions intentionally share a sparse dimension."""
    return int.from_bytes(blake2b(term.encode(), digest_size=4).digest(), "little")


def _sparse(weights: dict[str, float]) -> SparseVector:
    merged: Counter[int] = Counter()
    for term, weight in weights.items():
        merged[term_id(term)] += weight
    indices = sorted(merged)
    return SparseVector(indices=indices, values=[merged[i] for i in indices])


class Bm25Encoder:
    """Document weights use avgdl at index time, an accepted incremental approximation."""

    def __init__(self, stats: Bm25Statistics, k1: float = 1.2, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise RetrievalError("Invalid BM25 parameters")
        self.stats, self.k1, self.b = stats, k1, b

    def encode_document(self, text: str, update_stats: bool = False) -> SparseVector:
        tokens = analyze(text)
        if update_stats:
            self.stats.add_document(tokens)
        counts = Counter(tokens)
        norm = self.k1 * (1 - self.b + self.b * len(tokens) / (self.stats.avgdl or 1))
        return _sparse({t: tf * (self.k1 + 1) / (tf + norm) for t, tf in counts.items()})

    def encode_query(self, text: str) -> SparseVector:
        with self.stats._lock:
            return _sparse({t: self.stats.idf(t) for t in set(analyze(text)) if self.stats.df[t]})


def bm25_scores(query: str, docs: list[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    tokens = [analyze(doc) for doc in docs]
    n = len(docs)
    avg = sum(map(len, tokens)) / n if n else 1
    df = Counter(t for doc in tokens for t in set(doc))
    return [
        sum(
            log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            * counts[t]
            * (k1 + 1)
            / (counts[t] + k1 * (1 - b + b * len(doc) / (avg or 1)))
            for t in set(analyze(query))
            if counts[t]
        )
        for doc in tokens
        for counts in [Counter(doc)]
    ]
