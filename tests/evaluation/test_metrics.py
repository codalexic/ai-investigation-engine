import math
from types import SimpleNamespace

import pytest

from app.core.errors import ConfigurationError
from app.evaluation.metrics import (
    bootstrap_ci,
    dedupe_documents,
    exact_match,
    hit_at_k,
    mrr,
    ndcg_at_k,
    normalize,
    percentile,
    precision_at_k,
    recall_at_k,
    token_f1,
)


def test_rank_metrics_dedupe_and_cutoffs():
    ranked = [SimpleNamespace(doc_id="x"), {"doc_id": "x"}, "a", "b"]
    assert dedupe_documents(ranked) == ["x", "a", "b"]
    assert recall_at_k(ranked, ["a", "b"], 2) == 0.5
    assert precision_at_k(ranked, ["a", "b"], 2) == 0.5
    assert mrr(ranked, ["a", "b"], 3) == 0.5
    assert hit_at_k(ranked, ["b"], 2) == 0
    assert hit_at_k(ranked, ["b"], 3) == 1
    assert ndcg_at_k(ranked, ["a", "b"], 3) == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    )
    assert recall_at_k([], [], 5) == 0
    assert precision_at_k(["a"], ["a"], 5) == 0.2
    assert ndcg_at_k([], [], 0) == 0
    assert mrr(["a"], ["a"], 0) == 0
    assert precision_at_k([], [], 0) == 0


def test_answer_metrics():
    assert normalize(" The CAT, a dog! ") == "cat dog"
    assert exact_match("The Paris.", "Paris") == 1
    assert token_f1("red red blue", "red green") == 0.4
    assert token_f1("", "") == 1
    assert token_f1("", "word") == 0
    assert token_f1("Paris", "London") == 0


def test_bootstrap_and_percentiles():
    assert bootstrap_ci([0, 1, 0.5], seed=13) == bootstrap_ci([0, 1, 0.5], seed=13)
    assert bootstrap_ci([1, 1]) == (1, 1)
    assert bootstrap_ci([]) == (None, None)
    assert percentile([0, 10], 95) == 9.5
    assert percentile([], 50) is None
    with pytest.raises(ConfigurationError):
        bootstrap_ci([1], n=0)
    with pytest.raises(ConfigurationError):
        percentile([1], 101)
