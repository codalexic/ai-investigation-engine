import json
from collections import Counter, defaultdict
from pathlib import Path

from app.evaluation.common import read_jsonl, table


def _truncate(answer: str) -> str:
    return answer if len(answer) <= 400 else answer[:397] + "..."


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _metric(summary: dict, name: str, ci: bool = False) -> str:
    value = summary.get("metrics", {}).get(name, {})
    result = _number(value.get("mean"))
    bounds = value.get("ci95")
    if ci and bounds and all(bound is not None for bound in bounds):
        result += f" [{bounds[0]:.3f}\u2013{bounds[1]:.3f}]"
    return result


def _grid(headers: list[str], rows: list[list[str]]) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"

    return "\n".join([line(headers), line(["---"] * len(headers)), *map(line, rows)])


def _summary(results: list[tuple[str, dict]], counts: Counter) -> list[str]:
    groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for name, result in results:
        for config, value in result.get("configs", {result.get("config", name): result}).items():
            groups[result.get("kind", "")].append((config, value))
    lines = []
    retrieval = groups["retrieval"]
    hotpot = [(name, value.get("by_source", {}).get("hotpotqa", {})) for name, value in retrieval]
    sizes = sorted({value["count"] for _, value in hotpot if "count" in value})
    size = "/".join(map(str, sizes)) if sizes else "0"
    lines.append(f"### Retrieval \u2014 HotpotQA (n={size})")
    rows = []
    for name, summary in hotpot:
        rows.append(
            [
                name,
                *[
                    _metric(summary, key, key in {"Recall@10", "MRR@10"})
                    for key in ("Recall@5", "Recall@10", "Recall@20", "MRR@10", "nDCG@10")
                ],
                *[_number(summary.get("latency_ms", {}).get(p)) for p in ("p50", "p95")],
            ]
        )
    lines.append(
        _grid(
            [
                "Config",
                "Recall@5",
                "Recall@10",
                "Recall@20",
                "MRR@10",
                "nDCG@10",
                "Latency p50 ms",
                "Latency p95 ms",
            ],
            rows,
        )
        if rows
        else "Not run yet"
    )
    categories = sorted(set(counts) - {"bridge", "comparison"})
    lines.append("### Retrieval \u2014 investigation set by category")
    for metric in ("Recall@10", "MRR@10"):
        lines.append("#### " + metric)
        lines.append(
            _grid(
                ["Category", *[name for name, _ in retrieval]],
                [
                    [
                        category,
                        *[
                            _metric(value.get("by_category", {}).get(category, {}), metric)
                            for _, value in retrieval
                        ],
                    ]
                    for category in categories
                ],
            )
            if retrieval
            else "Not run yet"
        )
    lines.append("### Chunking")
    chunking = groups["chunking"]
    rows = []
    for key in (
        "evidence-hit@10",
        "Recall@10",
        "MRR@10",
        "context_tokens_to_first_hit",
        "mean_chunk_tokens",
        "chunks_per_document",
        "chunk_count",
    ):
        rows.append(
            [
                key,
                *[
                    _number(value.get("statistics", {}).get(key))
                    if key in {"mean_chunk_tokens", "chunks_per_document", "chunk_count"}
                    else _metric(value.get("summary", {}), key)
                    for _, value in chunking
                ],
            ]
        )
    lines.append(
        _grid(["Metric", *[name for name, _ in chunking]], rows) if chunking else "Not run yet"
    )
    lines.append("### Embeddings")
    rows = []
    for name, value in groups["embeddings"]:
        summary = value.get("summary", {})
        rows.append(
            [
                name,
                _metric(summary, "Recall@10", True),
                _metric(summary, "MRR@10", True),
                _number(value.get("index_seconds")),
                _number(summary.get("latency_ms", {}).get("p50")),
            ]
        )
    lines.append(
        _grid(["Model / mode", "Recall@10", "MRR@10", "Index seconds", "Query p50 ms"], rows)
        if rows
        else "Not run yet"
    )
    lines.append("### End-to-end")
    e2e = groups["e2e"]
    keys = (
        "judge_correctness",
        "token_f1",
        "citation_precision",
        "citation_recall",
        "faithfulness",
        "abstention_accuracy",
        "false_abstain_rate",
        "false_answer_rate",
        "contradiction_detection_rate",
        "injection_resistance",
    )
    rows = []
    for name, value in e2e:
        summary = value.get("summary", {})
        latency = summary.get("latency_ms", {}).get("p50")
        cells = [
            _metric(value.get("by_source", {}).get("hotpotqa", {}), key)
            if key == "token_f1"
            else _metric(summary, key)
            for key in keys
        ]
        rows.append(
            [
                name,
                *cells,
                _number(latency / 1000 if latency is not None else None),
                _metric(summary, "tokens"),
                _metric(summary, "estimated_cost"),
            ]
        )
    lines.append(
        _grid(
            [
                "Config",
                "Judge correctness",
                "Token F1 (HotpotQA)",
                "Citation precision",
                "Citation recall",
                "Faithfulness",
                "Abstention accuracy",
                "False-abstention rate",
                "False-answer rate",
                "Contradiction detection",
                "Injection resistance",
                "Latency p50 s",
                "Tokens/question",
                "Est. cost/question",
            ],
            rows,
        )
        if rows
        else "Not run yet"
    )
    lines.append("#### Judge correctness by category")
    e2e_categories = sorted(
        {category for _, value in e2e for category in value.get("by_category", {})}
    )
    lines.append(
        _grid(
            ["Category", *[name for name, _ in e2e]],
            [
                [
                    category,
                    *[
                        _metric(value.get("by_category", {}).get(category, {}), "judge_correctness")
                        for _, value in e2e
                    ],
                ]
                for category in e2e_categories
            ],
        )
        if e2e
        else "Not run yet"
    )
    lines.append("### Performance")
    from app.evaluation.benchmark import performance_tables

    benchmarks = [result for _, result in results if result.get("kind") == "benchmark"]
    if not benchmarks:
        lines.append("Not run yet")
    for benchmark in benchmarks:
        lines.extend(performance_tables(benchmark))
    lines.append("#### Indexing throughput")
    indexing = next((value for name, value in results if name == "indexing_documents"), None)
    if indexing:
        records = indexing.get("records", sum(indexing.get("counts_per_source", {}).values()))
        seconds = indexing.get("seconds")
        rate = indexing.get("records_per_sec")
        if rate is None and seconds:
            rate = records / seconds
        lines.append(
            _grid(
                ["Records", "Chunks", "Seconds", "Records/s"],
                [
                    [
                        str(records),
                        str(indexing.get("chunks", "n/a")),
                        _number(seconds),
                        _number(rate),
                    ]
                ],
            )
        )
    else:
        lines.append("Not run yet")
    return lines


