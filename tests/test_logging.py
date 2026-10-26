import io
import json
import logging

import pytest

from app.core.logging import (
    RequestContextFilter,
    StructuredFormatter,
    configure_logging,
    get_logger,
    request_id,
)


@pytest.mark.parametrize("environment", ["local", "prod"])
def test_logging_formats(environment: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    root = logging.getLogger()
    previous_handlers = root.handlers[:]
    previous_level = root.level
    stream = io.StringIO()
    monkeypatch.setattr("sys.stderr", stream)
    token = request_id.set("log-request")
    try:
        configure_logging("info")
        get_logger("test.logger").info("request_completed", extra={"status": 200})
        output = stream.getvalue().strip()
        if environment == "prod":
            record = json.loads(output)
            assert record["request_id"] == "log-request"
            assert record["status"] == 200
            assert record["message"] == "request_completed"
        else:
            assert 'request_id="log-request"' in output
            assert "status=200" in output
    finally:
        request_id.reset(token)
        root.handlers = previous_handlers
        root.setLevel(previous_level)


def test_exception_formatting() -> None:
    try:
        raise ValueError("bad value")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "failure", (), sys.exc_info()
        )
    assert RequestContextFilter().filter(record)
    output = json.loads(StructuredFormatter(json_output=True).format(record))
    assert "ValueError: bad value" in output["exception"]
    assert output["request_id"] == "-"
