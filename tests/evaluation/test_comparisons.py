import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.errors import ConfigurationError
from app.corpus.common import write_jsonl
from app.evaluation import connection, embeddings
from app.evaluation.chunking import run as chunking_run
from app.evaluation.report import build
from app.evaluation.retrieval_eval import run as retrieval_run


def test_read_only_connection(container, monkeypatch):
    class ReadOnlyClient:
        closed = False

        def collection_exists(self, name):
            return True

        def close(self):
            self.closed = True

    client = ReadOnlyClient()
    monkeypatch.setattr(connection, "make_qdrant_client", lambda settings: client)
    before = Path(container.engine.url.database).read_bytes()
    with connection.connect(container.settings) as c:
        assert c.retriever.config.top_k == container.settings.retrieval_top_k
        assert c.store.bm25.stats.N > 0
        with pytest.raises(OperationalError), c.engine.begin() as conn:
            conn.execute(text("CREATE TABLE forbidden (id INTEGER)"))
    assert client.closed
    assert Path(container.engine.url.database).read_bytes() == before
    with (
        pytest.raises(ConfigurationError),
        connection.connect(
            container.settings.model_copy(update={"database_url": "sqlite:///missing-registry.db"})
        ),
    ):
        pass


def test_chunking_three_questions(container, sample_questions, tmp_path):
    c = SimpleNamespace(store=container.store, retriever=container.retriever)
    result = chunking_run(
        {"structure": c, "fixed": c}, sample_questions, output=tmp_path / "chunking.json"
    )
    for config in result["configs"].values():
        assert config["summary"]["count"] == 3
        assert config["summary"]["metrics"]["evidence-hit@10"]["mean"] == 1
        assert config["statistics"]["chunks_per_document"] == 1
        assert config["statistics"]["mean_chunk_tokens"] > 0
    assert "mean_chunk_tokens" in (tmp_path / "chunking.md").read_text()


def test_embedding_subset_contexts(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    rows = [
        {
            "id": "q1",
            "question": "Where?",
            "answer": "Here",
            "type": "bridge",
            "level": "hard",
            "context": {"title": ["First", "Distractor"], "sentences": [["Here."], ["Elsewhere."]]},
            "supporting_facts": {"title": ["First"], "sent_id": [0]},
        }
    ]
    pq.write_table(pa.Table.from_pylist(rows), raw / "tiny.parquet")
    records = embeddings.subset_records(tmp_path, [{"id": "q1"}])
    assert len(records) == 2
    with pytest.raises(ConfigurationError, match="Missing cached"):
        embeddings.subset_records(tmp_path, [{"id": "unknown"}])


def test_embedding_runner_isolation(container, sample_questions, tmp_path, monkeypatch):
    from contextlib import contextmanager

    write_jsonl(tmp_path / "eval/data/hotpotqa_questions.jsonl", sample_questions)
    indexed = []

    def fake_index(settings, sources, root):
        assert settings.qdrant_collection.startswith("emb_")
        assert settings.database_url != container.settings.database_url
        assert sources == ["hotpotqa"]
        indexed.append(settings)
        return {"chunks": 1}

    @contextmanager
    def fake_connect(settings):
        yield container

    monkeypatch.setattr(embeddings, "index_corpus", fake_index)
    monkeypatch.setattr(embeddings, "connect", fake_connect)
    result = embeddings.run(
        container.settings,
        ["one/model", "two/model"],
        root=tmp_path,
        limit=3,
        records=[{"doc_id": "doc-a", "text": "rollback"}],
    )
    assert len(indexed) == 2
    assert indexed[0].qdrant_collection != indexed[1].qdrant_collection
    assert len(result["configs"]) == 4
    assert (tmp_path / "eval/results/embeddings.md").exists()


def test_report_missing_and_results(tmp_path, container, sample_questions):
    path = build(tmp_path)
    report = path.read_text()
    assert "not run yet" in report
    assert report.count("<!-- analysis -->") == 2
    retrieval_run(
        container.retriever,
        sample_questions,
        ["dense"],
        output=tmp_path / "eval/results/retrieval_demo.json",
    )
    report = build(tmp_path).read_text()
    assert "Recall@10" in report
    assert "Question: What happened" in report
    assert "Expected: payment-service" in report
    assert "Got: [" in report
    assert "95% CI" in report
    assert (
        json.loads((tmp_path / "eval/results/retrieval_demo.json").read_text())["kind"]
        == "retrieval"
    )
