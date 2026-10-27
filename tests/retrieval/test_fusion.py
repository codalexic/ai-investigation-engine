import numpy as np
import pytest

from app.retrieval.fusion import (
    cap_per_document,
    date_proximity_boost,
    entity_boost,
    mmr,
    weighted_rrf,
)
from app.retrieval.store import ScoredChunk


def test_rrf():
    result = weighted_rrf(
        {"dense": ["a", "b"], "sparse": ["b", "c"]}, {"dense": 2, "sparse": 1}, 60
    )
    assert result == pytest.approx({"a": 2 / 61, "b": 2 / 62 + 1 / 61, "c": 1 / 62})
    assert weighted_rrf({}, {}, 60) == {}


def test_boosts():
    assert entity_boost({"services": ["x", "y"]}, {"services": ["X"]}, 0.2) == 1.1
    assert entity_boost({}, {}, 0.2) == 1
    payload = {"created_at": "2025-03-12T00:00:00Z"}
    assert date_proximity_boost("March 2025", payload) == 1.15
    assert date_proximity_boost("March 2026", payload) == 1
    assert date_proximity_boost("2025-03-01 to 2025-03-31", payload) == 1.15
    assert date_proximity_boost("2024-03-01", {"entities": {"dates": ["2024-03-01"]}}) == 1.15
    assert date_proximity_boost("undated query", payload) == 1


def test_mmr_and_cap():
    vectors = {"a": np.array([1.0, 0]), "b": np.array([1.0, 0]), "c": np.array([0.0, 1])}
    selected = mmr([("a", 1), ("b", 0.99), ("c", 0.8)], np.array([1.0, 0]), vectors, 0.2, 2)
    assert selected == ["a", "c"]
    ranked = [ScoredChunk(str(i), 1, {"doc_id": "one" if i < 4 else "two"}) for i in range(5)]
    assert [c.chunk_id for c in cap_per_document(ranked, 2)] == ["0", "1", "4"]
    assert mmr([], np.array([1]), {}, top_n=3) == []
