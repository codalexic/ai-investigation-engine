from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.prompts import PLANNER
from app.core.errors import LLMError
from app.ingest.metadata import extract_entities
from app.llm.client import LLMClient
from app.llm.jsonutil import extract_json
from app.llm.types import Message


class TimeRange(BaseModel):
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None


class Plan(BaseModel):
    complexity: Literal["simple", "multi_hop"] = "simple"
    sub_questions: list[str] = Field(default_factory=list, max_length=4)
    entities: dict[str, list[str]] | list[str] = Field(default_factory=dict)
    time_range: TimeRange | None = None


class Planner:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def plan(self, question: str) -> Plan:
        entities = extract_entities(question)
        count = sum(len(v) for k, v in entities.items() if k != "dates")
        if (
            len(question.split()) <= 12
            and count == 1
            and not any(
                word in question.lower().split() for word in ("compare", "and", "versus", "between")
            )
        ):
            return Plan(entities=entities)
        response = self.llm.chat(
            [Message(role="system", content=PLANNER), Message(role="user", content=question)],
            json_mode=True,
        )
        try:
            return Plan.model_validate(extract_json(response.content))
        except ValidationError as exc:
            raise LLMError("Invalid investigation plan") from exc
