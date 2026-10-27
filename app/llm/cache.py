import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import ConfigurationError, LLMError
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, Message, ToolSpec


class CachedClient:
    def __init__(self, inner: LLMClient, engine: Engine) -> None:
        self.inner, self.engine = inner, engine
        self.model = getattr(inner, "model", "")
        self.table = Table(
            "llm_cache",
            MetaData(),
            Column("key", String, primary_key=True),
            Column("response", JSON),
            Column("created_at", DateTime),
        )
        try:
            self.table.create(engine, checkfirst=True)
        except SQLAlchemyError as exc:
            raise ConfigurationError("Unable to initialize the LLM cache") from exc

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        effective_temperature = (
            temperature if temperature is not None else getattr(self.inner, "temperature", None)
        )
        effective_max_tokens = (
            max_tokens if max_tokens is not None else getattr(self.inner, "max_tokens", None)
        )
        if not isinstance(effective_temperature, (int, float)):
            effective_temperature = None
        if not isinstance(effective_max_tokens, int):
            effective_max_tokens = None
        key = hashlib.sha256(
            json.dumps(
                [
                    self.model.split("/")[-1],
                    [m.model_dump() for m in messages],
                    [t.model_dump() for t in tools or []],
                    json_mode,
                    effective_temperature,
                    effective_max_tokens,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    select(self.table.c.response).where(self.table.c.key == key)
                ).first()
        except SQLAlchemyError as exc:
            raise LLMError("Unable to read the LLM cache") from exc
        if row:
            try:
                return LLMResponse.model_validate(row[0]).model_copy(
                    update={"cached": True, "latency_ms": 0}
                )
            except ValueError as exc:
                raise LLMError("Invalid stored LLM cache response") from exc
        response = self.inner.chat(
            messages,
            tools=tools,
            json_mode=json_mode,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.table.insert().values(
                        key=key, response=response.model_dump(), created_at=datetime.now(UTC)
                    )
                )
        except IntegrityError as exc:
            try:
                with self.engine.connect() as conn:
                    exists = conn.execute(
                        select(self.table.c.key).where(self.table.c.key == key)
                    ).first()
            except SQLAlchemyError as read_exc:
                raise LLMError("Unable to resolve concurrent LLM cache write") from read_exc
            if exists is None:
                raise LLMError("Unable to insert LLM cache response") from exc
        except SQLAlchemyError as exc:
            raise LLMError("Unable to write the LLM cache") from exc
        return response

    def stream(self, messages: list[Message], **kwargs: Any) -> Iterator[str]:
        yield from self.inner.stream(messages, **kwargs)
        self.last_response = getattr(self.inner, "last_response", LLMResponse())
