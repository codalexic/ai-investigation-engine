import random
from pathlib import Path
from typing import Any

from app.core.errors import IngestionError
from app.corpus.common import short_hash, slug, write_jsonl


def document_id(title: str) -> str:
    return f"hotpot:{slug(title)}-{short_hash(title)}"


def parse_rows(rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict], int]:
    paragraphs: dict[str, dict] = {}
    questions = []
    conflicts = 0
    for row in rows:
        context = row["context"]
        pairs = (
            zip(context["title"], context["sentences"], strict=True)
            if isinstance(context, dict)
            else context
        )
        for title, sentences in pairs:
            key, text = document_id(title), "\n".join(sentences)
            previous = paragraphs.get(key)
            if previous and previous["text"] != text:
                conflicts += 1
            if previous is None or len(text) > len(previous["text"]):
                paragraphs[key] = {
                    "doc_id": key,
                    "text": text,
                    "metadata": {
                        "title": title,
                        "source": "hotpotqa",
                        "doc_type": "encyclopedia",
                        "dataset": "hotpotqa",
                    },
                }
        facts = row["supporting_facts"]
        titles = facts["title"] if isinstance(facts, dict) else [fact[0] for fact in facts]
        questions.append(
            {key: row[key] for key in ("id", "question", "answer", "type", "level")}
            | {"gold_doc_ids": list(dict.fromkeys(document_id(title) for title in titles))}
        )
    return sorted(paragraphs.values(), key=lambda item: item["doc_id"]), questions, conflicts


def build(root: Path = Path(".")) -> dict[str, int]:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download, list_repo_files

    repo = "hotpotqa/hotpot_qa"
    files = sorted(
        name
        for name in list_repo_files(repo, repo_type="dataset")
        if name.startswith("distractor/") and "validation" in name and name.endswith(".parquet")
    )
    if not files:
        raise IngestionError("HotpotQA distractor validation parquet was not found")
    rows = []
    for name in files:
        path = hf_hub_download(repo, name, repo_type="dataset", cache_dir=root / "data/raw")
        rows.extend(pq.read_table(path).to_pylist())
    records, questions, conflicts = parse_rows(rows)
    if len(records) < 50_000:
        raise IngestionError(f"Expected at least 50000 paragraphs, found {len(records)}")
    write_jsonl(root / "data/corpus/hotpotqa.jsonl", records)
    questions.sort(key=lambda item: item["id"])
    write_jsonl(
        root / "eval/data/hotpotqa_questions.jsonl", random.Random(42).sample(questions, 1000)
    )
    rng = random.Random(7)
    subset = [
        q
        for kind in ("bridge", "comparison")
        for q in rng.sample([q for q in questions if q["type"] == kind], 10)
    ]
    write_jsonl(root / "eval/data/hotpotqa_e2e.jsonl", subset)
    return {"records": len(records), "questions": len(questions), "conflicts": conflicts}
