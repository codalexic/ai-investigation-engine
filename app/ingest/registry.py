from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    create_engine,
    select,
    update,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.errors import DocumentNotFoundError, IngestionError


class Base(DeclarativeBase):
    pass


class IndexMeta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


class DocumentRecord(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid4().hex)
    source: Mapped[str] = mapped_column(String)
    format: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    created_at: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="active")
    duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("documents.doc_id"))
    minhash: Mapped[bytes] = mapped_column(LargeBinary)
    entities: Mapped[dict] = mapped_column(JSON, default=dict)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_strategy: Mapped[str] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url)


class DocumentRegistry:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.create_all()

    def create_all(self) -> None:
        try:
            Base.metadata.create_all(self.engine)
            with self.session() as session:
                if session.get(IndexMeta, "index_version") is None:
                    session.add(IndexMeta(key="index_version", value=0))
        except SQLAlchemyError as exc:
            raise IngestionError("Cannot initialize document registry") from exc

    @contextmanager
    def session(self) -> Iterator[Session]:
        try:
            with Session(self.engine, expire_on_commit=False) as session, session.begin():
                yield session
        except SQLAlchemyError as exc:
            raise IngestionError("Document registry operation failed") from exc

    def get(self, doc_id: str) -> DocumentRecord | None:
        with self.session() as session:
            return session.get(DocumentRecord, doc_id)

    def get_by_hash(self, digest: str) -> DocumentRecord | None:
        with self.session() as session:
            return session.scalar(
                select(DocumentRecord).where(
                    DocumentRecord.content_hash == digest, DocumentRecord.status == "active"
                )
            )

    def list(
        self, offset: int = 0, limit: int = 100, doc_type: str | None = None, q: str | None = None
    ) -> list[DocumentRecord]:
        statement = select(DocumentRecord).where(DocumentRecord.status == "active")
        if doc_type:
            statement = statement.where(DocumentRecord.doc_type == doc_type)
        if q:
            statement = statement.where(DocumentRecord.title.ilike(f"%{q}%"))
        with self.session() as session:
            return list(
                session.scalars(
                    statement.order_by(DocumentRecord.doc_id).offset(offset).limit(limit)
                )
            )

    def upsert(self, record: DocumentRecord | dict[str, Any]) -> DocumentRecord:
        record = DocumentRecord(**record) if isinstance(record, dict) else record
        record.updated_at = datetime.now(UTC)
        with self.session() as session:
            merged = session.merge(record)
            self._bump(session)
            return merged

    def bulk_upsert(self, records: list[DocumentRecord]) -> None:
        with self.session() as session:
            session.add_all(records)
            if records:
                self._bump(session)
            session.add_all(
                [
                    DocumentVersion(doc_id=r.doc_id, version=r.version, content_hash=r.content_hash)
                    for r in records
                ]
            )

    def mark_deleted(self, doc_id: str) -> None:
        with self.session() as session:
            record = session.get(DocumentRecord, doc_id)
            if record is None:
                raise DocumentNotFoundError(doc_id)
            self._bump(session)
            record.status = "deleted"
            record.updated_at = datetime.now(UTC)

    @staticmethod
    def _bump(session: Session) -> None:
        session.execute(
            update(IndexMeta)
            .where(IndexMeta.key == "index_version")
            .values(value=IndexMeta.value + 1)
        )

    def add_version(self, doc_id: str, version: int, content_hash: str) -> None:
        with self.session() as session:
            session.add(DocumentVersion(doc_id=doc_id, version=version, content_hash=content_hash))

    def iter_signatures(self) -> Iterator[tuple[str, np.ndarray]]:
        with self.session() as session:
            rows = session.execute(
                select(DocumentRecord.doc_id, DocumentRecord.minhash).where(
                    DocumentRecord.status == "active"
                )
            ).yield_per(500)
            for key, value in rows:
                yield key, np.frombuffer(value, dtype="<u8").copy()
