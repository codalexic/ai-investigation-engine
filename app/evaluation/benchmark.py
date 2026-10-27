import os
import platform
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

from app.core.errors import ConfigurationError
from app.evaluation.common import read_jsonl, write_json
from app.evaluation.connection import EvaluationConnection
from app.evaluation.metrics import percentile
from app.evaluation.retrieval_eval import retrieval_config
from app.retrieval.hybrid import RetrievalConfig

MODES = ("dense", "sparse", "hybrid", "hybrid_rerank")
STAGES = ("dense", "sparse", "fusion", "rerank", "mmr")


def select_questions(root: Path = Path("."), limit: int | None = None) -> list[dict]:
    if limit is not None and limit < 1:
        raise ConfigurationError("Benchmark limit must be positive")
    hotpot = read_jsonl(root / "eval/data/hotpotqa_questions.jsonl")
    selected = random.Random(3).sample(hotpot, min(200, len(hotpot)))
    selected.extend(read_jsonl(root / "eval/questions.jsonl"))
    return selected if limit is None else selected[:limit]


def cache_effect(connection: EvaluationConnection, queries: list[str]) -> dict:
    embedder = connection.retriever.embedder
    # The cache is process-local; clearing it never changes the persisted index.
    cached = getattr(embedder, "_cached_query", None)
    if cached is None:
        return {"count": len(queries), "supported": False}
    embedder.embed_query(queries[0])  # Load the model outside the timed passes.
    cached.cache_clear()
    seconds = []
    hits = []
    for _ in range(2):
        before = cached.cache_info().hits
        started = perf_counter()
        for query in queries:
            embedder.embed_query(query)
        seconds.append(perf_counter() - started)
        hits.append(cached.cache_info().hits - before)
    return {
        "supported": True,
        "count": len(queries),
        "first_seconds": seconds[0],
        "second_seconds": seconds[1],
        "speedup": seconds[0] / seconds[1] if seconds[1] else None,
        "hits": hits,
        "cache_size": cached.cache_info().maxsize,
    }


def performance_tables(result: dict) -> list[str]:
    from app.evaluation.report import _grid, _number

    rows, stages = [], []
    for run in result.get("runs", []):
        prefix = [run["mode"], str(run["concurrency"])]
        rows.append(
            prefix
            + [_number(run["latency_ms"].get(p)) for p in ("p50", "p95", "p99")]
            + [_number(run["queries_per_second"])]
        )
        for stage, timing in run["stages_ms"].items():
            stages.append([*prefix, stage, _number(timing["mean"]), _number(timing["p95"])])
    return [
        _grid(["Mode", "Concurrency", "p50 ms", "p95 ms", "p99 ms", "QPS"], rows)
        if rows
        else "Not run yet",
        "#### Retrieval stages",
        _grid(["Mode", "Concurrency", "Stage", "Mean ms", "p95 ms"], stages)
        if stages
        else "Not run yet",
    ]


def run(
    connection: EvaluationConnection,
    questions: list[dict],
    concurrency: tuple[int, ...] = (1, 4, 8),
    output: Path | None = None,
) -> dict:
    if not questions or not concurrency or any(c < 1 for c in concurrency):
        raise ConfigurationError("Benchmark requires queries and positive concurrency")
    queries = [question["question"] for question in questions]
    result = {
        "kind": "benchmark",
        "machine": {
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "collection": connection.settings.qdrant_collection,
        "point_count": connection.store.count(),
        "models": {
            "embedding": connection.retriever.embedder.name,
            "reranker": connection.settings.reranker_model,
        },
        "seed": 3,
        "question_ids": [q["id"] for q in questions],
        "warmup_queries": 10,
        "cache_effect": cache_effect(connection, queries[:50]),
        "runs": [],
    }
    for mode in MODES:
        cfg = retrieval_config(mode, 10)

        def measure(query: str, config: RetrievalConfig = cfg) -> dict:
            started = perf_counter()
            retrieved = connection.retriever.search(query, config=config)
            return {
                "latency_ms": (perf_counter() - started) * 1000,
                "timings_ms": retrieved.timings_ms,
            }

        for workers in concurrency:
            for i in range(10):
                measure(queries[i % len(queries)])
            with ThreadPoolExecutor(max_workers=workers) as executor:
                started = perf_counter()
                rows = list(executor.map(measure, queries))
                elapsed = perf_counter() - started
            timings = {}
            for stage in STAGES:
                values = [r["timings_ms"][stage] for r in rows if stage in r["timings_ms"]]
                timings[stage] = {
                    "mean": sum(values) / len(values) if values else None,
                    "p95": percentile(values, 95),
                }
            result["runs"].append(
                {
                    "mode": mode,
                    "concurrency": workers,
                    "count": len(rows),
                    "seconds": elapsed,
                    "queries_per_second": len(rows) / elapsed,
                    "latency_ms": {
                        f"p{p}": percentile([r["latency_ms"] for r in rows], p)
                        for p in (50, 95, 99)
                    },
                    "stages_ms": timings,
                    "retrieval_config": cfg.model_dump(),
                    "rows": rows,
                }
            )
    if output:
        write_json(output, result)
        import json

        lines = [
            "# Performance benchmark",
            *performance_tables(result),
            "## Embedding cache",
            "```json\n" + json.dumps(result["cache_effect"], indent=2) + "\n```",
            "## Machine and index",
            "```json\n"
            + json.dumps(
                {k: v for k, v in result.items() if k not in {"runs", "cache_effect"}}, indent=2
            )
            + "\n```",
            "Latency measures each search; QPS uses batch wall time including scheduling. "
            "Ten warm-up searches per mode/concurrency are excluded. The process-local query "
            "cache remains enabled across retrieval runs. Cache speed-up times embeddings only, "
            "with model loading excluded and the cache cleared before the first pass.",
        ]
        output.with_suffix(".md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return result
