from time import perf_counter

import numpy as np
import pytest

from app.core.errors import IngestionError
from app.ingest.dedup import LSHIndex, MinHasher, content_hash, jaccard_estimate, shingles


def test_hash_shingles():
    assert content_hash(" Hello\nWORLD ") == content_hash("hello world")
    assert shingles("one two three", 2) == {"one two", "two three"}
    assert shingles("") == set()


def test_minhash_and_lsh():
    text = " ".join(f"word{i}" for i in range(300))
    edited = text.replace("word150", "changed")
    hasher = MinHasher()
    a, b = hasher.signature(text), hasher.signature(edited)
    assert a.dtype == np.uint64
    assert jaccard_estimate(a, a) == 1
    assert jaccard_estimate(a, b) > 0.8
    assert jaccard_estimate(a, hasher.signature("entirely separate vocabulary")) < 0.1
    assert np.array_equal(a, MinHasher().signature(text))
    index = LSHIndex()
    index.add("a", a)
    assert index.query(b) == {"a"}
    assert index.find_near_duplicates(b, 0.8)[0][0] == "a"
    index.add("a", b)
    index.remove("a")
    assert index.query(a) == set()
    index.remove("missing")


def test_validation():
    for call in (
        lambda: MinHasher(0),
        lambda: LSHIndex(7, 2),
        lambda: shingles("x", 0),
        lambda: jaccard_estimate(np.zeros(2), np.zeros(3)),
        lambda: LSHIndex().query(np.zeros(3)),
    ):
        with pytest.raises(IngestionError):
            call()


def test_batch_signatures_and_empty():
    hasher = MinHasher()
    texts = ["", "one two three", "different words"]
    result = hasher.signatures(iter(texts))
    assert result.shape == (3, 128)
    assert result.dtype == np.uint64
    assert np.all(result[0] == 0xFFFFFFFF)
    for text, signature in zip(texts, result, strict=True):
        np.testing.assert_array_equal(signature, hasher.signature(text))
    assert hasher.signatures([]).shape == (0, 128)


def test_signature_throughput():
    texts = [" ".join(f"word{document}_{word}" for word in range(150)) for document in range(1000)]
    hasher = MinHasher()
    started = perf_counter()
    signatures = hasher.signatures(texts)
    duration = perf_counter() - started
    assert signatures.shape == (1000, 128)
    assert duration < 2, f"Signatures took {duration:.3f}s"
