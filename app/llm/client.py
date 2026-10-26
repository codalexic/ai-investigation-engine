import json
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic, perf_counter
from typing import Any, Protocol

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.core.errors import ConfigurationError, LLMError, LLMRateLimitError
from app.llm.types import LLMResponse, Message, StreamResult, ToolCall, ToolSpec, Usage


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...
    def stream(self, messages: list[Message], **kwargs: Any) -> StreamResult: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> None:
        self.provider, self.model = provider, model
        self.temperature, self.max_tokens = temperature, max_tokens
        self.max_retries = max_retries
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def _body(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        serialized = []
        for message in messages:
            item = message.model_dump(exclude_none=True, exclude={"tool_calls"})
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {"name": t.name, "arguments": json.dumps(t.arguments)},
                    }
                    for t in message.tool_calls
                ]
            serialized.append(item)
        body = {
            "model": self.model,
            "messages": serialized,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t.model_dump()} for t in tools]
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    @staticmethod
    def _retryable(exc: BaseException) -> bool:
        return isinstance(exc, httpx.TimeoutException) or (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code in {429, 500, 502, 503, 504}
        )

    def _retry(self) -> Retrying:
        default = wait_exponential_jitter(initial=0.1, max=8)

        def delay(state: RetryCallState) -> float:
            exc = state.outcome.exception()
            if isinstance(exc, httpx.HTTPStatusError):
                value = exc.response.headers.get("Retry-After")
                if value:
                    try:
                        return max(0, float(value))
                    except ValueError:
                        try:
                            return max(
                                0,
                                (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(),
                            )
                        except (ValueError, TypeError):
                            return default(state)
            return default(state)

        return Retrying(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=delay,
            retry=retry_if_exception(self._retryable),
            reraise=True,
        )

    def _error(self, exc: Exception) -> LLMError:
        if isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 429:
                return LLMRateLimitError(f"{self.provider}: rate limit exhausted")
            return LLMError(f"{self.provider}: HTTP {exc.response.status_code}")
        return LLMError(
            f"{self.provider}: invalid response or transport failure ({type(exc).__name__})"
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        started = perf_counter()
        try:
            for attempt in self._retry():
                with attempt:
                    response = self.http.post(
                        "chat/completions",
                        json=self._body(messages, tools, json_mode, temperature, max_tokens),
                    )
                    response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            calls = []
            for call in message.get("tool_calls", []):
                try:
                    args = json.loads(call["function"]["arguments"])
                except (ValueError, TypeError) as exc:
                    raise LLMError(
                        f"{self.provider}: invalid arguments for tool "
                        f"{call['function'].get('name', '<unknown>')}"
                    ) from exc
                if not isinstance(args, dict):
                    raise LLMError(f"{self.provider}: tool arguments must be an object")
                calls.append(ToolCall(id=call["id"], name=call["function"]["name"], arguments=args))
            return LLMResponse(
                content=message.get("content") or "",
                tool_calls=calls,
                usage=Usage.model_validate(data.get("usage", {})),
                model=data.get("model", self.model),
                provider=self.provider,
                latency_ms=(perf_counter() - started) * 1000,
            )
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            raise self._error(exc) from exc

    def stream(self, messages: list[Message], **kwargs: Any) -> StreamResult:
        return StreamResult(lambda result: self._stream(messages, result, **kwargs))

    def _stream(
        self, messages: list[Message], result: StreamResult, **kwargs: Any
    ) -> Iterator[str]:
        emitted = False
        terminal = False
        result.response = LLMResponse(model=self.model, provider=self.provider)
        try:
            for attempt in self._retry():
                with (
                    attempt,
                    self.http.stream(
                        "POST",
                        "chat/completions",
                        json={
                            **self._body(messages, **kwargs),
                            "stream": True,
                            "stream_options": {"include_usage": True},
                        },
                    ) as response,
                ):
                    response.raise_for_status()
                    try:
                        for line in response.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                return
                            data = json.loads(payload)
                            if data.get("usage"):
                                result.response = LLMResponse(
                                    usage=Usage.model_validate(data["usage"]),
                                    model=data.get("model", self.model),
                                    provider=self.provider,
                                )
                            for choice in data.get("choices", []):
                                terminal = terminal or choice.get("finish_reason") is not None
                                text = choice.get("delta", {}).get("content")
                                if text:
                                    emitted = True
                                    yield text
                        if not terminal:
                            raise LLMError("stream ended unexpectedly")
                        return
                    except httpx.TimeoutException as exc:
                        if emitted:
                            raise LLMError(f"{self.provider}: interrupted stream") from exc
                        raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if emitted:
                raise LLMError(f"{self.provider}: interrupted stream") from exc
            raise self._error(exc) from exc

    def close(self) -> None:
        self.http.close()


class FallbackClient:
    def __init__(self, clients: list[LLMClient]) -> None:
        self.clients = clients
        self.temperature = getattr(clients[0], "temperature", 0.1) if clients else 0.1
        self.max_tokens = getattr(clients[0], "max_tokens", 1200) if clients else 1200
        self.failures = [0] * len(clients)
        self.open_until = [0.0] * len(clients)
        self.model = getattr(clients[0], "model", "") if clients else ""

    def _run(
        self,
        method: str,
        messages: list[Message],
        kwargs: dict[str, Any],
        result: StreamResult | None = None,
    ) -> Iterator[LLMResponse | str]:
        error = LLMError("All provider circuits are open")
        emitted = False
        for index, client in enumerate(self.clients):
            if monotonic() < self.open_until[index]:
                continue
            try:
                value = getattr(client, method)(messages, **kwargs)
                if method == "stream":
                    for delta in value:
                        emitted = True
                        yield delta
                    if result is not None:
                        result.response = getattr(value, "response", LLMResponse())
                else:
                    self.failures[index] = 0
                    yield value
                self.failures[index] = 0
                return
            except LLMError as exc:
                error = exc
                self.failures[index] += 1
                if self.failures[index] >= 3:
                    self.open_until[index] = monotonic() + 60
                if emitted:
                    raise
        raise error

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return next(
            self._run(
                "chat",
                messages,
                dict(
                    tools=tools, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens
                ),
            )
        )

    def stream(self, messages: list[Message], **kwargs: Any) -> StreamResult:
        return StreamResult(lambda result: self._run("stream", messages, kwargs, result))


def build_llm(settings: Settings, model_override: str | None = None) -> LLMClient:
    clients = []
    for provider in settings.llm_provider_order:
        if provider not in {"groq", "gemini", "openrouter"}:
            raise ConfigurationError(f"Unknown LLM provider: {provider}")
        key = getattr(settings, f"{provider}_api_key")
        if not key:
            continue
        model = {
            "groq": settings.llm_primary_model,
            "gemini": settings.llm_fallback_model,
            "openrouter": settings.openrouter_model,
        }[provider]
        clients.append(
            OpenAICompatibleClient(
                provider,
                getattr(settings, f"{provider}_base_url"),
                key.get_secret_value(),
                model_override or model,
                settings.request_timeout_s,
                settings.llm_max_retries,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_output_tokens,
            )
        )
    if not clients:
        raise ConfigurationError("No LLM provider credentials configured")
    chain = FallbackClient(clients)
    if settings.llm_cache_enabled:
        from sqlalchemy import create_engine

        from app.llm.cache import CachedClient

        return CachedClient(chain, create_engine(settings.database_url))
    return chain
