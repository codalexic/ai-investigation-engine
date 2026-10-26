import math
import re
import string
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from app.core.errors import ConfigurationError


def dedupe_documents(ranked: Iterable[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            item
            if isinstance(item, str)
            else item["doc_id"]
            if isinstance(item, dict)
            else item.doc_id
            for item in ranked
        )
    )


def recall_at_k(ranked: Sequence[Any], gold: Iterable[str], k: int) -> float:
    relevant = set(gold)
    return (
        len(set(dedupe_documents(ranked)[: max(0, k)]) & relevant) / len(relevant)
        if relevant
        else 0.0
    )


def precision_at_k(ranked: Sequence[Any], gold: Iterable[str], k: int) -> float:
    return len(set(dedupe_documents(ranked)[: max(0, k)]) & set(gold)) / k if k > 0 else 0.0


def mrr(ranked: Sequence[Any], gold: Iterable[str], k: int = 10) -> float:
    relevant = set(gold)
    return next(
        (
            1 / i
            for i, doc in enumerate(dedupe_documents(ranked)[: max(0, k)], 1)
            if doc in relevant
        ),
        0.0,
    )


def hit_at_k(ranked: Sequence[Any], gold: Iterable[str], k: int) -> float:
    return float(bool(set(dedupe_documents(ranked)[: max(0, k)]) & set(gold)))


def ndcg_at_k(ranked: Sequence[Any], gold: Iterable[str], k: int) -> float:
    relevant = set(gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(max(0, k), len(relevant))))
    score = sum(
        1 / math.log2(i + 2)
        for i, doc in enumerate(dedupe_documents(ranked)[: max(0, k)])
        if doc in relevant
    )
    return score / ideal if ideal else 0.0


def normalize(text: str) -> str:
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", text).split())


def exact_match(answer: str, reference: str) -> float:
    return float(normalize(answer) == normalize(reference))


def token_f1(answer: str, reference: str) -> float:
    a, b = normalize(answer).split(), normalize(reference).split()
    if not a or not b:
        return float(a == b)
    overlap = sum((Counter(a) & Counter(b)).values())
    return 2 * overlap / (len(a) + len(b))


def percentile(values: Sequence[float], p: float) -> float | None:
    if not 0 <= p <= 100:
        raise ConfigurationError("Percentile must be between 0 and 100")
    return float(np.percentile(values, p)) if len(values) else None


def bootstrap_ci(
    values: Sequence[float], n: int = 1000, seed: int = 0, alpha: float = 0.05
) -> tuple[float | None, float | None]:
    if n < 1 or not 0 < alpha < 1:
        raise ConfigurationError("Invalid bootstrap parameters")
    if not len(values):
        return None, None
    rng = np.random.default_rng(seed)
    samples = np.asarray(values, dtype=float)
    means = [float(rng.choice(samples, len(samples), replace=True).mean()) for _ in range(n)]
    return percentile(means, alpha * 50), percentile(means, 100 - alpha * 50)
