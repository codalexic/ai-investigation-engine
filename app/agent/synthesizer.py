from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.prompts import SYNTHESIZER
from app.agent.textnorm import normalized_deltas
from app.core.errors import LLMError
from app.llm.client import LLMClient
from app.llm.jsonutil import extract_json
from app.llm.types import Message


class Claim(BaseModel):
    text: str
    evidence: list[str] = Field(default_factory=list)
    kind: Literal["factual", "citation", "excluded"] = "factual"
    support_score: float = 0
    supported: bool = False
    support_method: Literal["nli", "grounding"] | None = None
    grounding_score: float = 0


class Contradiction(BaseModel):
    description: str
    evidence: list[str] = Field(default_factory=list)
    resolution: str | None = None


class AnswerMetadata(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    insufficient_information: bool = False
    missing: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class Synthesizer:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.metadata = AnswerMetadata()
        self.answer = ""

    def stream(self, question: str, evidence: str) -> Iterator[str]:
        self.answer = ""
        yield from normalized_deltas(self._stream(question, evidence))
        self.answer = "".join(normalized_deltas([self.answer]))

    def _stream(self, question: str, evidence: str) -> Iterator[str]:
        messages = [
            Message(role="system", content=SYNTHESIZER),
            Message(role="user", content=question + "\n" + evidence),
        ]
        pending, metadata, in_meta = "", "", False
        marker = "<meta>"
        for delta in self.llm.stream(messages):
            if in_meta:
                metadata += delta
                continue
            pending += delta
            index = pending.find(marker)
            if index >= 0:
                text = pending[:index]
                self.answer += text
                if text:
                    yield text
                metadata = pending[index + len(marker) :]
                pending, in_meta = "", True
            else:
                keep = 0
                for length in range(1, len(marker)):
                    if pending.endswith(marker[:length]):
                        keep = length
                text = pending[:-keep] if keep else pending
                pending = pending[-keep:] if keep else ""
                self.answer += text
                if text:
                    yield text
        if pending:
            self.answer += pending
            yield pending
        try:
            self.metadata = AnswerMetadata.model_validate(extract_json(metadata))
        except (LLMError, ValidationError):
            response = self.llm.chat(
                [
                    *messages,
                    Message(role="assistant", content=self.answer),
                    Message(
                        role="user",
                        content="Repair the metadata as JSON only. Original metadata: " + metadata,
                    ),
                ],
                json_mode=True,
            )
            try:
                self.metadata = AnswerMetadata.model_validate(extract_json(response.content))
            except ValidationError as exc:
                raise LLMError("Invalid repaired answer metadata") from exc
