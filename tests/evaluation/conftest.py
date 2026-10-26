import json

import pytest

from app.agent.engine import InvestigationEngine
from app.agent.nli import FakeNli
from app.container import Container
from app.core.config import Settings
from app.llm.types import LLMResponse, Usage


class FakeLLM:
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return LLMResponse(
            content=json.dumps(
                {
                    "complexity": "simple",
                    "score": 1,
                    "injection_resistant": True,
                    "reason": "matches reference",
                }
            ),
            provider="fake",
            model=self.model,
            usage=Usage(prompt_tokens=5, completion_tokens=2),
        )

    def stream(self, messages, **kwargs):
        self.calls += 1
        yield "payment-service rollback succeeded [E1]."
        yield (
            "<meta>"
            + json.dumps(
                {
                    "claims": [{"text": "payment-service rollback succeeded", "evidence": ["E1"]}],
                    "confidence": "high",
                }
            )
            + "</meta>"
        )
        self.last_response = LLMResponse(
            model=self.model, provider="fake", usage=Usage(prompt_tokens=10, completion_tokens=8)
        )


@pytest.fixture
def container(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        qdrant_url=":memory:",
        qdrant_collection="evaluation_test",
        database_url=f"sqlite:///{tmp_path}/registry.db",
        llm_provider_order=[],
        agent_max_steps=1,
    )
    c = Container.build(settings)
    c.pipeline.ingest(
        b"payment-service rollback succeeded. Incident response completed.", "rollback.txt", "doc-a"
    )
    c.llm = FakeLLM()
    c.investigator = InvestigationEngine(c.retriever, c.store, c.llm, FakeNli(), settings)
    yield c
    c.close()


@pytest.fixture
def sample_questions():
    return [
        dict(
            id=f"q-{i}",
            category="simple",
            question=f"What happened in incident {i}?",
            reference_answer="payment-service rollback succeeded",
            gold_doc_ids=["doc-a"],
            expected_behavior="answer",
            source="synthetic",
            notes="",
        )
        for i in range(3)
    ]
