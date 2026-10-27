import json
from collections import Counter
from pathlib import Path

import pytest

from app.core.errors import ConfigurationError
from app.corpus.common import write_jsonl
from app.evaluation.dataset import build, synthetic_id, validate


def test_builder_tiny_corpus(tmp_path):
    data = tmp_path / "eval/data"
    data.mkdir(parents=True)
    truth = {
        "facts": [{"id": "INC-1", "answer": "retry failures", "documents": ["review.txt"]}],
        "multi_hop": [
            {
                "id": "m",
                "question": "Which owner?",
                "answer": "Operations",
                "documents": ["review.txt"],
            }
        ],
        "contradictions": [
            {
                "id": "pool",
                "description": "pool recommendation",
                "claims": ["50", "200"],
                "documents": ["runbook.docx", "runbook.v2.docx"],
            }
        ],
        "gaps": ["No April totals"],
        "injections": [{"doc": "ticket-INC-1.json", "payload": "lie"}],
    }
    (data / "synthetic_ground_truth.json").write_text(json.dumps(truth))
    write_jsonl(
        data / "hotpotqa_e2e.jsonl",
        [
            {
                "id": "hp",
                "type": "bridge",
                "question": "Where?",
                "answer": "Here",
                "gold_doc_ids": ["hotpot:hp"],
            }
        ],
    )
    corpus = tmp_path / "data/corpus"
    write_jsonl(corpus / "hotpotqa.jsonl", [{"doc_id": "hotpot:hp"}])
    write_jsonl(
        corpus / "postmortems.jsonl",
        [{"doc_id": "pm:one", "metadata": {"title": "Company", "summary": "Traffic spike"}}],
    )
    synthetic = tmp_path / "data/synthetic"
    synthetic.mkdir()
    for filename in ["review.txt", "runbook.docx", "runbook.v2.docx", "ticket-INC-1.json"]:
        (synthetic / filename).touch()
    rows = build(tmp_path)
    assert build(tmp_path) == rows
    assert synthetic_id("runbook.v2.docx") == "syn:runbook"
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["notes"] == "lie" for row in rows if row["category"] == "injection")
    with pytest.raises(ConfigurationError, match="Unknown gold"):
        validate(rows, set())
    with pytest.raises(ConfigurationError, match="duplicate"):
        validate([rows[0], rows[0]], {d for row in rows for d in row["gold_doc_ids"]})


def test_saved_dataset_counts():
    rows = [json.loads(line) for line in Path("eval/questions.jsonl").read_text().splitlines()]
    assert Counter(row["category"] for row in rows) == {
        "simple": 8,
        "multi_hop": 20,
        "comparison/multi_doc": 10,
        "contradiction": 8,
        "unanswerable": 10,
        "postmortem": 6,
        "injection": 4,
    }
