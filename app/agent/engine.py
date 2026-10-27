from collections.abc import Iterator
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.evidence import EvidenceStore
from app.agent.investigator import Investigator
from app.agent.nli import NliModel
from app.agent.planner import Planner
from app.agent.synthesizer import Claim, Contradiction, Synthesizer
from app.agent.tools import InvestigationTools
from app.agent.verifier import Verifier
from app.core.config import Settings
from app.core.errors import LLMError, LLMRateLimitError, RetrievalError
from app.core.logging import get_logger
from app.llm.accounting import UsageTracker
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, Message
from app.retrieval.hybrid import HybridRetriever, RetrievalConfig
from app.retrieval.store import QdrantStore, QueryFilters


class AgentEvent(BaseModel):
    event: Literal[
        "plan",
        "tool_call",
        "tool_result",
        "evidence",
        "answer_delta",
        "verification",
        "final",
        "error",
    ]
    data: Any

    @property
    def type(self) -> str:
        return self.event


class Citation(BaseModel):
    evidence_id: str
    chunk_id: str
    doc_id: str
    title: str
    source: str
    snippet: str
    text: str = ""
    created_at: str | None = None
    explain: dict[str, Any] = Field(default_factory=dict)


class InvestigationResult(BaseModel):
    question: str
    cached: bool = False
    answer: str = ""
    abstained: bool = True
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    confidence: str = "low"
    trace: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class _TrackedClient:
    def __init__(self, inner: LLMClient, tracker: UsageTracker) -> None:
        self.inner, self.tracker = inner, tracker

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        response = self.inner.chat(messages, **kwargs)
        self.tracker.record(response)
        return response

    def stream(self, messages: list[Message], **kwargs: Any) -> Iterator[str]:
        started = perf_counter()
        yield from self.inner.stream(messages, **kwargs)
        response = getattr(self.inner, "last_response", LLMResponse())
        self.tracker.record(
            response.model_copy(update={"latency_ms": (perf_counter() - started) * 1000})
        )


class InvestigationEngine:
    def __init__(
        self,
        retriever: HybridRetriever,
        store: QdrantStore,
        llm: LLMClient,
        nli: NliModel | None,
        settings: Settings,
    ) -> None:
        self.retriever, self.store, self.llm = retriever, store, llm
        self.nli, self.settings = nli, settings

    def investigate(
        self,
        question: str,
        filters: QueryFilters | None = None,
        retrieval_config: RetrievalConfig | dict[str, Any] | None = None,
        agentic: bool = True,
    ) -> InvestigationResult:
        for event in self.investigate_stream(question, filters, retrieval_config, agentic):
            if event.event == "final":
                return event.data
        raise LLMError("Investigation ended without a final result")

    def investigate_stream(
        self,
        question: str,
        filters: QueryFilters | None = None,
        retrieval_config: RetrievalConfig | dict[str, Any] | None = None,
        agentic: bool = True,
    ) -> Iterator[AgentEvent]:
        started = perf_counter()
        evidence, tracker, trace, timings = EvidenceStore(), UsageTracker(), [], {}
        llm = _TrackedClient(self.llm, tracker)
        result = InvestigationResult(question=question)
        try:
            stage = perf_counter()
            tools = InvestigationTools(
                self.retriever, self.store, evidence, filters, retrieval_config
            )
            if agentic:
                plan = Planner(llm).plan(question)
                timings["plan"] = (perf_counter() - stage) * 1000
                trace.append(
                    {
                        "stage": "plan",
                        "plan": plan.model_dump(mode="json", by_alias=True),
                        "latency_ms": timings["plan"],
                    }
                )
                yield AgentEvent(event="plan", data=plan.model_dump(mode="json", by_alias=True))
                stage = perf_counter()
                for event, data in Investigator(llm, tools, self.settings).run(
                    question, plan, trace
                ):
                    yield AgentEvent(event=event, data=data)
            else:
                chunks = self.retriever.search(
                    question, config=retrieval_config, filters=filters
                ).chunks
                tools._summary(chunks, "search_documents", question)
            timings["investigation"] = (perf_counter() - stage) * 1000
            for key, item in evidence.items.items():
                yield AgentEvent(
                    event="evidence",
                    data={
                        "evidence_id": key,
                        "chunk_id": item.chunk.chunk_id,
                        "doc_id": item.chunk.doc_id,
                    },
                )
            stage = perf_counter()
            synthesizer = Synthesizer(llm)
            for delta in synthesizer.stream(
                question, evidence.render(self.settings.llm_context_budget_tokens)
            ):
                yield AgentEvent(event="answer_delta", data=delta)
            timings["synthesis"] = (perf_counter() - stage) * 1000
            trace.append({"stage": "synthesis", "latency_ms": timings["synthesis"]})
            stage = perf_counter()
            report = Verifier(self.nli, self.settings).verify(
                synthesizer.answer, synthesizer.metadata, evidence
            )
            timings["verification"] = (perf_counter() - stage) * 1000
            trace.append({"stage": "verification", "latency_ms": timings["verification"]})
            yield AgentEvent(event="verification", data=report.model_dump())
            cited = {key for claim in report.metadata.claims for key in claim.evidence}
            cited.update(
                key for conflict in report.metadata.contradictions for key in conflict.evidence
            )
            result = InvestigationResult(
                question=question,
                answer=report.answer,
                abstained=report.abstained,
                claims=report.metadata.claims,
                contradictions=report.metadata.contradictions,
                missing=report.metadata.missing,
                confidence=report.metadata.confidence,
                citations=[
                    Citation(
                        evidence_id=key,
                        chunk_id=evidence.items[key].chunk.chunk_id,
                        doc_id=evidence.items[key].chunk.doc_id,
                        title=str(evidence.items[key].chunk.payload.get("title", "")),
                        source=str(evidence.items[key].chunk.payload.get("source", "")),
                        snippet=evidence.items[key].chunk.text[:300],
                        text=evidence.items[key].chunk.text,
                        created_at=str(evidence.items[key].chunk.payload.get("created_at") or "")
                        or None,
                        explain=evidence.items[key].chunk.explain,
                    )
                    for key in evidence.items
                    if key in cited
                ],
            )
        except LLMRateLimitError:
            raise
        except (LLMError, RetrievalError) as exc:
            get_logger(__name__).warning("investigation_failed error_type=%s", type(exc).__name__)
            result.error = "Investigation failed: a provider or retrieval service was unavailable."
            result.answer = "Insufficient information: the investigation could not be completed."
            result.missing = ["Available evidence and a successful provider response."]
            yield AgentEvent(event="error", data={"error": result.error})
        result.trace, result.usage = trace, tracker.snapshot()
        result.timings_ms = {**timings, "total": (perf_counter() - started) * 1000}
        yield AgentEvent(event="final", data=result)