def build(root: Path = Path(".")) -> Path:
    path = root / "eval/questions.jsonl"
    counts = Counter(q["category"] for q in read_jsonl(path)) if path.exists() else Counter()
    e2e_path = root / "eval/questions_e2e.jsonl"
    e2e_counts = (
        Counter(q["category"] for q in read_jsonl(e2e_path)) if e2e_path.exists() else Counter()
    )
    methodology = [
        "# Evaluation report",
        "## Methodology",
        "The evaluation set is assembled deterministically with seed 13 from synthetic facts, "
        "HotpotQA bridge/comparison questions, and postmortem summaries. Gold documents are "
        "validated against corpus identifiers. Category counts: "
        + json.dumps(dict(sorted(counts.items()))),
        "Retrieval ranks are deduplicated by document before scoring. "
        "Recall@k measures the fraction "
        "of gold documents retrieved; precision@k divides relevant hits by "
        "k; MRR is the reciprocal "
        "rank of the first relevant document; binary nDCG discounts hits by log2(rank+1); Hit@k "
        "indicates any gold hit. Confidence intervals use 1,000 bootstrap "
        "samples, seed 0, 95% coverage. "
        "Latency percentiles use linear interpolation.",
        "Retrieval configurations: dense, sparse, hybrid, hybrid_rerank, hybrid_rerank_mmr. "
        "Chunking compares identical document sets using evidence substring hits, document recall, "
        "MRR, chunk tokens and context tokens to the first hit (misses are "
        "excluded from that mean). "
        "Embedding experiments use only the original contexts of the first N sampled questions.",
        "End-to-end runs use eval/questions_e2e.jsonl, a fixed "
        + str(sum(e2e_counts.values()))
        + "-question subset covering every category: "
        + json.dumps(dict(sorted(e2e_counts.items())))
        + ". Configurations: no_agent (one retrieval followed by synthesis and verification, "
        "gpt-oss-120b), no_agent_gemini (the same pipeline on gemini-3.5-flash-lite) and gemini "
        "(planner, tool loop, synthesis and verification on gemini-3.5-flash-lite). The two "
        "Gemini configurations share the generator, so their difference isolates the agent. "
        "All use hybrid retrieval with reranking. "
        "The automatic judge prefers a different provider from the generator, uses a strict "
        "0/0.5/1 correctness rubric, and checks injection assertions including paraphrases. "
        "Actual judge provider/model and usage are recorded per question; unavailable or disabled "
        "judges produce missing scores rather than substitute estimates.",
        "Answer metrics include SQuAD normalized EM/token F1 for HotpotQA, "
        "document citation precision "
        "and recall, supported-claim share from the NLI verifier, "
        "abstention accuracy, false abstention "
        "and false answer rates conditional on expected behavior, "
        "gold-citing contradiction detection, "
        "and judge-checked injection resistance. Cost estimates use the "
        "configured model price table; "
        "cached calls incur no new estimated cost. Judge cost is reported separately.",
        "### Reproducibility",
        "```bash\nmake data\nmake index\nmake index-chunking\nmake eval-retrieval\n"
        "make eval-chunking\nmake eval-embeddings\nmake eval-e2e\nmake benchmark\nmake report\n```",
        "Existing collection evaluations open registry databases read-only; "
        "embeddings use isolated "
        "emb_* collections and separate registry databases. End-to-end "
        "question and LLM caches live "
        "under eval/cache. Re-run the same command after quota recovery to resume; remove stale "
        "question caches when the dataset or configuration changes. "
        "Question-cache reuse is validated against the run context.",
    ]
    results = []
    for path in sorted((root / "eval/results").glob("*.json")):
        results.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    lines = [
        "# Detailed evaluation results",
        "Generated from eval/results/ by `make report`. The written report with methodology and "
        "discussion is docs/EVALUATION_REPORT.md.",
        "## Summary",
        *_summary(results, counts),
        "## Analysis",
        (root / "eval/analysis.md").read_text(encoding="utf-8")
        if (root / "eval/analysis.md").exists()
        else "Analysis pending.",
        *methodology[1:],
    ]
    details = ["## Appendix: detailed results"]
    failures = defaultdict(list)
    for kind, title in [
        ("retrieval", "Retrieval"),
        ("chunking", "Chunking"),
        ("embeddings", "Embeddings"),
        ("e2e", "End-to-end"),
    ]:
        details.append("### " + title)
        matches = [(name, result) for name, result in results if result.get("kind") == kind]
        if not matches:
            details.append("not run yet")
        for name, result in matches:
            details.append("#### " + name)
            configs = result.get("configs", {result.get("config", name): result})
            for config, value in configs.items():
                details.extend(["##### " + config, table(value.get("summary", {}))])
                for key in ("statistics", "index_seconds", "paragraphs", "retrieval_config"):
                    if key in value:
                        details.append(key + ": " + json.dumps(value[key]))
                for field in ("category", "source"):
                    for group, summary in value.get("by_" + field, {}).items():
                        details.extend(["###### " + field + ": " + group, table(summary)])
                judges = sorted(
                    {
                        (row["judge"]["provider"], row["judge"]["model"])
                        for row in value.get("rows", [])
                        if row.get("judge")
                    }
                )
                if judges:
                    details.append("Judges used (provider, model): " + json.dumps(judges))
                if value.get("stopped_on_rate_limit"):
                    details.append(
                        "Partial run: quota exhausted; rerun the same command to resume."
                    )
                for row in value.get("rows", []):
                    metrics = row["metrics"]
                    candidates = [
                        "judge_correctness",
                        "token_f1",
                        "injection_resistance",
                        "contradiction_detection_rate",
                        "abstention_accuracy",
                    ]
                    candidates.extend(key for key in metrics if key.startswith("Recall@"))
                    candidates.extend(key for key in metrics if key.startswith("MRR@"))
                    correctness = next(
                        (metrics[key] for key in candidates if metrics.get(key) is not None), 1
                    )
                    failures[(row.get("category", "unknown"), kind)].append(
                        (correctness, config, row)
                    )
    lines.append("## Failure cases")
    if not failures:
        lines.append("not run yet")
    for (category, kind), cases in sorted(failures.items()):
        lines.append(f"### {category} ({kind})")
        for _, config, row in sorted(cases, key=lambda value: (value[0], value[2]["id"]))[:2]:
            lines.extend(
                [
                    f"#### {row['id']} ({config})",
                    "Question: " + row["question"],
                    "Expected: " + row.get("reference_answer", ""),
                    "Got: "
                    + _truncate(row.get("answer", json.dumps(row.get("ranked_doc_ids", [])))),
                    "Metrics: " + json.dumps(row["metrics"]),
                ]
            )
    lines.extend(details)
    output = root / "eval/results/REPORT.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return output
