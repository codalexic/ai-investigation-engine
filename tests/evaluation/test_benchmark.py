import json
import random
from contextlib import nullcontext
from functools import lru_cache
from types import SimpleNamespace

import pytest

from app.core.errors import ConfigurationError
from app.corpus.common import write_jsonl
from app.evaluation import benchmark, cli
from app.evaluation.report import build


def test_sampling_and_limit(tmp_path):
    hotpot = [{"id": str(i), "question": str(i)} for i in range(210)]
    investigation = [{"id": "investigation", "question": "Why?"}]
    write_jsonl(tmp_path / "eval/data/hotpotqa_questions.jsonl", hotpot)
    write_jsonl(tmp_path / "eval/questions.jsonl", investigation)
    selected = benchmark.select_questions(tmp_path)
    assert selected == random.Random(3).sample(hotpot, 200) + investigation
    assert benchmark.select_questions(tmp_path, 5) == selected[:5]
    with pytest.raises(ConfigurationError):
        benchmark.select_questions(tmp_path, 0)


def test_run_with_container_and_report(container, sample_questions, tmp_path):
    output = tmp_path / "eval/results/benchmark.json"
    result = benchmark.run(container, sample_questions, (1, 4, 8), output)
    assert result["kind"] == "benchmark"
    assert result["point_count"] == container.store.count()
    assert len(result["runs"]) == 12
    assert result["cache_effect"]["supported"] is False
    for run in result["runs"]:
        assert run["count"] == len(run["rows"]) == 3
        assert run["queries_per_second"] == pytest.approx(3 / run["seconds"])
        assert run["latency_ms"]["p50"] <= run["latency_ms"]["p99"]
        for stage in benchmark.STAGES:
            values = [r["timings_ms"][stage] for r in run["rows"]]
            assert run["stages_ms"][stage]["mean"] == pytest.approx(sum(values) / 3)
    assert json.loads(output.read_text()) == result
    assert "Retrieval stages" in output.with_suffix(".md").read_text()
    write_jsonl(tmp_path / "eval/questions.jsonl", sample_questions)
    (output.parent / "indexing_documents.json").write_text(
        json.dumps({"counts_per_source": {"a": 20, "b": 10}, "chunks": 60, "seconds": 2})
    )
    report = build(tmp_path).read_text()
    assert "### Performance" in report.split("## Analysis")[0]
    assert "| hybrid_rerank | 8 |" in report
    assert "| 30 | 60 | 2.000 | 15.000 |" in report


def test_warmups_excluded_and_invalid_inputs(container, sample_questions, monkeypatch):
    calls = []
    original = container.retriever.search

    def search(query, config):
        calls.append(config.mode)
        return original(query, config)

    monkeypatch.setattr(container.retriever, "search", search)
    result = benchmark.run(container, sample_questions, (1,))
    assert len(calls) == 4 * (10 + 3)
    assert sum(run["count"] for run in result["runs"]) == 12
    for queries, concurrency in [([], (1,)), (sample_questions, (0,)), (sample_questions, ())]:
        with pytest.raises(ConfigurationError):
            benchmark.run(container, queries, concurrency)


def test_cache_passes_clear_existing_entries_and_exclude_model_load(monkeypatch):
    calls = []

    @lru_cache(maxsize=100)
    def embed(query):
        calls.append(query)
        return [1.0]

    connection = SimpleNamespace(
        retriever=SimpleNamespace(embedder=SimpleNamespace(_cached_query=embed, embed_query=embed))
    )
    times = iter([0, 10, 10, 12])
    monkeypatch.setattr(benchmark, "perf_counter", lambda: next(times))
    result = benchmark.cache_effect(connection, [str(i) for i in range(50)])
    assert result["hits"] == [0, 50]
    assert result["speedup"] == 5
    assert len(calls) == 51


def test_cli(container, sample_questions, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_jsonl(tmp_path / "eval/data/hotpotqa_questions.jsonl", sample_questions)
    write_jsonl(tmp_path / "eval/questions.jsonl", sample_questions)
    settings = container.settings.model_copy(update={"app_env": "local"})
    monkeypatch.setattr(cli, "settings_for", lambda *args: settings)
    monkeypatch.setattr(cli, "connect", lambda settings: nullcontext(container))
    monkeypatch.setattr("sys.argv", ["benchmark.py", "--limit", "2", "--concurrency", "1"])
    cli.benchmark_main()
    result = json.loads((tmp_path / "eval/results/benchmark.json").read_text())
    assert len(result["question_ids"]) == 2
    assert {run["concurrency"] for run in result["runs"]} == {1}
