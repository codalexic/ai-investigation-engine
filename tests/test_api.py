import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import __version__
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
from app.core.logging import request_id


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "app_env": "local"}


def test_request_id_propagation(client: TestClient) -> None:
    @client.app.get("/request-context")
    def context() -> dict[str, str]:
        return {"request_id": request_id.get()}

    response = client.get("/request-context", headers={"X-Request-ID": "test-request"})
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {"request_id": "test-request"}
    assert request_id.get() == "-"
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert str(UUID(first)) == first
    assert first != second


@pytest.mark.parametrize(
    ("error_class", "status"),
    [
        (AppError, 500),
        (DocumentNotFoundError, 404),
        (UnsupportedFormatError, 415),
        (IngestionError, 500),
        (RetrievalError, 500),
        (LLMError, 502),
        (LLMRateLimitError, 429),
        (ConfigurationError, 500),
    ],
)
def test_error_mapping(client: TestClient, error_class: type[AppError], status: int) -> None:
    @client.app.get("/error")
    def failing_route() -> None:
        raise error_class("test failure")

    response = client.get("/error", headers={"X-Request-ID": "error-request"})
    assert response.status_code == status
    assert response.json() == {"error": {"type": error_class.__name__, "message": "test failure"}}
    assert response.headers["X-Request-ID"] == "error-request"


def test_context_reset_after_unhandled_error(client: TestClient) -> None:
    @client.app.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError("unexpected failure")

    with pytest.raises(RuntimeError, match="unexpected failure"):
        client.get("/unexpected")
    assert request_id.get() == "-"


def test_request_log(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.main"):
        client.get("/health", headers={"X-Request-ID": "logged-request"})
    record = next(record for record in caplog.records if record.message == "request_completed")
    assert record.method == "GET"
    assert record.path == "/health"
    assert record.status == 200
    assert record.latency_ms >= 0
    assert record.request_id == "logged-request"
