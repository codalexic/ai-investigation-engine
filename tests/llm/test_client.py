import json
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import create_engine

from app.core.config import Settings
from app.core.errors import ConfigurationError, LLMError, LLMRateLimitError
from app.llm.accounting import UsageTracker
from app.llm.cache import CachedClient
from app.llm.client import FallbackClient, OpenAICompatibleClient, build_llm
from app.llm.jsonutil import extract_json
from app.llm.tokens import count_tokens, fit_to_budget
from app.llm.types import LLMResponse, Message, StreamResult, ToolCall, ToolSpec, Usage

MESSAGES = [Message(role="user", content="question")]


def client(handler, **kw):
    return OpenAICompatibleClient(
        "test",
        "https://example.test/v1",
        "secret",
        "model",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def payload(content="ok", **kw):
    return {"choices": [{"message": {"content": content, **kw}}], "usage": {"prompt_tokens": 2}}


def test_tools_and_parse():
    def handle(request):
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "search"
        assert body["messages"][0]["tool_calls"][0]["function"]["arguments"] == '{"q": "x"}'
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json=payload(
                tool_calls=[
                    {"id": "1", "function": {"name": "search", "arguments": '{"query":"x"}'}}
                ]
            ),
        )

    llm = client(handle)
    response = llm.chat(
        [
            Message(
                role="assistant", tool_calls=[ToolCall(id="a", name="search", arguments={"q": "x"})]
            )
        ],
        tools=[ToolSpec(name="search", description="search", parameters={})],
        json_mode=True,
    )
    assert response.tool_calls[0].arguments == {"query": "x"}
    assert response.provider == "test" and response.usage.prompt_tokens == 2


@pytest.mark.parametrize("arguments", ["{bad", "[]"])
def test_invalid_arguments(arguments):
    llm = client(
        lambda r: httpx.Response(
            200,
            json=payload(
                tool_calls=[{"id": "1", "function": {"name": "search", "arguments": arguments}}]
            ),
        )
    )
    with pytest.raises(LLMError):
        llm.chat(MESSAGES)


@pytest.mark.parametrize(
    "status,expected_calls,error",
    [(429, 3, LLMRateLimitError), (400, 1, LLMError), (503, 3, LLMError)],
)
def test_retries(status, expected_calls, error):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "0"})

    with pytest.raises(error):
        client(handle, max_retries=2).chat(MESSAGES)
    assert len(calls) == expected_calls


def test_retry_after_then_success():
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=payload())]
    )
    assert client(lambda r: next(responses)).chat(MESSAGES).content == "ok"


def test_stream():
    content = ": heartbeat\n\ndata: " + json.dumps({"choices": [{"delta": {"content": "hello"}}]})
    content += "\n\ndata: " + json.dumps({"choices": [], "usage": {"completion_tokens": 1}})
    content += "\n\ndata: [DONE]\n\n"
    llm = client(lambda r: httpx.Response(200, text=content))
    stream = llm.stream(MESSAGES)
    assert list(stream) == ["hello"]
    assert stream.response.usage.completion_tokens == 1


def test_fallback_and_circuit(monkeypatch):
    a, b = Mock(model="a"), Mock(model="b")
    a.chat.side_effect = LLMError("unavailable")
    b.chat.return_value = LLMResponse(provider="b")
    llm = FallbackClient([a, b])
    for _ in range(4):
        assert llm.chat(MESSAGES).provider == "b"
    assert a.chat.call_count == 3
    monkeypatch.setattr("app.llm.client.monotonic", lambda: llm.open_until[0] + 1)
    a.chat.side_effect = None
    a.chat.return_value = LLMResponse(provider="a")
    assert llm.chat(MESSAGES).provider == "a"
    assert llm.failures[0] == 0


def test_build():
    with pytest.raises(ConfigurationError):
        build_llm(Settings(_env_file=None))
    llm = build_llm(Settings(_env_file=None, groq_api_key="test", llm_cache_enabled=False))
    assert len(llm.clients) == 1
    llm.clients[0].close()


def test_cache_and_accounting():
    inner = Mock(model="openai/gpt-oss-120b")
    inner.chat.return_value = LLMResponse(
        model=inner.model, usage=Usage(prompt_tokens=100, completion_tokens=10)
    )
    engine = create_engine("sqlite:///:memory:")
    llm = CachedClient(inner, engine)
    tracker = UsageTracker()
    first, second = llm.chat(MESSAGES), llm.chat(MESSAGES)
    tracker.record(first)
    tracker.record(second)
    assert not first.cached and second.cached and inner.chat.call_count == 1
    assert tracker.snapshot()["cache_hits"] == 1
    assert tracker.estimated_cost == pytest.approx((15 + 6) / 1_000_000)
    llm.chat(MESSAGES, max_tokens=2)
    assert inner.chat.call_count == 2
    engine.dispose()


