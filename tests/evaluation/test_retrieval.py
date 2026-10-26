import pytest

from app.core.errors import ConfigurationError
from app.evaluation.common import questions, read_jsonl, safe_name, write_json
from app.evaluation.retrieval_eval import CONFIGS, retrieval_config, run


def test_retrieval_three_questions(container, sample_questions, tmp_path):
    result = run(
        container.retriever, sample_questions, ks=(1, 5, 10), output=tmp_path / "result.json"
    )
    assert set(result["configs"]) == set(CONFIGS)
    for config in result["configs"].values():
        assert config["summary"]["count"] == 3
        assert config["summary"]["metrics"]["Recall@1"]["mean"] == 1
        assert config["by_source"]["synthetic"]["count"] == 3
        assert config["by_category"]["simple"]["count"] == 3
    assert (tmp_path / "result.md").exists()
    assert retrieval_config("dense", 10).mmr is False
    assert retrieval_config("hybrid_rerank_mmr", 10).mmr is True
    sample_questions[0]["expected_behavior"] = "abstain"
    assert (
        run(container.retriever, sample_questions, ["dense"])["configs"]["dense"]["summary"][
            "count"
        ]
        == 2
    )
    with pytest.raises(ConfigurationError):
        retrieval_config("invalid", 10)


def test_common_loader_and_validation(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text('{"id":"1","question":"Q","answer":"A","gold_doc_ids":[]}\n')
    rows = questions(str(path) + "," + str(path), 3)
    assert len(rows) == 1
    assert rows[0]["reference_answer"] == "A"
    assert read_jsonl(path)[0]["id"] == "1"
    write_json(tmp_path / "nested/result.json", rows)
    with pytest.raises(ConfigurationError):
        safe_name("../escape")
    with pytest.raises(ConfigurationError):
        questions(str(path), -1)
