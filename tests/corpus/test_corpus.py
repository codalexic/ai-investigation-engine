import json
from unittest.mock import Mock

import pyarrow as pa
from sqlalchemy import create_engine

from app.core.config import Settings
from app.corpus.common import short_hash, slug, write_jsonl
from app.corpus.hotpotqa import document_id, parse_rows
from app.corpus.indexer import index_sources, run
from app.corpus.postmortems import build, parse_readme
from app.corpus.synthetic import SCENARIO, generate
from app.ingest.chunking import build_chunker
from app.ingest.dedup import LSHIndex, MinHasher
from app.ingest.parsers import get_parser
from app.ingest.pipeline import IngestionPipeline
from app.ingest.registry import DocumentRegistry
from app.retrieval.factory import build_retrieval


def test_common(tmp_path):
    assert slug("A & B") == "a-b"
    assert len(short_hash("A")) == 8
    path = tmp_path / "records.jsonl"
    write_jsonl(path, [{"text": "hello"}])
    assert json.loads(path.read_text()) == {"text": "hello"}


def test_hotpot_rows():
    rows = []
    for text in ("Short", "Longer paragraph"):
        rows.append(
            dict(
                id=text,
                question="Which?",
                answer="A",
                type="bridge",
                level="easy",
                context={"title": ["A!", "A?"], "sentences": [[text], ["Second"]]},
                supporting_facts={"title": ["A!"], "sent_id": [0]},
            )
        )
    table = pa.Table.from_pylist(rows)
    records, questions, conflicts = parse_rows(table.to_pylist())
    assert len(records) == 2 and conflicts == 1
    assert document_id("A!") != document_id("A?")
    assert (
        next(r for r in records if r["doc_id"] == document_id("A!"))["text"] == "Longer paragraph"
    )
    assert questions[0]["gold_doc_ids"] == [document_id("A!")]


SAMPLE = """# Incidents
## Payments
* [Acme](https://example.org/1) - database outage
- [Beta](https://example.org/2) TLS issue
## Infrastructure
* [Gamma](https://example.org/3) network partition
* [Delta](https://example.org/4) disk failure
* [Epsilon](https://example.org/5) DNS outage
"""


def test_postmortems(tmp_path, monkeypatch):
    records = parse_readme(SAMPLE)
    assert len(parse_readme(SAMPLE.replace("* [", "[").replace("- [", "["))) == 5
    assert len(records) == 5
    assert records[0]["metadata"]["category"] == "Payments"
    assert records[-1]["metadata"]["summary"] == "DNS outage"
    response = Mock(text=SAMPLE)
    get = Mock(return_value=response)
    monkeypatch.setattr("app.corpus.postmortems.httpx.get", get)
    assert build(tmp_path) == {"records": 5}
    build(tmp_path)
    get.assert_called_once()


def test_synthetic(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    assert generate(first)["documents"] == 45
    generate(second)
    parsed = {}
    for path in (first / "data/synthetic").iterdir():
        parsed[path.name] = get_parser(path.name).parse(path.read_bytes(), path.name).text
        assert parsed[path.name]
        if path.suffix not in (".pdf", ".docx"):
            assert path.read_bytes() == (second / "data/synthetic" / path.name).read_bytes()
    truth = json.loads((first / "eval/data/synthetic_ground_truth.json").read_text())
    for fact in truth["facts"]:
        assert any(fact["answer"] in parsed[name] for name in fact["documents"])
    for contradiction in truth["contradictions"]:
        for name, claim in zip(contradiction["documents"], contradiction["claims"], strict=True):
            assert claim in parsed[name]
    assert len(SCENARIO["changes"]) >= 50


def test_indexer_end_to_end(tmp_path):
    generate(tmp_path)
    write_jsonl(
        tmp_path / "data/corpus/hotpotqa.jsonl",
        [
            {
                "doc_id": f"hotpot:{i}",
                "text": f"Unique paragraph {i} about topic {i * i} and event {i * 17}",
                "metadata": {"title": f"Title {i}", "doc_type": "encyclopedia"},
            }
            for i in range(20)
        ],
    )
    engine = create_engine("sqlite:///:memory:")
    settings = Settings(_env_file=None, app_env="test")
    store, _ = build_retrieval(settings, engine)
    store.bulk = True
    registry = DocumentRegistry(engine)
    pipeline = IngestionPipeline(registry, store, build_chunker(settings), MinHasher(), LSHIndex())
    try:
        result = index_sources(pipeline, ["hotpotqa", "synthetic"], tmp_path, batch_size=7)
        assert result["counts_per_source"]["hotpotqa"] == 20
        assert registry.get("hotpot:0").doc_type == "encyclopedia"
        assert registry.get("hotpot:0").title == "Title 0"
        assert registry.get("hotpot:0").extra["origin"] == "seed"
        assert result["counts_per_source"]["synthetic"] == 45
        assert registry.get("syn:runbook-payment-gateway").version == 2
        assert registry.get("syn:runbook-payment-gateway").extra["origin"] == "seed"
        assert result["near_duplicates"] >= 1
        assert store.count() > 50
        again = index_sources(pipeline, ["hotpotqa", "synthetic"], tmp_path)
        assert sum(again["counts_per_source"].values()) == 0
        assert again["chunks"] == 0
    finally:
        store.client.close()
        engine.dispose()


def test_report(tmp_path):
    generate(tmp_path)
    result = run(
        Settings(_env_file=None, app_env="test", database_url="sqlite:///:memory:"),
        ["synthetic"],
        tmp_path,
        limit=2,
        recreate=True,
    )
    report = tmp_path / "eval/results/indexing_documents.json"
    assert json.loads(report.read_text()) == result
    assert result["counts_per_source"]["synthetic"] == 2
    assert result["qdrant_point_count"] > 0