@pytest.mark.parametrize(
    "text,expected",
    [
        ('```json\n{"a":1}\n```', {"a": 1}),
        (
            "prefix " + json.dumps({"a": ' } " {', "b": {"c": 2}}) + " suffix",
            {"a": ' } " {', "b": {"c": 2}},
        ),
        ("{} {}", {}),
    ],
)
def test_json(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "[]", "{broken"])
def test_bad_json(text):
    with pytest.raises(LLMError):
        extract_json(text)


def test_tokens():
    assert count_tokens("12345") == 2
    assert fit_to_budget(["12345", "x"], 1) == ["x"]


class InterruptedStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        raise httpx.ReadTimeout("stream interrupted")


def test_interrupted_stream_does_not_retry_or_fallback():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=InterruptedStream())

    primary = client(handle)
    secondary = Mock(model="secondary")
    chain = FallbackClient([primary, secondary])
    stream = chain.stream(MESSAGES)
    assert next(stream) == "partial"
    with pytest.raises(LLMError):
        next(stream)
    assert len(requests) == 1
    secondary.stream.assert_not_called()


def test_stream_fallback_before_any_output():
    first = Mock(model="first")
    first.stream.side_effect = LLMError("down")
    second = Mock(model="second")
    stream = StreamResult(lambda result: iter(["ok"]))
    stream.response = LLMResponse(provider="second")
    second.stream.return_value = stream
    chain = FallbackClient([first, second])
    stream = chain.stream(MESSAGES)
    assert list(stream) == ["ok"]
    assert stream.response.provider == "second"


def test_invalid_first_json_is_not_replaced_with_nested_object():
    with pytest.raises(LLMError):
        extract_json('{bad: {"nested":1}}')


@pytest.mark.parametrize("finish", [False, True])
def test_stream_requires_terminal_marker(finish):
    content = "data: " + json.dumps({"choices": [{"delta": {"content": "partial"}}]}) + "\n\n"
    if finish:
        content += (
            "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}) + "\n\n"
        )
    provider = client(lambda request: httpx.Response(200, text=content))
    fallback = Mock()
    chain = FallbackClient([provider, fallback])
    stream = chain.stream(MESSAGES)
    assert next(stream) == "partial"
    if finish:
        assert list(stream) == []
    else:
        with pytest.raises(LLMError, match="stream ended unexpectedly"):
            list(stream)
    fallback.stream.assert_not_called()


def test_overlapping_stream_accounting_is_per_call():
    from app.api.llm_metrics import MeteredClient
    from app.api.observability import Metrics

    calls = []

    def handle(request):
        number = len(calls) + 1
        calls.append(number)
        text = "data: " + json.dumps({"choices": [{"delta": {"content": str(number)}}]})
        text += "\n\ndata: " + json.dumps({"choices": [], "usage": {"completion_tokens": number}})
        text += "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=text)

    provider = client(handle)
    metrics = Metrics()
    metered = MeteredClient(FallbackClient([provider]), metrics)
    a, b = metered.stream(MESSAGES), metered.stream(MESSAGES)
    assert next(a) == "1"
    assert next(b) == "2"
    list(b)
    list(a)
    assert a.response.usage.completion_tokens == 1
    assert b.response.usage.completion_tokens == 2
    assert metrics.tokens.labels("test", "model", "completion")._value.get() == 3


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("groq", "openai/gpt-oss-20b", {"reasoning_effort": "low", "reasoning_format": "hidden"}),
        ("gemini", "gemini-3.5-flash-lite", {"reasoning_effort": "low"}),
        ("groq", "llama-3.3-70b", {}),
        ("openrouter", "other", {}),
    ],
)
def test_reasoning_capabilities(provider, model, expected):
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=payload())

    llm = OpenAICompatibleClient(
        provider, "https://example.test", "key", model, transport=httpx.MockTransport(handle)
    )
    llm.chat(MESSAGES)
    assert {k: v for k, v in bodies[0].items() if k.startswith("reasoning_")} == expected
    llm.close()


