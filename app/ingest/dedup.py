import hashlib
import random
import re
from collections.abc import Iterable

import numpy as np

from app.core.errors import IngestionError
from app.ingest.parsers import normalize_text


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(normalize_text(text).lower().split()).encode()).hexdigest()


def shingles(text: str, k: int = 5) -> set[str]:
    if k < 1:
        raise IngestionError("Shingle size must be positive")
    words = re.findall(r"\w+", normalize_text(text).lower())
    return (
        {" ".join(words[i : i + k]) for i in range(max(1, len(words) - k + 1))} if words else set()
    )


class MinHasher:
    """Estimate Jaccard similarity with vectorized universal hashes modulo 2^61-1.

    Parameters a and b are drawn from [1, 2^32), and shingle hashes are 32-bit.
    Since a < 2^32, a*x < 2^64; even a*x + b fits uint64 without overflow.
    """

    def __init__(self, num_perm: int = 128, seed: int = 42) -> None:
        if num_perm < 1:
            raise IngestionError("num_perm must be positive")
        self.num_perm = num_perm
        self.prime = (1 << 61) - 1
        rng = random.Random(seed)
        parameters = np.array(
            [(rng.randrange(1, 1 << 32), rng.randrange(1, 1 << 32)) for _ in range(num_perm)],
            dtype=np.uint64,
        )
        self.a, self.b = parameters[:, :1], parameters[:, 1:]

    def signature(self, text: str) -> np.ndarray:
        values = np.array(
            [
                int.from_bytes(hashlib.blake2b(s.encode(), digest_size=4).digest(), "big")
                for s in shingles(text)
            ],
            dtype=np.uint64,
        )
        if not values.size:
            return np.full(self.num_perm, 0xFFFFFFFF, dtype=np.uint64)
        hashes = ((self.a * values + self.b) % self.prime) & 0xFFFFFFFF
        return hashes.min(axis=1)

    def signatures(self, texts: Iterable[str]) -> np.ndarray:
        signatures = [self.signature(text) for text in texts]
        return np.stack(signatures) if signatures else np.empty((0, self.num_perm), dtype=np.uint64)

    @staticmethod
    def jaccard_estimate(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
        return jaccard_estimate(sig_a, sig_b)


def jaccard_estimate(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
    if sig_a.shape != sig_b.shape or not sig_a.size:
        raise IngestionError("Signatures must have equal nonzero lengths")
    return float(np.mean(sig_a == sig_b))


class LSHIndex:
    """Banding with b bands and r rows gives a threshold approximately (1/b)^(1/r)."""

    def __init__(self, num_perm: int = 128, bands: int = 32) -> None:
        if bands < 1 or num_perm < 1 or num_perm % bands:
            raise IngestionError("Bands must divide num_perm")
        self.num_perm, self.bands = num_perm, bands
        self.signatures: dict[str, np.ndarray] = {}
        self.buckets: dict[tuple[int, bytes], set[str]] = {}

    def _keys(self, sig: np.ndarray) -> list[tuple[int, bytes]]:
        if sig.shape != (self.num_perm,):
            raise IngestionError("Invalid signature length")
        return [
            (i, hashlib.blake2b(band.astype("<u8").tobytes(), digest_size=16).digest())
            for i, band in enumerate(np.split(sig, self.bands))
        ]

    def add(self, key: str, sig: np.ndarray) -> None:
        keys = self._keys(sig)
        self.remove(key)
        self.signatures[key] = sig.copy()
        for bucket in keys:
            self.buckets.setdefault(bucket, set()).add(key)

    def remove(self, key: str) -> None:
        sig = self.signatures.pop(key, None)
        if sig is not None:
            for bucket in self._keys(sig):
                self.buckets[bucket].discard(key)
                if not self.buckets[bucket]:
                    del self.buckets[bucket]

    def query(self, sig: np.ndarray) -> set[str]:
        return set().union(*(self.buckets.get(bucket, set()) for bucket in self._keys(sig)))

    def find_near_duplicates(
        self, sig: np.ndarray, threshold: float = 0.85
    ) -> list[tuple[str, float]]:
        return sorted(
            (
                (key, score)
                for key in self.query(sig)
                if (score := jaccard_estimate(sig, self.signatures[key])) >= threshold
            ),
            key=lambda item: (-item[1], item[0]),
        )
