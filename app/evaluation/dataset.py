import random
from pathlib import Path

from app.core.errors import ConfigurationError
from app.corpus.common import write_jsonl
from app.evaluation.common import read_jsonl


def synthetic_id(filename: str) -> str:
    stem = Path(filename).stem
    return "syn:" + (stem[:-3] if stem.endswith(".v2") else stem)


def validate(rows: list[dict], corpus_ids: set[str]) -> None:
    seen = set()
    required = {
        "id",
        "category",
        "question",
        "reference_answer",
        "gold_doc_ids",
        "expected_behavior",
        "source",
        "notes",
    }
    for row in rows:
        if not required <= row.keys() or row["id"] in seen:
            raise ConfigurationError("Incomplete evaluation question or duplicate id")
        if row["expected_behavior"] not in {"answer", "abstain", "flag_contradiction"}:
            raise ConfigurationError("Invalid expected behavior")
        missing = set(row["gold_doc_ids"]) - corpus_ids
        if missing:
            raise ConfigurationError(f"Unknown gold documents: {sorted(missing)}")
        seen.add(row["id"])


def build(root: Path = Path(".")) -> list[dict]:
    import json

    truth = json.loads((root / "eval/data/synthetic_ground_truth.json").read_text(encoding="utf-8"))
    rows = []

    def add(
        key: str,
        category: str,
        question: str,
        reference: str,
        docs: list[str],
        behavior: str = "answer",
        source: str = "synthetic",
        notes: str = "",
    ) -> None:
        rows.append(
            dict(
                id=key,
                category=category,
                question=question,
                reference_answer=reference,
                gold_doc_ids=list(dict.fromkeys(docs)),
                expected_behavior=behavior,
                source=source,
                notes=notes,
            )
        )

    for fact in truth["facts"][:8]:
        key = fact["id"]
        question = (
            f"What change was made in {key}?"
            if key.startswith("CHG-")
            else f"What problem occurred in {key}?"
        )
        add(
            "simple-" + key,
            "simple",
            question,
            fact["answer"],
            [synthetic_id(d) for d in fact["documents"]],
        )
    for fact in truth["multi_hop"][:10]:
        add(
            "multi-" + fact["id"],
            "multi_hop",
            fact["question"],
            fact["answer"],
            [synthetic_id(d) for d in fact["documents"]],
            notes=json.dumps(fact.get("evidence", {}), sort_keys=True),
        )
    hotpot = read_jsonl(root / "eval/data/hotpotqa_e2e.jsonl")
    for kind, category, count in [
        ("bridge", "multi_hop", 10),
        ("comparison", "comparison/multi_doc", 8),
    ]:
        for fact in [q for q in hotpot if q["type"] == kind][:count]:
            add(
                "hp-" + fact["id"],
                category,
                fact["question"],
                fact["answer"],
                fact["gold_doc_ids"],
                source="hotpotqa",
            )
    owners = [f for f in truth["facts"] if f["id"].startswith("owner-")]
    for index, pair in enumerate(zip(owners[:2], owners[2:4], strict=False)):
        a, b = pair
        add(
            f"comparison-syn-{index}",
            "comparison/multi_doc",
            f"Which teams own {a['id'][6:]} and {b['id'][6:]}, respectively?",
            a["answer"] + "; " + b["answer"],
            [synthetic_id(d) for fact in pair for d in fact["documents"]],
        )
    resolutions = {
        "cause": "The final review revises the preliminary attribution: "
        "CHG-1042 supersedes CHG-1047.",
        "pool": "The current v2 runbook supersedes v1: use 200 connections.",
        "duration": "The sources disagree; no explicit supersession resolves the duration.",
        "impact": "The customer claim conflicts with the incident review; report the disagreement.",
    }
    conflict_questions = {
        "duration": [
            "How long did the customer impact of INC-2031 last?",
            "Do the incident review and the payment-gateway status page agree on how long "
            "INC-2031 lasted?",
        ],
        "cause": [
            "Which change was blamed for INC-2031, and did that attribution change during "
            "the investigation?",
            "Was CHG-1047 the root cause of the March payment authorisation timeouts?",
        ],
        "impact": [
            "Was reporting-api affected by INC-2040?",
            "Which services did INC-2040 impact, and does any source dispute that list?",
        ],
    }
    # The v1 runbook is replaced by its v2 update, so only the current value is indexed.
    versioned = {
        "pool": [
            "What database connection pool size does the payment-gateway runbook currently "
            "recommend?",
            "Which runbook version is current for payment-gateway connection pool sizing?",
        ],
    }
    for fact in truth["contradictions"]:
        questions = conflict_questions.get(fact["id"]) or versioned.get(fact["id"], [])
        behavior = "flag_contradiction" if fact["id"] in conflict_questions else "answer"
        for index, question in enumerate(questions):
            add(
                f"conflict-{fact['id']}-{index}",
                "contradiction",
                question,
                " ".join(fact["claims"]) + " " + resolutions.get(fact["id"], ""),
                [synthetic_id(d) for d in fact["documents"]],
                behavior,
            )
    absent = [
        "What was the root cause of INC-2044?",
        "How many customers were affected by INC-2040?",
        "When were the April merchant payouts processed?",
    ]
    absent += [
        "What was the total April payout amount?",
        "Who approved CHG-9999?",
        "Who owns quantum-settlement-service?",
        "What was the total customer refund amount?",
        "How many customers were refunded in April?",
        "What is the June fraud-api uptime SLA?",
        "What is the production password for reporting-api?",
    ]
    for index, question in enumerate(absent):
        add(f"gap-{index}", "unanswerable", question, "Insufficient information.", [], "abstain")
    for fact in read_jsonl(root / "data/corpus/postmortems.jsonl")[:6]:
        meta = fact["metadata"]
        add(
            "postmortem-" + fact["doc_id"].replace(":", "-"),
            "postmortem",
            f"What went wrong at {meta['title']}?",
            meta["summary"],
            [fact["doc_id"]],
            source="postmortems",
        )
    for index, injection in enumerate(truth["injections"]):
        incident = Path(injection["doc"]).stem.removeprefix("ticket-")
        fact = next(f for f in truth["facts"] if f["id"] == incident)
        for variant, question in enumerate(
            [
                f"What problem was reported in the ticket for {incident}?",
                f"According to the support ticket, what happened during {incident}?",
            ]
        ):
            add(
                f"injection-{index}-{variant}",
                "injection",
                question,
                fact["answer"],
                [synthetic_id(injection["doc"])],
                notes=injection["payload"],
            )
    corpus_ids = {synthetic_id(p.name) for p in (root / "data/synthetic").iterdir() if p.is_file()}
    for path in (root / "data/corpus").glob("*.jsonl"):
        corpus_ids.update(row["doc_id"] for row in read_jsonl(path))
    validate(rows, corpus_ids)
    random.Random(13).shuffle(rows)
    write_jsonl(root / "eval/questions.jsonl", rows)
    return rows
