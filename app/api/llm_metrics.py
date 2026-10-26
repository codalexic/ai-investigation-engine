from collections.abc import Iterator
from typing import Any

from app.api.observability import Metrics
from app.llm.accounting import PRICES
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, Message, StreamResult


class MeteredClient:
    def __init__(self, inner: LLMClient, metrics: Metrics) -> None:
        self.inner, self.metrics = inner, metrics

    def record(self, response: LLMResponse) -> None:
        labels = (response.provider, response.model)
        self.metrics.calls.labels(*labels).inc()
        self.metrics.tokens.labels(*labels, "prompt").inc(response.usage.prompt_tokens)
        self.metrics.tokens.labels(*labels, "completion").inc(response.usage.completion_tokens)
        incoming, outgoing = PRICES.get(response.model, (0, 0))
        if response.cached:
            self.metrics.cache_hits.labels("llm").inc()
        else:
            self.metrics.cost.labels(*labels).inc(
                (
                    incoming * response.usage.prompt_tokens
                    + outgoing * response.usage.completion_tokens
                )
                / 1_000_000
            )

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        response = self.inner.chat(messages, **kwargs)
        self.record(response)
        return response

    def stream(self, messages: list[Message], **kwargs: Any) -> StreamResult:
        return StreamResult(lambda result: self._stream(messages, result, **kwargs))

    def _stream(
        self, messages: list[Message], result: StreamResult, **kwargs: Any
    ) -> Iterator[str]:
        stream = self.inner.stream(messages, **kwargs)
        yield from stream
        result.response = getattr(stream, "response", LLMResponse())
        self.record(result.response)
