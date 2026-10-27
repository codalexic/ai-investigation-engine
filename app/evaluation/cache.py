from collections.abc import Iterator
from typing import Any

from sqlalchemy.engine import Engine

from app.llm.cache import CachedClient
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, Message, StreamResult


class _StreamAdapter:
    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", "") + ":stream"
        self.temperature = getattr(inner, "temperature", None)
        self.max_tokens = getattr(inner, "max_tokens", None)

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        stream = self.inner.stream(messages, **kwargs)
        text = "".join(stream)
        response = getattr(stream, "response", LLMResponse())
        return response.model_copy(update={"content": text})


class EvaluationCachedClient(CachedClient):
    def __init__(self, inner: LLMClient, engine: Engine) -> None:
        super().__init__(inner, engine)
        self.stream_cache = CachedClient(_StreamAdapter(inner), engine)

    def stream(self, messages: list[Message], **kwargs: Any) -> StreamResult:
        return StreamResult(lambda result: self._stream(messages, result, **kwargs))

    def _stream(
        self, messages: list[Message], result: StreamResult, **kwargs: Any
    ) -> Iterator[str]:
        result.response = self.stream_cache.chat(messages, **kwargs)
        yield result.response.content
