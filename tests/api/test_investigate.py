import json
from datetime import UTC, datetime, timedelta

from app.core.errors import LLMError

QUESTION = {"question": "What happened to payment-service?"}


def seed(client):
    return client.post(
        "/api/documents", files={"file": ("incident.txt", b"payment-service rollback succeeded")}
    ).json()["doc_id"]


def test_search(api_client):
    identifier = seed(api_client)
    result = api_client.post(
        "/api/search",
        json={
            "query": "rollback",
            "filters": {"doc_ids": [identifier]},
            "mode": "hybrid",
            "rerank": True,
            "mmr": False,
        },
    ).json()
    assert result["chunks"][0]["doc_id"] == identifier
    assert {"dense_rank", "sparse_rank", "rerank_score", "boost"} <= result["chunks"][0][
        "explain"
    ].keys()
    assert result["timings_ms"]["total"] >= 0
    assert (
        api_client.post(
            "/api/search", json={"query": "rollback", "filters": {"doc_ids": ["absent"]}}
        ).json()["chunks"]
        == []
    )
    assert api_client.post("/api/search", json={"query": " "}).status_code == 422
    assert api_client.post("/api/search", json={"query": "x", "mode": "invalid"}).status_code == 422


def test_investigation_cache_traces(api_client):
    identifier = seed(api_client)
    first = api_client.post("/api/investigate", json=QUESTION)
    assert first.status_code == 200, first.text
    assert not first.json()["cached"]
    assert first.json()["citations"]
    second = api_client.post("/api/investigate", json=QUESTION).json()
    assert second["cached"]
    assert second["answer"] == first.json()["answer"]
    traces = api_client.get("/api/traces").json()
    assert len(traces) == 2
    assert traces[0]["citations_count"] == 1
    assert api_client.get("/api/traces/" + traces[0]["id"]).json()["trace"]
    assert api_client.get("/api/traces/absent").status_code == 404
    api_client.post(
        "/api/documents",
        files={"file": ("other.txt", b"Independent information on a different topic")},
    )
    assert not api_client.post("/api/investigate", json=QUESTION).json()["cached"]
    api_client.put(
        f"/api/documents/{identifier}",
        files={"file": ("new.txt", b"payment-service rollback succeeded after review")},
    )
    assert not api_client.post("/api/investigate", json=QUESTION).json()["cached"]
    api_client.delete(f"/api/documents/{identifier}")
    assert not api_client.post("/api/investigate", json=QUESTION).json()["cached"]


def test_stream(api_client):
    seed(api_client)
    response = api_client.post("/api/investigate/stream", json=QUESTION)
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = response.text.strip().split("\n\n")
    events = [
        (
            f.splitlines()[0].removeprefix("event: "),
            json.loads(f.splitlines()[1].removeprefix("data: ")),
        )
        for f in frames
    ]
    names = [e[0] for e in events]
    assert names[0] == "plan"
    assert (
        names.index("tool_call")
        < names.index("tool_result")
        < names.index("evidence")
        < names.index("answer_delta")
    )
    assert names[-1] == "final"
    assert events[-1][1]["answer"]
    assert len(api_client.get("/api/traces").json()) == 1
    cached = api_client.post("/api/investigate/stream", json=QUESTION)
    assert cached.text.startswith("event: final\n")
    assert '"cached": true' in cached.text


def test_cache_expiration_and_settings(api_client):
    seed(api_client)
    api_client.post("/api/investigate", json=QUESTION)
    queries = api_client.app.state.queries
    with queries.registry.session() as session:
        session.execute(
            queries.cache.update().values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert not api_client.post("/api/investigate", json=QUESTION).json()["cached"]
    assert not api_client.post(
        "/api/investigate", json={**QUESTION, "retrieval": {"mode": "dense"}}
    ).json()["cached"]
    assert api_client.post("/api/investigate", json={"question": " "}).status_code == 422


def test_no_provider_and_rate_limit(api_client):
    container = api_client.app.state.container
    container.llm = None
    assert api_client.post("/api/investigate", json=QUESTION).status_code == 503
    assert api_client.post("/api/investigate/stream", json=QUESTION).status_code == 503
    assert api_client.post("/api/search", json={"query": "hello"}).status_code == 200
    api_client.app.state.settings.rate_limit_per_minute = 1
    api_client.app.state.limiter.buckets.clear()
    api_client.post("/api/investigate", json=QUESTION)
    response = api_client.post("/api/investigate/stream", json=QUESTION)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_stream_error_saved(api_client, monkeypatch):
    def failing(*args, **kwargs):
        raise LLMError("Provider unavailable")
        yield

    monkeypatch.setattr(api_client.app.state.container.investigator, "investigate_stream", failing)
    response = api_client.post("/api/investigate/stream", json=QUESTION)
    assert response.text.startswith("event: error\n")
    assert api_client.get("/api/traces").json()[0]["error"]


def test_heartbeat_and_missing_final(api_client, monkeypatch):
    import asyncio

    from app.agent.engine import AgentEvent

    original_wait = asyncio.wait
    emitted = False

    async def waiting(tasks, **kwargs):
        nonlocal emitted
        if not emitted:
            emitted = True
            return set(), tasks
        return await original_wait(tasks, **kwargs)

    monkeypatch.setattr("app.api.routes.investigate.asyncio.wait", waiting)
    monkeypatch.setattr(
        api_client.app.state.container.investigator,
        "investigate_stream",
        lambda *args: iter([AgentEvent(event="plan", data={})]),
    )
    response = api_client.post("/api/investigate/stream", json=QUESTION)
    assert ": heartbeat\n\n" in response.text
    assert response.text.rstrip().split("\n\n")[-1].startswith("event: error")
    assert api_client.get("/api/traces").json()[0]["error"]


def test_json_error_is_traced(api_client, monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(
        api_client.app.state.container.investigator,
        "investigate",
        Mock(side_effect=LLMError("Provider failed")),
    )
    assert api_client.post("/api/investigate", json=QUESTION).status_code == 502
    assert api_client.get("/api/traces").json()[0]["error"] == "Provider failed"


def test_registry_mutation_invalidates_cache(api_client):
    seed(api_client)
    api_client.post("/api/investigate", json=QUESTION)
    assert api_client.post("/api/investigate", json=QUESTION).json()["cached"]
    api_client.app.state.container.pipeline.ingest_records(
        [
            {
                "doc_id": "external",
                "text": "New externally indexed facts",
                "metadata": {"origin": "seed"},
            }
        ]
    )
    assert not api_client.post("/api/investigate", json=QUESTION).json()["cached"]
