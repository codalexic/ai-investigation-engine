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
from app.llm.types import LLMResponse, Message, ToolCall, ToolSpec, Usage

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
    assert list(llm.stream(MESSAGES)) == ["hello"]
    assert llm.last_response.usage.completion_tokens == 1


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
    inner = Mock(model="llama-3.3-70b-versatile")
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
    assert tracker.estimated_cost == pytest.approx((59 + 7.9) / 1_000_000)
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
    second.stream.return_value = iter(["ok"])
    second.last_response = LLMResponse(provider="second")
    chain = FallbackClient([first, second])
    assert list(chain.stream(MESSAGES)) == ["ok"]
    assert chain.last_response.provider == "second"


def test_invalid_first_json_is_not_replaced_with_nested_object():
    with pytest.raises(LLMError):
        extract_json('{bad: {"nested":1}}')
