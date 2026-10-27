from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text

from app.api.routes.documents import origin_expression
from app.api.schemas import StatsResponse, TraceResponse
from app.container import Container, get_container
from app.core.errors import DocumentNotFoundError, ServiceUnavailableError
from app.ingest.registry import DocumentRecord
from app.llm.cache import CachedClient

router = APIRouter()
Dependency = Annotated[Container, Depends(get_container)]


@router.get("/api/stats", response_model=StatsResponse)
def stats(request: Request, container: Dependency) -> dict[str, Any]:
    with container.registry.session() as session:

        def grouped(column: Any) -> dict[str, int]:
            rows = session.execute(
                select(column, func.count())
                .where(DocumentRecord.status == "active")
                .group_by(column)
            )
            return {str(key): count for key, count in rows}

        by_type = grouped(DocumentRecord.doc_type)
        documents = {
            "total": sum(by_type.values()),
            "by_doc_type": by_type,
            "by_source": grouped(DocumentRecord.source),
            "by_dataset": grouped(
                func.coalesce(DocumentRecord.extra["dataset"].as_string(), "unknown")
            ),
            "by_origin": grouped(origin_expression()),
        }
        cache_entries = session.scalar(
            select(func.count()).select_from(request.app.state.queries.cache)
        )
        llm_entries = (
            session.scalar(select(func.count()).select_from(container.llm.table))
            if isinstance(container.llm, CachedClient)
            else 0
        )
    return {
        "documents": documents,
        "chunks": container.store.count(),
        "collection": container.store.collection,
        "embedding_model": container.settings.embedding_model,
        "chunk_strategy": container.settings.chunk_strategy,
        "llm_providers": [
            p
            for p in container.settings.llm_provider_order
            if getattr(container.settings, f"{p}_api_key", None)
        ],
        "cache": {
            "answer_entries": cache_entries,
            "llm_entries": llm_entries,
            "llm_hits": request.app.state.metrics.cache_hits.labels("llm")._value.get(),
            "answer_hits": request.app.state.metrics.cache_hits.labels("answer")._value.get(),
        },
    }


@router.get("/api/traces", response_model=list[TraceResponse])
def traces(request: Request, limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
    return request.app.state.queries.traces(limit)


@router.get("/api/traces/{identifier}", response_model=TraceResponse)
def trace(identifier: str, request: Request) -> dict[str, Any]:
    rows = request.app.state.queries.traces(identifier=identifier)
    if not rows:
        raise DocumentNotFoundError(identifier)
    return rows[0]


@router.get("/ready")
def ready(container: Dependency) -> dict[str, str]:
    try:
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        container.store.count()
    except Exception as exc:
        raise ServiceUnavailableError("Database or vector store is unavailable") from exc
    return {"status": "ready"}


@router.get("/metrics")
def metrics(request: Request) -> Response:
    return Response(
        generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST
    )
