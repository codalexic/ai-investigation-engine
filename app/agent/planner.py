from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.prompts import PLANNER
from app.core.logging import get_logger
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
            return Plan.model_validate(_coerce(extract_json(response.content)))
        except (ValueError, ValidationError) as exc:
            # The plan only steers retrieval; a malformed one must not sink the investigation.
            get_logger(__name__).warning("plan_invalid error=%s", str(exc)[:200])
            return Plan(entities=entities)


def _coerce(raw: object) -> dict:
    """Repair common model deviations: extra sub-questions, scalar entities, bad dates."""
    if not isinstance(raw, dict):
        raise ValueError("plan is not an object")
    plan = dict(raw)
    if plan.get("complexity") not in ("simple", "multi_hop"):
        plan.pop("complexity", None)
    questions = plan.get("sub_questions") or []
    plan["sub_questions"] = [str(q) for q in questions if str(q).strip()][:4]
    entities = plan.get("entities")
    if isinstance(entities, dict):
        plan["entities"] = {
            str(k): [str(v) for v in (vs if isinstance(vs, list) else [vs]) if v]
            for k, vs in entities.items()
        }
    elif not isinstance(entities, list):
        plan["entities"] = {}
    window = plan.get("time_range")
    if window is not None:
        try:
            TimeRange.model_validate(window)
        except ValidationError:
            plan["time_range"] = None
    return plan
