import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from time import perf_counter
from typing import Annotated, Any

from anyio import CancelScope
from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.agent.engine import AgentEvent, InvestigationResult
from app.api.schemas import InvestigationRequest
from app.container import Container, get_container
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger

router = APIRouter(prefix="/api/investigate")
Dependency = Annotated[Container, Depends(get_container)]


def prepare(
    body: InvestigationRequest, request: Request, container: Container
) -> tuple[str, InvestigationResult | None, dict[str, Any]]:
    if container.llm is None or container.investigator is None:
        raise ServiceUnavailableError(
            "No LLM provider configured. Configure a provider API key to investigate; "
            "search remains available."
        )
    config = container.retriever.config.model_dump()
    if body.retrieval:
        config.update(body.retrieval.model_dump(exclude_unset=True))
    key = request.app.state.queries.key(
        body.question,
        body.filters.model_dump(mode="json") if body.filters else {},
        config,
        container.settings,
    )
    return key, request.app.state.queries.get(key), config


def finish(result: InvestigationResult, key: str, request: Request, container: Container) -> None:
    request.app.state.queries.save(result, key, container.settings.answer_cache_ttl_s)
    metrics = request.app.state.metrics
    if result.cached:
        metrics.cache_hits.labels("answer").inc()
    else:
        metrics.investigations.observe(result.timings_ms.get("total", 0) / 1000)
        if result.abstained:
            metrics.abstentions.inc()


@router.post("", response_model=InvestigationResult)
def investigate(
    body: InvestigationRequest, request: Request, container: Dependency
) -> InvestigationResult:
    key, cached, config = prepare(body, request, container)
    started = perf_counter()
    try:
        result = cached or container.investigator.investigate(body.question, body.filters, config)
    except AppError as exc:
        result = InvestigationResult(
            question=body.question,
            error=str(exc),
            timings_ms={"total": (perf_counter() - started) * 1000},
        )
        finish(result, key, request, container)
        raise
    finish(result, key, request, container)
    return result


def frame(event: AgentEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(jsonable_encoder(event.data))}\n\n"


def next_event(iterator: Iterator[AgentEvent]) -> AgentEvent | None:
    return next(iterator, None)


@router.post("/stream")
async def stream(
    body: InvestigationRequest, request: Request, container: Dependency
) -> StreamingResponse:
    key, cached, config = await run_in_threadpool(prepare, body, request, container)

    async def events() -> AsyncIterator[str]:
        started = perf_counter()
        saved = False
        if cached:
            await run_in_threadpool(finish, cached, key, request, container)
            yield frame(AgentEvent(event="final", data=cached))
            return
        iterator = container.investigator.investigate_stream(body.question, body.filters, config)
        pending = None
        try:
            while True:
                pending = asyncio.create_task(run_in_threadpool(next_event, iterator))
                while not pending.done():
                    done, _ = await asyncio.wait({pending}, timeout=15)
                    if not done:
                        yield ": heartbeat\n\n"
                event = pending.result()
                if event is None:
                    raise ServiceUnavailableError("Investigation ended without a final result")
                if event.event == "final":
                    await run_in_threadpool(finish, event.data, key, request, container)
                    saved = True
                    yield frame(event)
                    break
                if event.event == "error":
                    final_event = await run_in_threadpool(next_event, iterator)
                    result = (
                        final_event.data
                        if final_event and final_event.event == "final"
                        else InvestigationResult(
                            question=body.question,
                            error=str(event.data),
                            timings_ms={"total": (perf_counter() - started) * 1000},
                        )
                    )
                    await run_in_threadpool(finish, result, key, request, container)
                    saved = True
                    yield frame(event)
                    break
                yield frame(event)
        except AppError as exc:
            get_logger(__name__).warning("stream_failed", extra={"error_type": type(exc).__name__})
            result = InvestigationResult(
                question=body.question,
                error=str(exc),
                timings_ms={"total": (perf_counter() - started) * 1000},
            )
            await run_in_threadpool(finish, result, key, request, container)
            saved = True
            yield frame(AgentEvent(event="error", data={"error": str(exc)}))
        finally:
            with CancelScope(shield=True):
                if pending and not pending.done():
                    await pending
                close = getattr(iterator, "close", None)
                if close:
                    close()
                if not saved:
                    result = InvestigationResult(
                        question=body.question,
                        error="Client disconnected before completion",
                        timings_ms={"total": (perf_counter() - started) * 1000},
                    )
                    await run_in_threadpool(finish, result, key, request, container)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
