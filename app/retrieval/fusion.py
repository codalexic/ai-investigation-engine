import calendar
import re
from datetime import date
from typing import Any, Protocol, TypeVar

import numpy as np

from app.ingest.metadata import extract_entities, parse_date


def weighted_rrf(
    rankings: dict[str, list[str]], weights: dict[str, float], k: int
) -> dict[str, float]:
    """Fuse ranks starting at one: score(d) = sum(w_r / (k + rank_r(d)))."""
    scores: dict[str, float] = {}
    for name, ranking in rankings.items():
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0) + weights.get(name, 1.0) / (k + rank)
    return scores


def entity_boost(
    query_entities: dict[str, list[str]], chunk_entities: dict[str, list[str]], weight: float
) -> float:
    """Return 1 + weight * matched / total query entities."""
    total = matched = 0
    for key, values in query_entities.items():
        wanted = {str(v).lower() for v in values}
        total += len(wanted)
        matched += len(wanted & {str(v).lower() for v in chunk_entities.get(key, [])})
    return 1 + weight * matched / total if total else 1.0


def date_proximity_boost(
    query: str,
    payload: dict[str, Any],
    weight: float = 0.15,
    date_range: tuple[date, date] | None = None,
) -> float:
    """Boost by 1 + weight when a chunk date lies inside the queried dates or month."""
    dates = [date.fromisoformat(d) for d in extract_entities(query)["dates"]]
    months: list[tuple[int | None, int]] = []
    if not dates:
        for month in range(1, 13):
            pattern = (
                rf"\b(?:{calendar.month_name[month]}|{calendar.month_abbr[month]})"
                rf"\b(?:\s+(\d{{4}}))?"
            )
            for match in re.finditer(pattern, query, re.I):
                months.append((int(match[1]) if match[1] else None, month))
        months.extend(
            (int(m[1]), int(m[2])) for m in re.finditer(r"\b(\d{4})-(0[1-9]|1[0-2])\b", query)
        )
    values = [payload.get("created_at"), *payload.get("entities", {}).get("dates", [])]
    for value in values:
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
            value = value[:10]
        parsed = parse_date(value)
        if parsed is None:
            continue
        if date_range and date_range[0] <= parsed <= date_range[1]:
            return 1 + weight
        if dates and min(dates) <= parsed <= max(dates):
            return 1 + weight
        if any(
            parsed.month == month and (year is None or parsed.year == year)
            for year, month in months
        ):
            return 1 + weight
    return 1.0


def mmr(
    candidates: list[tuple[str, float]],
    query_vec: np.ndarray,
    doc_vecs: dict[str, np.ndarray],
    lambda_: float = 0.7,
    top_n: int = 10,
) -> list[str]:
    """Select argmax lambda * normalized relevance - (1-lambda) * max cosine redundancy.

    Candidate scores supply query relevance; query_vec is accepted for callers that also
    retain the dense query representation. Cosine is used only for chunk redundancy.
    """
    if not candidates or top_n <= 0:
        return []
    scores = dict(candidates)
    low, high = min(scores.values()), max(scores.values())
    relevance = {key: (s - low) / (high - low) if high > low else 1.0 for key, s in scores.items()}
    vectors = {
        key: np.asarray(vec) / max(np.linalg.norm(vec), 1e-12) for key, vec in doc_vecs.items()
    }
    selected: list[str] = []
    while scores and len(selected) < top_n:

        def utility(key: str) -> float:
            redundancy = max(
                (float(vectors[key] @ vectors[other]) for other in selected), default=0.0
            )
            return lambda_ * relevance[key] - (1 - lambda_) * redundancy

        best = max(scores, key=utility)
        selected.append(best)
        del scores[best]
    return selected


class PayloadChunk(Protocol):
    @property
    def payload(self) -> dict[str, Any]: ...


ChunkT = TypeVar("ChunkT", bound=PayloadChunk)


def cap_per_document(ranked: list[ChunkT], max_per_doc: int) -> list[ChunkT]:
    """Preserve rank order while keeping at most max_per_doc chunks per document."""
    counts: dict[str, int] = {}
    result: list[ChunkT] = []
    for chunk in ranked:
        key = chunk.payload["doc_id"]
        if counts.get(key, 0) < max_per_doc:
            result.append(chunk)
            counts[key] = counts.get(key, 0) + 1
    return result
