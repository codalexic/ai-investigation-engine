from unittest.mock import Mock

import numpy as np
import pytest
from sqlalchemy import create_engine

from app.retrieval.bm25 import Bm25Encoder, Bm25Statistics, Bm25StatsRepository, bm25_scores
from app.retrieval.embeddings import FastEmbedEmbedder, HashingEmbedder
from app.retrieval.text import analyze


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The CATS and dogs", ["cat", "dog"]),
        (
            "CHG-1042 payment-service v2.3.1",
            [
                "chg-1042",
                "chg",
                "1042",
                "payment-service",
                "payment",
                "service",
                "v2.3.1",
                "v2",
                "3",
                "1",
            ],
        ),
        ("running stopped quickly studies boxes", ["run", "stop", "quick", "study", "box"]),
        ("123 sing bed gas", ["123", "sing", "bed", "gas"]),
        ("", []),
    ],
)
def test_analyzer(text, expected):
    assert analyze(text) == expected


def test_hashing():
    embedder = HashingEmbedder()
    rows = embedder.embed_documents(
        ["payment rollback failure", "payment rollback", "bananas orchard"]
    )
    assert rows.dtype == np.float32
    assert rows.shape == (3, 64)
    np.testing.assert_allclose(np.linalg.norm(rows, axis=1), 1, atol=1e-6)
    assert rows[0] @ rows[1] > rows[0] @ rows[2]
    np.testing.assert_array_equal(rows[0], embedder.embed_query("payment rollback failure"))
    assert embedder.embed_documents([]).shape == (0, 64)


def test_lazy_embedding_and_cache(fake_model, monkeypatch):
    monkeypatch.setattr("fastembed.TextEmbedding", lambda **kw: fake_model)
    embedder = FastEmbedEmbedder("test-model")
    assert embedder._model is None
    assert embedder.dim == 3
    np.testing.assert_allclose(embedder.embed_documents(["a"]), [[0.6, 0.8, 0]])
    query = embedder.embed_query("question")
    query[0] = 99
    np.testing.assert_array_equal(embedder.embed_query("question"), [0, 0, 1])
    assert fake_model.query_embed.call_count == 1


def test_sparse_equals_reference_and_persistence():
    docs = ["cat cat dog", "dog mouse", "cat hamster mouse mouse", ""]
    stats = Bm25Statistics()
    for doc in docs:
        stats.add_document(analyze(doc))
    encoder = Bm25Encoder(stats)
    query = encoder.encode_query("cat mouse mouse")
    q = dict(zip(query.indices, query.values, strict=True))
    actual = []
    for doc in docs:
        vector = encoder.encode_document(doc)
        actual.append(
            sum(q.get(i, 0) * v for i, v in zip(vector.indices, vector.values, strict=True))
        )
    np.testing.assert_allclose(actual, bm25_scores("cat mouse mouse", docs), atol=1e-6)
    engine = create_engine("sqlite:///:memory:")
    repo = Bm25StatsRepository(engine)
    repo.save(stats)
    loaded = repo.load()
    assert loaded == stats
    assert not stats.dirty
    repo.save(stats)
    for doc in docs:
        stats.remove_document(analyze(doc))
    repo.save(stats)
    assert repo.load() == Bm25Statistics()
    engine.dispose()


def test_incremental_stats_and_failed_persistence(monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    from app.core.errors import RetrievalError

    engine = create_engine("sqlite:///:memory:")
    repo = Bm25StatsRepository(engine)
    stats = Bm25Statistics()
    stats.add_document(["alpha"])
    repo.save(stats)
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(
            (statement, params)
        ),
    )
    stats.add_document(["beta"])
    repo.save(stats)
    term_queries = [(sql, params) for sql, params in statements if "bm25_terms" in sql]
    assert len(term_queries) == 2
    assert all("alpha" not in str(params) for _, params in term_queries)
    stats.add_document(["gamma"])
    with monkeypatch.context() as scoped:
        scoped.setattr(engine, "begin", Mock(side_effect=OperationalError("failure", None, None)))
        with pytest.raises(RetrievalError):
            repo.save(stats)
    assert stats.dirty == {"gamma"}
    repo.save(stats)
    assert repo.load() == stats
    engine.dispose()


def test_query_cache_eviction_and_embedding_errors(fake_model, monkeypatch):
    from app.core.errors import RetrievalError

    monkeypatch.setattr("fastembed.TextEmbedding", lambda **kw: fake_model)
    embedder = FastEmbedEmbedder("test", query_cache_size=1)
    embedder.embed_query("first")
    embedder.embed_query("second")
    embedder.embed_query("first")
    assert fake_model.query_embed.call_count == 3
    fake_model.embed.side_effect = RuntimeError("offline")
    with pytest.raises(RetrievalError):
        embedder.embed_documents(["test"])
    fake_model.query_embed.side_effect = RuntimeError("offline")
    with pytest.raises(RetrievalError):
        embedder.embed_query("uncached")


def test_statistics_save_keeps_mutations_during_io(tmp_path):
    from sqlalchemy import event

    engine = create_engine(f"sqlite:///{tmp_path}/stats.db")
    repo = Bm25StatsRepository(engine)
    stats = Bm25Statistics()
    stats.add_document(["alpha"])
    changed = False

    def mutate(conn, cursor, statement, params, context, many):
        nonlocal changed
        if not changed:
            changed = True
            stats.add_document(["beta"])

    event.listen(engine, "before_cursor_execute", mutate)
    repo.save(stats)
    assert stats.dirty == {"beta"}
    repo.save(stats)
    assert repo.load() == stats
    engine.dispose()


def test_threaded_statistics_mutation_and_save(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    engine = create_engine(f"sqlite:///{tmp_path}/stats.db")
    repo = Bm25StatsRepository(engine)
    stats = Bm25Statistics()

    def work(index):
        stats.add_document([str(index), "shared"])
        repo.save(stats)
        stats.remove_document([str(index), "shared"])
        repo.save(stats)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(32)))
    assert stats.N == 0 and not stats.df and not stats.dirty
    assert repo.load() == stats
    engine.dispose()


def test_load_pages_through_terms_and_retries(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    repo = Bm25StatsRepository(engine)
    stats = Bm25Statistics()
    for doc in ["alpha beta", "gamma delta epsilon", "zeta eta theta iota"]:
        stats.add_document(analyze(doc))
    repo.save(stats)
    assert repo.load(page_size=2) == stats
    connect = engine.connect
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("select", {}, Exception("SSL connection closed"))
        return connect()

    monkeypatch.setattr(engine, "connect", flaky)
    assert repo.load(page_size=2) == stats
    engine.dispose()
