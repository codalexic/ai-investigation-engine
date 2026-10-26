import json
from types import SimpleNamespace

import pytest

from app.agent.engine import Citation, InvestigationResult
from app.agent.synthesizer import Claim, Contradiction
from app.core.errors import LLMError, LLMRateLimitError
from app.evaluation.cache import EvaluationCachedClient
from app.evaluation.e2e import judge_answer, run, score
from app.llm.types import LLMResponse


def test_e2e_three_questions_resume(container, sample_questions, tmp_path):
    cached = EvaluationCachedClient(container.llm, container.engine)
    container.investigator.llm = cached
    result = run(
        container.investigator,
        sample_questions,
        "no_agent",
        cached,
        tmp_path / "cache",
        tmp_path / "result.json",
        pause=0,
    )
    assert len(result["rows"]) == 3
    assert all(row["verifier_report"] for row in result["rows"])
    assert result["summary"]["metrics"]["citation_recall"]["mean"] == 1
    assert result["rows"][0]["judge"]["provider"] == "fake"
    calls = container.llm.calls
    resumed = run(
        container.investigator, sample_questions, "no_agent", cached, tmp_path / "cache", pause=0
    )
    assert container.llm.calls == calls
    assert resumed["rows"] == result["rows"]
    assert (tmp_path / "result.md").exists()


def test_stream_and_chat_cached(container):
    cached = EvaluationCachedClient(container.llm, container.engine)
    from app.llm.types import Message

    messages = [Message(role="user", content="Q")]
    first = "".join(cached.stream(messages))
    calls = container.llm.calls
    stream = cached.stream(messages)
    assert "".join(stream) == first
    assert stream.response.cached
    assert container.llm.calls == calls
    cached.chat(messages)
    cached.chat(messages)
    assert container.llm.calls == calls + 1


def test_rate_limit_preserves_progress(container, sample_questions, tmp_path):
    original = container.investigator.investigate_stream
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LLMRateLimitError("quota")
        yield from original(*args, **kwargs)

    container.investigator.investigate_stream = interrupted
    result = run(
        container.investigator,
        sample_questions,
        "no_agent",
        cache_dir=tmp_path / "cache",
        output=tmp_path / "result.json",
        pause=0,
    )
    assert result["stopped_on_rate_limit"]
    assert len(result["rows"]) == 1
    assert not (tmp_path / "cache/no_agent/q-1.json").exists()
    container.investigator.investigate_stream = original
    result = run(
        container.investigator, sample_questions, "no_agent", cache_dir=tmp_path / "cache", pause=0
    )
    assert len(result["rows"]) == 3
    assert not result["stopped_on_rate_limit"]


def test_engine_propagates_quota(container):
    class LimitedLLM(type(container.llm)):
        def stream(self, *args, **kwargs):
            raise LLMRateLimitError("quota")
            yield

    container.investigator.llm = LimitedLLM()
    with pytest.raises(LLMRateLimitError):
        container.investigator.investigate("Question", agentic=False)


def test_behavior_scoring(sample_questions):
    q = {**sample_questions[0], "category": "contradiction"}
    citation = Citation(
        evidence_id="E1", chunk_id="chunk", doc_id="doc-a", title="", source="", snippet=""
    )
    result = InvestigationResult(
        question="Q",
        answer="rollback",
        abstained=False,
        citations=[citation],
        claims=[Claim(text="rollback", supported=True)],
        contradictions=[Contradiction(description="conflict", evidence=["E1", "E2"])],
    )
    metrics = score(q, result, None)
    assert metrics["contradiction_detection_rate"] == 1
    assert metrics["faithfulness"] == 1
    assert metrics["false_answer_rate"] is None
    assert score({**q, "expected_behavior": "abstain"}, result, None)["false_answer_rate"] == 1
    assert score({**q, "source": "hotpotqa"}, result, None)["exact_match"] == 0
    assert score({**q, "category": "injection"}, result, None)["injection_resistance"] is None
    judge = {
        "score": 0,
        "injection_resistant": False,
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "estimated_cost": 0},
    }
    assert score({**q, "category": "injection"}, result, judge)["injection_resistance"] == 0


def test_judge_rejects_invalid_response(sample_questions):
    judge = SimpleNamespace(chat=lambda *a, **k: LLMResponse(content=json.dumps({"score": 0.7})))
    with pytest.raises(LLMError):
        judge_answer(judge, sample_questions[0], "answer")


def test_contradiction_requires_two_gold_documents(sample_questions):
    q = {**sample_questions[0], "category": "contradiction", "gold_doc_ids": ["a", "b"]}
    result = InvestigationResult(
        question="Q",
        citations=[
            Citation(evidence_id="E1", chunk_id="1", doc_id="a", title="", source="", snippet=""),
            Citation(
                evidence_id="E2", chunk_id="2", doc_id="other", title="", source="", snippet=""
            ),
        ],
        contradictions=[Contradiction(description="conflict", evidence=["E1", "E2"])],
    )
    assert score(q, result, None)["contradiction_detection_rate"] == 0
    result.citations[1].doc_id = "b"
    assert score(q, result, None)["contradiction_detection_rate"] == 1
    assert score({**q, "gold_doc_ids": ["a"]}, result, None)["contradiction_detection_rate"] == 1
