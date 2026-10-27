from collections.abc import Callable, Iterator
from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    latency_ms: float = 0
    cached: bool = False


class StreamResult(Iterator[str]):
    def __init__(self, factory: Callable[["StreamResult"], Iterator[str]]) -> None:
        self.response = LLMResponse()
        self._iterator = factory(self)

    def text_iter(self) -> Iterator[str]:
        return self

    def __iter__(self) -> "StreamResult":
        return self

    def __next__(self) -> str:
        return next(self._iterator)
