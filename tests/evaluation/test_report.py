import json
from pathlib import Path

from app.evaluation.report import build


def save_result(root: Path, name: str, result: dict) -> None:
    path = root / "eval/results" / (name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")


def summary(value: float = 0.874) -> dict:
    return {
        "count": 7,
        "metrics": {
            key: {"mean": value, "ci95": [0.85, 0.89], "n": 7}
            for key in (
                "Recall@5",
                "Recall@10",
                "Recall@20",
                "MRR@10",
                "nDCG@10",
                "evidence-hit@10",
                "context_tokens_to_first_hit",
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
                "tokens",
                "estimated_cost",
            )
        },
        "latency_ms": {"p50": 1234, "p95": 2345},
    }


def test_summary_tables_and_section_order(tmp_path):
    questions = tmp_path / "eval/questions.jsonl"
    questions.parent.mkdir()
    questions.write_text(
        "\n".join(
            json.dumps({"category": c})
            for c in ["bridge", "comparison", "injection", "unanswerable"]
        )
    )
    value = {
        "summary": summary(0.1),
        "by_source": {"hotpotqa": summary()},
        "by_category": {"injection": summary(0.5)},
    }
    save_result(tmp_path, "retrieval", {"kind": "retrieval", "configs": {"dense": value}})
    save_result(
        tmp_path,
        "chunking",
        {
            "kind": "chunking",
            "configs": {
                "structure": {
                    "summary": summary(),
                    "statistics": {
                        "mean_chunk_tokens": 99,
                        "chunks_per_document": 2,
                        "chunk_count": 100,
                    },
                }
            },
        },
    )
    save_result(
        tmp_path,
        "embeddings",
        {
            "kind": "embeddings",
            "configs": {"model/dense": {"summary": summary(), "index_seconds": 42}},
        },
    )
    save_result(tmp_path, "e2e", {"kind": "e2e", "config": "full", **value})
    report = build(tmp_path).read_text(encoding="utf-8")
    top = report.split("## Analysis")[0]
    assert "HotpotQA (n=7)" in top
    assert "0.874 [0.850\u20130.890]" in top
    assert "| injection | 0.500 |" in top
    assert "| unanswerable | n/a |" in top
    assert "| bridge |" not in top and "| comparison |" not in top
    assert "| chunk_count | 100.000 |" in top
    assert "| model/dense | 0.874 [0.850\u20130.890] |" in top
    assert "| full | 0.100 | 0.874 |" in top
    assert "1.234 | 0.100 | 0.100 |" in top
    headings = [
        "## Summary",
        "## Analysis",
        "## Methodology",
        "## Failure cases",
        "## Appendix: detailed results",
    ]
    assert [report.index(h) for h in headings] == sorted(report.index(h) for h in headings)
    assert "```bash\nmake data\nmake index\nmake index-chunking" in report
    assert "make report\n```" in report


def test_analysis_included_verbatim_and_missing_files(tmp_path):
    report = build(tmp_path).read_text(encoding="utf-8")
    assert "Analysis pending." in report
    assert "Not run yet" in report
    analysis = "### Findings\n\nExact text.\n\n### Improvements\nKeep this.\n"
    (tmp_path / "eval").mkdir(exist_ok=True)
    (tmp_path / "eval/analysis.md").write_text(analysis, encoding="utf-8")
    report = build(tmp_path).read_text(encoding="utf-8")
    assert analysis in report
    assert "Analysis pending." not in report


def test_failure_limits_by_category_and_kind_and_truncation(tmp_path):
    rows = [
        {
            "id": str(i),
            "question": "Why?",
            "category": "injection",
            "answer": "x" * 900,
            "metrics": {"judge_correctness": i / 10},
        }
        for i in range(4)
    ]
    for kind in ("e2e", "retrieval"):
        save_result(
            tmp_path,
            kind,
            {"kind": kind, "configs": {"first": {"rows": rows}, "second": {"rows": rows}}},
        )
    report = build(tmp_path).read_text(encoding="utf-8")
    failures = report.split("## Failure cases")[1].split("## Appendix")[0]
    assert failures.count("Question: Why?") == 4
    answers = [
        line.removeprefix("Got: ") for line in failures.splitlines() if line.startswith("Got: ")
    ]
    assert all(len(answer) == 400 and answer.endswith("...") for answer in answers)
    assert "#### 3 (" not in failures
