import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.agent import prompts
from app.agent.engine import InvestigationResult
from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.ingest.registry import DocumentRegistry


class QueryRepository:
    def __init__(self, registry: DocumentRegistry) -> None:
        self.registry = registry
        metadata = MetaData()
        self.meta = Table(
            "meta", metadata, Column("key", String, primary_key=True), Column("value", Integer)
        )
        self.cache = Table(
            "answer_cache",
            metadata,
            Column("key", String, primary_key=True),
            Column("expires_at", DateTime),
            Column("result", JSON),
        )
        self.logs = Table(
            "query_log",
            metadata,
            Column("id", String, primary_key=True),
            Column("created_at", DateTime),
            Column("question", String),
            Column("abstained", Integer),
            Column("answer_excerpt", String),
            Column("citations_count", Integer),
            Column("contradictions_count", Integer),
            Column("usage", JSON),
            Column("timings", JSON),
            Column("trace", JSON),
            Column("error", String, nullable=True),
        )
        try:
            metadata.create_all(registry.engine)
        except SQLAlchemyError as exc:
            raise ConfigurationError("Unable to initialize query storage") from exc

    def key(
        self,
        question: str,
        filters: dict[str, Any],
        retrieval: dict[str, Any],
        settings: Settings | None = None,
    ) -> str:
        with self.registry.session() as session:
            version = session.scalar(
                select(self.meta.c.value).where(self.meta.c.key == "index_version")
            )
        settings = settings or Settings(_env_file=None)
        fingerprint = {
            k: v
            for k, v in settings.model_dump(mode="json").items()
            if k.startswith(("llm_", "nli_", "agent_", "abstain_"))
            or k in {"openrouter_model", "support_threshold", "contradiction_threshold"}
        }
        fingerprint["prompts"] = hashlib.sha256(
            json.dumps(
                {k: v for k, v in vars(prompts).items() if isinstance(v, str) and k.isupper()},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return hashlib.sha256(
            json.dumps(
                [" ".join(question.lower().split()), filters, retrieval, str(version), fingerprint],
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def get(self, key: str) -> InvestigationResult | None:
        with self.registry.session() as session:
            row = session.execute(
                select(self.cache.c.result).where(
                    self.cache.c.key == key, self.cache.c.expires_at > datetime.now(UTC)
                )
            ).first()
        return (
            InvestigationResult.model_validate(row[0]).model_copy(update={"cached": True})
            if row
            else None
        )

    def save(self, result: InvestigationResult, key: str, ttl: int) -> str:
        identifier = uuid4().hex
        with self.registry.session() as session:
            session.execute(
                self.logs.insert().values(
                    id=identifier,
                    created_at=datetime.now(UTC),
                    question=result.question,
                    abstained=int(result.abstained),
                    answer_excerpt=result.answer[:500],
                    citations_count=len(result.citations),
                    contradictions_count=len(result.contradictions),
                    usage=result.usage,
                    timings=result.timings_ms,
                    trace=result.trace,
                    error=result.error,
                )
            )
            if not result.cached and not result.error and ttl:
                values = {
                    "expires_at": datetime.now(UTC) + timedelta(seconds=ttl),
                    "result": result.model_dump(mode="json"),
                }
                changed = session.execute(
                    self.cache.update().where(self.cache.c.key == key).values(**values)
                )
                if not changed.rowcount:
                    try:
                        with session.begin_nested():
                            session.execute(self.cache.insert().values(key=key, **values))
                    except IntegrityError:
                        session.execute(
                            self.cache.update().where(self.cache.c.key == key).values(**values)
                        )
        return identifier

    def traces(self, limit: int = 20, identifier: str | None = None) -> list[dict[str, Any]]:
        statement = select(self.logs).order_by(self.logs.c.created_at.desc()).limit(limit)
        if identifier:
            statement = statement.where(self.logs.c.id == identifier)
        with self.registry.session() as session:
            return [dict(row) for row in session.execute(statement).mappings()]
