from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.core.config import get_settings
from app.core.errors import (
    AppError,
    ConfigurationError,
    DocumentNotFoundError,
    IngestionError,
    LLMError,
    LLMRateLimitError,
    RetrievalError,
    UnsupportedFormatError,
)
from app.core.logging import configure_logging, get_logger, request_id

logger = get_logger(__name__)
ERROR_STATUS = {
    AppError: 500,
    DocumentNotFoundError: 404,
    UnsupportedFormatError: 415,
    IngestionError: 500,
    RetrievalError: 500,
    LLMError: 502,
    LLMRateLimitError: 429,
    ConfigurationError: 500,
}


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
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
            request_id.reset(token)


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    status = next(ERROR_STATUS[cls] for cls in type(exc).__mro__ if cls in ERROR_STATUS)
    return JSONResponse(
        status_code=status,
        content={"error": {"type": type(exc).__name__, "message": str(exc)}},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title="AI Investigation Engine", version=__version__)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_exception_handler(AppError, handle_app_error)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "app_env": settings.app_env}

    return application


app = create_app()
