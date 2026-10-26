from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def count_tokens(text: str) -> int:
    """Approximate tokens with ceil(chars / 4); no model tokenizer is loaded."""
    return (len(text) + 3) // 4


def fit_to_budget(items: Iterable[T], budget: int) -> list[T]:
    result = []
    for item in items:
        cost = count_tokens(str(item))
        if cost <= budget:
            result.append(item)
            budget -= cost
    return result
