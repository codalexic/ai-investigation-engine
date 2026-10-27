from collections.abc import Iterator
from time import perf_counter
from typing import Any

from app.agent.planner import Plan
from app.agent.prompts import INVESTIGATOR
from app.agent.tools import TOOL_SPECS, InvestigationTools
from app.core.config import Settings
from app.ingest.metadata import extract_entities
from app.llm.client import LLMClient
from app.llm.types import Message


class Investigator:
    def __init__(self, llm: LLMClient, tools: InvestigationTools, settings: Settings) -> None:
        self.llm, self.tools, self.settings = llm, tools, settings

    def run(
        self, question: str, plan: Plan, trace: list[dict[str, Any]]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        calls = 0
        entities = (
            plan.entities
            if isinstance(plan.entities, dict)
            else extract_entities(" ".join(plan.entities))
        )
        hints = {
            k: entities[k] for k in ("services", "change_ids", "incident_ids") if entities.get(k)
        }
        if plan.time_range:
            start, end = plan.time_range.from_, plan.time_range.to
            if start or end:
                self.tools.date_range = (start or end, end or start)
        for query in dict.fromkeys([question, *plan.sub_questions]):
            if calls >= self.settings.agent_max_tool_calls:
                break
            args = {"query": query}
            started = perf_counter()
            yield "tool_call", {"name": "search_documents", "arguments": args}
            result = self.tools.execute("search_documents", args)
            trace.append(
                {
                    "tool": "search_documents",
                    "arguments": args,
                    "result": result,
                    "latency_ms": (perf_counter() - started) * 1000,
                }
            )
            yield "tool_result", {"name": "search_documents", "content": result}
            calls += 1
        if hints and calls < self.settings.agent_max_tool_calls:
            args = {"query": question, "entity_should": hints}
            yield "tool_call", {"name": "search_documents", "arguments": args}
            started = perf_counter()
            chunks = self.tools.retriever.search(
                question,
                config=self.tools.config,
                filters=self.tools.filters.model_copy(update={"entity_should": hints}),
                date_range=self.tools.date_range,
            ).chunks
            result = self.tools._summary(chunks, "search_documents", question)
            trace.append(
                {
                    "tool": "search_documents",
                    "arguments": args,
                    "result": result,
                    "latency_ms": (perf_counter() - started) * 1000,
                }
            )
            yield "tool_result", {"name": "search_documents", "content": result}
            calls += 1
        messages = [
            Message(role="system", content=INVESTIGATOR),
            Message(
                role="user",
                content=question
                + "\n"
                + self.tools.evidence.render(self.settings.llm_context_budget_tokens),
            ),
        ]
        for step in range(self.settings.agent_max_steps):
            if calls >= self.settings.agent_max_tool_calls:
                break
            started = perf_counter()
            response = self.llm.chat(messages, tools=TOOL_SPECS)
            trace.append(
                {
                    "step": step,
                    "provider": response.provider,
                    "latency_ms": (perf_counter() - started) * 1000,
                }
            )
            messages.append(
                Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                tool_started = perf_counter()
                if calls < self.settings.agent_max_tool_calls:
                    yield "tool_call", call.model_dump()
                    result = self.tools.execute(call.name, call.arguments)
                    calls += 1
                    yield "tool_result", {"id": call.id, "name": call.name, "content": result}
                else:
                    result = "Tool error: investigation tool budget exhausted"
                messages.append(Message(role="tool", tool_call_id=call.id, content=result))
                trace.append(
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "result": result,
                        "latency_ms": (perf_counter() - tool_started) * 1000,
                    }
                )
