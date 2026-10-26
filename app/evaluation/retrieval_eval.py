from pathlib import Path
from time import perf_counter
from typing import Protocol

from app.core.errors import ConfigurationError
from app.evaluation.common import aggregate, breakdown, write_result
from app.evaluation.metrics import hit_at_k, mrr, ndcg_at_k, recall_at_k
from app.retrieval.hybrid import RetrievalConfig, RetrievalResult

CONFIGS = ("dense", "sparse", "hybrid", "hybrid_rerank", "hybrid_rerank_mmr")


class Retriever(Protocol):
    def search(self, query: str, config: RetrievalConfig) -> RetrievalResult: ...


def retrieval_config(name: str, k: int) -> RetrievalConfig:
    if name not in CONFIGS:
        raise ConfigurationError(f"Unknown retrieval configuration: {name}")
    return RetrievalConfig(
        mode=name.split("_")[0],
        rerank="rerank" in name,
        mmr=name.endswith("_mmr"),
        top_k=k,
        candidate_k=max(50, k),
        rerank_top_n=max(30, k),
    )


def run(
    retriever: Retriever,
    questions: list[dict],
    configs: list[str] | None = None,
    ks: tuple[int, ...] = (5, 10, 20),
    output: Path | None = None,
) -> dict:
    if not ks or min(ks) < 1:
        raise ConfigurationError("Retrieval cutoffs must be positive")
    result = {"kind": "retrieval", "ks": list(ks), "configs": {}}
    for name in configs if configs is not None else CONFIGS:
        rows = []
        cfg = retrieval_config(name, max(*ks, 10))
        for question in questions:
            gold = question.get("gold_doc_ids", [])
            if not gold or question.get("expected_behavior") == "abstain":
                continue
            started = perf_counter()
            chunks = retriever.search(question["question"], config=cfg).chunks
            latency = (perf_counter() - started) * 1000
            metrics = {f"Recall@{k}": recall_at_k(chunks, gold, k) for k in ks}
            metrics.update(
                {
                    "MRR@10": mrr(chunks, gold, 10),
                    "nDCG@10": ndcg_at_k(chunks, gold, 10),
                    "Hit@10": hit_at_k(chunks, gold, 10),
                }
            )
            rows.append(
                {
                    **question,
                    "ranked_doc_ids": [c.doc_id for c in chunks],
                    "latency_ms": latency,
                    "metrics": metrics,
                }
            )
        result["configs"][name] = {
            "retrieval_config": cfg.model_dump(),
            "summary": aggregate(rows),
            "rows": rows,
            "by_source": breakdown(rows, "source"),
            "by_category": breakdown(rows, "category"),
        }
    if output:
        write_result(output, result)
    return result
