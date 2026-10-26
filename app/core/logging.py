import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import get_settings

request_id: ContextVar[str] = ContextVar("request_id", default="-")
_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class StructuredFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool) -> None:
        super().__init__()
        self.json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id.get()),
        }
        fields.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_FIELDS})
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        if self.json_output:
            return json.dumps(fields, default=str)
        return " ".join(f"{key}={json.dumps(value, default=str)}" for key, value in fields.items())


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(StructuredFormatter(json_output=get_settings().app_env == "prod"))
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
