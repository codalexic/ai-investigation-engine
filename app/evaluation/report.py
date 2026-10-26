import json
from collections import Counter, defaultdict
from pathlib import Path

from app.evaluation.common import read_jsonl, table


def build(root: Path = Path(".")) -> Path:
    path = root / "eval/questions.jsonl"
    counts = Counter(q["category"] for q in read_jsonl(path)) if path.exists() else Counter()
    lines = [
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
        "End-to-end configurations: full (primary 70B model), no_agent (one retrieval followed by "
        "synthesis and verification), small_model (8B), gemini. All use "
        "hybrid retrieval with reranking. "
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
        '```powershell\n$env:UV_CACHE_DIR=".uv-cache"\n'
        "uv run python scripts/build_eval_set.py\n"
        "uv run python scripts/eval_retrieval.py --collection demo "
        "--questions eval/questions.jsonl\n"
        "uv run python scripts/eval_chunking.py --collections documents,documents_fixed\n"
        "uv run python scripts/eval_embeddings.py --subset-questions 300\n"
        "uv run python scripts/eval_e2e.py --config full --judge auto --pause 2\n"
        "uv run python scripts/make_report.py\n```",
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
    failures = defaultdict(list)
    for kind, title in [
        ("retrieval", "Retrieval"),
        ("chunking", "Chunking"),
        ("embeddings", "Embeddings"),
        ("e2e", "End-to-end"),
    ]:
        lines.append("## " + title)
        matches = [(name, result) for name, result in results if result.get("kind") == kind]
        if not matches:
            lines.append("not run yet")
        for name, result in matches:
            lines.append("### " + name)
            configs = result.get("configs", {result.get("config", name): result})
            for config, value in configs.items():
                lines.extend(["#### " + config, table(value.get("summary", {}))])
                for key in ("statistics", "index_seconds", "paragraphs", "retrieval_config"):
                    if key in value:
                        lines.append(key + ": " + json.dumps(value[key]))
                for field in ("category", "source"):
                    for group, summary in value.get("by_" + field, {}).items():
                        lines.extend(["##### " + field + ": " + group, table(summary)])
                judges = sorted(
                    {
                        (row["judge"]["provider"], row["judge"]["model"])
                        for row in value.get("rows", [])
                        if row.get("judge")
                    }
                )
                if judges:
                    lines.append("Judges used (provider, model): " + json.dumps(judges))
                if value.get("stopped_on_rate_limit"):
                    lines.append("Partial run: quota exhausted; rerun the same command to resume.")
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
                    failures[row.get("category", "unknown")].append((correctness, config, row))
    lines.extend(
        [
            "## Analysis",
            "<!-- analysis -->",
            "## Improvements",
            "<!-- analysis -->",
            "## Failure cases",
        ]
    )
    if not failures:
        lines.append("not run yet")
    for category, cases in sorted(failures.items()):
        lines.append("### " + category)
        for _, config, row in sorted(cases, key=lambda value: (value[0], value[2]["id"]))[:3]:
            lines.extend(
                [
                    f"#### {row['id']} ({config})",
                    "Question: " + row["question"],
                    "Expected: " + row.get("reference_answer", ""),
                    "Got: " + row.get("answer", json.dumps(row.get("ranked_doc_ids", []))),
                    "Metrics: " + json.dumps(row["metrics"]),
                ]
            )
    output = root / "docs/EVALUATION_REPORT.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return output