@pytest.mark.parametrize("reset,seconds", [("3.57s", 3.57), ("1m2.5s", 62.5)])
def test_header_token_throttle(monkeypatch, reset, seconds):
    monkeypatch.setattr("app.llm.client.monotonic", lambda: 100)
    sleep = Mock()
    monkeypatch.setattr("app.llm.client.sleep", sleep)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=payload(),
            headers={
                "x-ratelimit-remaining-tokens": "5",
                "x-ratelimit-reset-tokens": reset,
                "x-ratelimit-remaining-requests": "10",
                "x-ratelimit-reset-requests": "1h",
            },
        )

    llm = client(handle)
    llm.chat(MESSAGES)
    if seconds > 15:
        with pytest.raises(LLMRateLimitError) as error:
            llm.chat(MESSAGES)
        assert error.value.retry_after == seconds
        assert len(calls) == 1
        sleep.assert_not_called()
    else:
        llm.chat(MESSAGES)
        sleep.assert_called_once_with(pytest.approx(seconds))
    llm.close()


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("streaming", [False, True])
def test_long_retry_after_falls_back(status, streaming):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "60"})

    first = client(handle)
    second = Mock(model="backup")
    second.chat.return_value = LLMResponse(content="backup")
    second.stream.return_value = StreamResult(lambda result: iter(["backup"]))
    chain = FallbackClient([first, second])
    assert (
        "".join(chain.stream(MESSAGES)) if streaming else chain.chat(MESSAGES).content
    ) == "backup"
    assert len(calls) == 1
    first.close()


@pytest.mark.parametrize("status", [404, 503])
def test_judge_model_fallback(status):
    settings = Settings(
        _env_file=None, gemini_api_key="key", llm_provider_order=["gemini"], llm_cache_enabled=False
    )
    chain = build_llm(settings, judge=True)
    models = []

    def handle(request):
        model = json.loads(request.content)["model"]
        models.append(model)
        return httpx.Response(status if model == settings.llm_judge_model else 200, json=payload())

    for item in chain.clients:
        item.http.close()
        item.http = httpx.Client(
            base_url="https://example.test/", transport=httpx.MockTransport(handle)
        )
    assert chain.chat(MESSAGES).content == "ok"
    assert models == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    for item in chain.clients:
        item.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_request_header_throttle(monkeypatch, streaming):
    monkeypatch.setattr("app.llm.client.monotonic", lambda: 100)
    slept = Mock()
    monkeypatch.setattr("app.llm.client.sleep", slept)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=payload(),
            headers={"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "5s"},
        )

    llm = client(handle)
    llm.chat(MESSAGES)
    if streaming:
        # The response body is irrelevant to checking the pre-request wait.
        with pytest.raises(LLMError):
            list(llm.stream(MESSAGES))
    else:
        llm.chat(MESSAGES)
    slept.assert_called_once_with(5)
    assert len(calls) == 2
    llm.close()


def test_preflight_long_reset_uses_next_provider(monkeypatch):
    monkeypatch.setattr("app.llm.client.monotonic", lambda: 100)
    first = client(
        lambda request: httpx.Response(
            200,
            json=payload(),
            headers={"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "1m2.5s"},
        )
    )
    first.chat(MESSAGES)
    backup = Mock(model="backup")
    backup.chat.return_value = LLMResponse(content="backup")
    chain = FallbackClient([first, backup])
    assert chain.chat(MESSAGES).content == "backup"
    assert chain.open_until[0] == 162.5
    first.close()


@pytest.mark.parametrize(
    "model,rates", [("gemini-3.5-flash-lite", (0.10, 0.40)), ("gemini-3.8-flash", (0.30, 2.50))]
)
def test_reference_prices(model, rates):
    tracker = UsageTracker()
    tracker.record(LLMResponse(model=model, usage=Usage(prompt_tokens=100, completion_tokens=20)))
    assert tracker.estimated_cost == pytest.approx((100 * rates[0] + 20 * rates[1]) / 1_000_000)


def test_tool_call_extra_content_round_trip():
    signature = {"google": {"thought_signature": "sig"}}
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            call = {
                "id": "c1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "x"}'},
                "extra_content": signature,
            }
            return httpx.Response(200, json=payload(None, tool_calls=[call]))
        assert body["messages"][-2]["tool_calls"][0]["extra_content"] == signature
        return httpx.Response(200, json=payload("done"))

    llm = client(handle)
    first = llm.chat(MESSAGES)
    assert first.tool_calls[0].extra_content == signature
    follow_up = [
        *MESSAGES,
        Message(role="assistant", tool_calls=first.tool_calls),
        Message(role="tool", content="result", tool_call_id="c1"),
    ]
    assert llm.chat(follow_up).content == "done"
