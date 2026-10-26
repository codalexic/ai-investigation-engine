import json

import pytest
from fastapi.testclient import TestClient

from app.agent.engine import InvestigationEngine
from app.agent.nli import FakeNli
from app.api.main import create_app
from app.container import Container, get_container
from app.core.config import Settings
from app.llm.types import LLMResponse, StreamResult, Usage


class FakeLLM:
    model = "fake-model"

    def chat(self, messages, **kwargs):
        content = json.dumps({"complexity": "simple"}) if kwargs.get("json_mode") else "Ready"
        return LLMResponse(
            content=content,
            provider="fake",
            model=self.model,
            usage=Usage(prompt_tokens=5, completion_tokens=2),
        )

    def stream(self, messages, **kwargs):
        return StreamResult(lambda result: self._stream(messages, result, **kwargs))

    def _stream(self, messages, result, **kwargs):
        yield "payment-service rollback succeeded [E1]."
        yield (
            "<meta>"
            + json.dumps(
                {
                    "claims": [{"text": "payment-service rollback succeeded", "evidence": ["E1"]}],
                    "confidence": "high",
                    "missing": [],
                    "contradictions": [],
                }
            )
            + "</meta>"
        )
        result.response = LLMResponse(
            provider="fake", model=self.model, usage=Usage(prompt_tokens=10, completion_tokens=8)
        )


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path}/api.db",
        qdrant_collection="m6_test",
        max_upload_mb=1,
        rate_limit_per_minute=100,
    )
    original = Container.build

    def build(settings):
        container = original(settings)
        container.llm = FakeLLM()
        container.investigator = InvestigationEngine(
            container.retriever, container.store, container.llm, FakeNli(), settings
        )
        return container

    monkeypatch.setattr(Container, "build", build)
    application = create_app(settings)
    with TestClient(application) as client:
        application.dependency_overrides[get_container] = lambda: application.state.container
        yield client
