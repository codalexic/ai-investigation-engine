import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.api.llm_metrics import MeteredClient
from app.api.observability import Metrics, RateLimiter
from app.api.persistence import QueryRepository
from app.api.routes import documents, investigate, search, system
from app.container import Container
from app.core.config import Settings, get_settings
from app.core.errors import (
    AccessDeniedError,
    AppError,
    ConfigurationError,
    DocumentNotFoundError,
    IngestionError,
    InvalidRequestError,
    LLMError,
    LLMRateLimitError,
    RetrievalError,
    ServiceUnavailableError,
    UnsupportedFormatError,
    UploadTooLargeError,
)
from app.core.logging import configure_logging, get_logger, request_id

logger = get_logger(__name__)
ERROR_STATUS = {
    AccessDeniedError: 403,
    UploadTooLargeError: 413,
    InvalidRequestError: 422,
    ServiceUnavailableError: 503,
    AppError: 500,
    DocumentNotFoundError: 404,
    UnsupportedFormatError: 415,
    IngestionError: 500,
    RetrievalError: 500,
    LLMError: 502,
    LLMRateLimitError: 429,
    ConfigurationError: 500,
}


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        response = JSONResponse(
            {
                "error": {
                    "type": "UploadTooLargeError",
                    "message": "Request body exceeds upload limit",
                }
            },
            status_code=413,
        )
        if length > self.limit:
            await response(scope, receive, send)
            return
        messages = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                await response(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def replay() -> Message:
            message = next(iterator, None)
            return message if message is not None else await receive()

        await self.app(scope, replay, send)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        application = scope["app"]
        path = scope["path"]
        incoming_id = Request(scope).headers.get("X-Request-ID") or str(uuid4())
        token = request_id.set(incoming_id)
        started = perf_counter()
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k != b"x-request-id"]
                message["headers"] = [*headers, (b"x-request-id", incoming_id.encode("latin-1"))]
            await send(message)

        try:
            retry = 0
            if path.startswith(("/api/investigate", "/api/search", "/api/documents")):
                group = "investigate" if path.startswith("/api/investigate") else "general"
                capacity = (
                    application.state.settings.rate_limit_per_minute
                    if group == "investigate"
                    else 120
                )
                retry = application.state.limiter.check(
                    (scope.get("client") or ("unknown", 0))[0], group, capacity
                )
            if retry:
                for route in application.state.api_routes:
                    match, _ = route.matches(scope)
                    if match == Match.FULL:
                        scope["route"] = route
                        break
                response = JSONResponse(
                    {"error": {"type": "RateLimitError", "message": "Rate limit exceeded"}},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
                await response(scope, receive, send_with_request_id)
            else:
                await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
            route = scope.get("route")
            template = getattr(route, "path", "unmatched")
            application.state.metrics.requests.labels(template, str(status)).inc()
            application.state.metrics.http_latency.labels(template, str(status)).observe(
                perf_counter() - started
            )
            request_id.reset(token)


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    status = next(ERROR_STATUS[cls] for cls in type(exc).__mro__ if cls in ERROR_STATUS)
    return JSONResponse(
        status_code=status,
        content={"error": {"type": type(exc).__name__, "message": str(exc)}},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if max(settings.web_concurrency, settings.uvicorn_workers) > 1:
            logger.warning(
                "single_worker_required web_concurrency=%s uvicorn_workers=%s",
                settings.web_concurrency,
                settings.uvicorn_workers,
            )
        container = Container.build(settings)
        application.state.container = container
        try:
            application.state.queries = QueryRepository(container.registry)
            container.retriever.observe = lambda stage, seconds: (
                application.state.metrics.retrieval.labels(stage).observe(seconds)
            )
            if container.llm and container.investigator:
                container.investigator.llm = MeteredClient(container.llm, application.state.metrics)
            warmup_task = None
            if settings.warmup if settings.warmup is not None else settings.app_env == "prod":

                async def warm_models() -> None:
                    await asyncio.sleep(0)
                    await asyncio.to_thread(container.warm_models)

                warmup_task = asyncio.create_task(warm_models())
            try:
                yield
            finally:
                if warmup_task is not None:
                    await warmup_task
        finally:
            container.close()

    application = FastAPI(title="AI Investigation Engine", version=__version__, lifespan=lifespan)
    application.state.settings = settings
    application.state.metrics = Metrics()
    application.state.limiter = RateLimiter()
    application.state.api_routes = []
    for router in (documents.router, search.router, investigate.router, system.router):
        application.include_router(router)
        application.state.api_routes.extend(router.routes)
    static = Path(__file__).parents[1] / "ui" / "static"
    application.mount("/static", StaticFiles(directory=static, html=True), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    application.add_middleware(
        RequestBodyLimitMiddleware, limit=(settings.max_upload_mb + 1) * 1024**2
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_exception_handler(AppError, handle_app_error)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "app_env": settings.app_env}

    return application


app = create_app()
