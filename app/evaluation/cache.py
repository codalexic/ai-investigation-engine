from collections.abc import Iterator
from typing import Any

from sqlalchemy.engine import Engine

from app.llm.cache import CachedClient
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, Message


class _StreamAdapter:
    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", "") + ":stream"
        self.temperature = getattr(inner, "temperature", None)
        self.max_tokens = getattr(inner, "max_tokens", None)

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        text = "".join(self.inner.stream(messages, **kwargs))
        response = getattr(self.inner, "last_response", LLMResponse())
        return response.model_copy(update={"content": text})


class EvaluationCachedClient(CachedClient):
    def __init__(self, inner: LLMClient, engine: Engine) -> None:
        super().__init__(inner, engine)
        self.stream_cache = CachedClient(_StreamAdapter(inner), engine)

    def stream(self, messages: list[Message], **kwargs: Any) -> Iterator[str]:
        self.last_response = self.stream_cache.chat(messages, **kwargs)
        yield self.last_response.content
