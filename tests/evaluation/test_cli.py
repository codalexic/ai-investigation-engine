from contextlib import nullcontext

import pytest

from app.core.errors import ConfigurationError
from app.corpus.common import write_jsonl
from app.evaluation import cli, e2e, embeddings


def test_cli_retrieval_limit_three(container, sample_questions, tmp_path, monkeypatch):
    write_jsonl(
        tmp_path / "questions.jsonl", [*sample_questions, {**sample_questions[0], "id": "fourth"}]
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "connect", lambda settings: nullcontext(container))
    monkeypatch.setattr(cli, "settings_for", lambda *args: container.settings)
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_retrieval.py",
            "--collection",
            "demo",
            "--questions",
            "questions.jsonl",
            "--configs",
            "dense",
            "--limit",
            "3",
        ],
    )
    cli.retrieval_main()
    import json

    result = json.loads((tmp_path / "eval/results/retrieval_demo.json").read_text())
    assert result["configs"]["dense"]["summary"]["count"] == 3


def test_cli_e2e_configurations(container, sample_questions, tmp_path, monkeypatch):

    write_jsonl(tmp_path / "questions.jsonl", sample_questions)
    monkeypatch.chdir(tmp_path)
    settings = container.settings.model_copy(
        update={"groq_api_key": "test", "gemini_api_key": "test"}
    )
    monkeypatch.setattr(cli, "settings_for", lambda *args: settings)
    monkeypatch.setattr(cli, "connect", lambda settings: nullcontext(container))
    calls = []

    def build_llm(settings):
        calls.append(settings)
        fake = type(container.llm)()
        fake.model = (
            settings.llm_primary_model
            if settings.llm_provider_order == ["groq"]
            else settings.llm_fallback_model
        )
        return fake

    monkeypatch.setattr(cli, "build_llm", build_llm)
    for config in ["full", "no_agent", "small_model", "gemini"]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "eval_e2e.py",
                "--config",
                config,
                "--questions",
                "questions.jsonl",
                "--limit",
                "3",
                "--pause",
                "0",
            ],
        )
        cli.e2e_main()
        generator, judge = calls[-2:]
        assert generator.llm_provider_order != judge.llm_provider_order
        if config == "small_model":
            assert generator.llm_primary_model == "llama-3.1-8b-instant"
        if config == "gemini":
            assert generator.llm_provider_order == ["gemini"]
        assert (tmp_path / f"eval/results/e2e_{config}.json").exists()


def test_cli_other_entrypoints(tmp_path, monkeypatch, container, sample_questions):
    from app.evaluation import dataset

    monkeypatch.chdir(tmp_path)
    called = []
    monkeypatch.setattr(dataset, "build", lambda root: called.append(root))
    monkeypatch.setattr("sys.argv", ["build_eval_set.py"])
    cli.dataset_main()
    assert called == [tmp_path.__class__(".")]
    monkeypatch.setattr("sys.argv", ["make_report.py"])
    cli.report_main()
    assert (tmp_path / "docs/EVALUATION_REPORT.md").exists()
    write_jsonl(tmp_path / "questions.jsonl", sample_questions)
    monkeypatch.setattr(cli, "connect", lambda settings: nullcontext(container))
    monkeypatch.setattr(cli, "settings_for", lambda *args: container.settings)
    monkeypatch.setattr(
        "sys.argv",
        [
            "eval_chunking.py",
            "--collections",
            "one,two",
            "--questions",
            "questions.jsonl",
            "--limit",
            "3",
        ],
    )
    cli.chunking_main()
    assert (tmp_path / "eval/results/chunking.json").exists()
    monkeypatch.setattr(embeddings, "run", lambda *a, **k: called.append(k))
    monkeypatch.setattr("sys.argv", ["eval_embeddings.py", "--limit", "3"])
    cli.embeddings_main()
    assert called[-1]["limit"] == 3


def test_stale_cache_rejected(container, sample_questions, tmp_path):
    e2e.run(container.investigator, sample_questions, "no_agent", cache_dir=tmp_path, pause=0)
    sample_questions[0]["reference_answer"] = "changed"
    with pytest.raises(ConfigurationError, match="Stale"):
        e2e.run(container.investigator, sample_questions, "no_agent", cache_dir=tmp_path, pause=0)
