from unittest.mock import Mock

from app.api.llm_metrics import MeteredClient
from app.api.observability import Metrics, RateLimiter
from app.core.errors import RetrievalError
from app.llm.types import LLMResponse, Usage


def test_system(api_client, monkeypatch):
    api_client.post(
        "/api/documents", files={"file": ("incident.txt", b"payment-service rollback succeeded")}
    )
    assert api_client.get("/").status_code == 200
    assert "Investigation Engine" in api_client.get("/").text
    for asset in ("app.js", "styles.css"):
        assert api_client.get("/static/" + asset).status_code == 200
    assert api_client.get("/ready").json() == {"status": "ready"}
    stats = api_client.get("/api/stats").json()
    assert stats["documents"]["total"] == 1
    assert stats["documents"]["by_origin"] == {"user": 1}
    assert stats["chunks"] >= 1
    api_client.post("/api/investigate", json={"question": "What happened to payment-service?"})
    api_client.post("/api/investigate", json={"question": "What happened to payment-service?"})
    metrics = api_client.get("/metrics").text
    for name in (
        "http_requests_total",
        "http_request_duration_seconds",
        "investigation_duration_seconds",
        "llm_tokens_total",
        "llm_cost_total",
        "llm_calls_total",
        "cache_hits_total",
        "retrieval_stage_duration_seconds",
        "abstentions_total",
    ):
        assert name in metrics
    monkeypatch.setattr(
        api_client.app.state.container.store, "count", Mock(side_effect=RetrievalError("offline"))
    )
    assert api_client.get("/ready").status_code == 503


def test_metrics_isolated_and_accounted():
    metrics = Metrics()
    other = Metrics()
    inner = Mock()
    inner.chat.return_value = LLMResponse(
        provider="test",
        model="llama-3.3-70b-versatile",
        usage=Usage(prompt_tokens=10, completion_tokens=5),
    )
    client = MeteredClient(inner, metrics)
    client.chat([])
    assert metrics.calls.labels("test", "llama-3.3-70b-versatile")._value.get() == 1
    assert metrics.cost.labels("test", "llama-3.3-70b-versatile")._value.get() > 0
    assert other.calls.labels("test", "llama-3.3-70b-versatile")._value.get() == 0
    client.record(inner.chat.return_value.model_copy(update={"cached": True}))
    assert metrics.cache_hits.labels("llm")._value.get() == 1


def test_rate_limiter(monkeypatch):
    current = [0.0]
    monkeypatch.setattr("app.api.observability.monotonic", lambda: current[0])
    limiter = RateLimiter()
    assert limiter.check("one", "investigate", 1) == 0
    assert limiter.check("one", "investigate", 1) > 0
    assert limiter.check("two", "investigate", 1) == 0
    assert limiter.check("one", "general", 120) == 0
    current[0] = 61
    assert limiter.check("one", "investigate", 1) == 0
    current[0] = 300
    limiter.check("three", "general", 120)
    assert ("one", "investigate") not in limiter.buckets


def test_general_rate_limit_and_route_labels(api_client, monkeypatch):
    monkeypatch.setattr("app.api.observability.monotonic", lambda: 1)
    for _ in range(120):
        assert api_client.get("/api/documents/absent").status_code == 404
    response = api_client.get("/api/documents/absent")
    assert response.status_code == 429
    assert "X-Request-ID" in response.headers
    metrics = api_client.get("/metrics").text
    assert 'route="/api/documents/{doc_id}",status="429"' in metrics


def test_empty_admin_token_is_unset():
    from app.core.config import Settings

    assert Settings(_env_file=None, admin_token="").admin_token is None
