import json
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from sqlalchemy import case, func, or_, select
from sqlalchemy.sql.elements import ColumnElement
from starlette.concurrency import run_in_threadpool

from app.api.schemas import DocumentDetail, DocumentList
from app.container import Container, get_container
from app.core.errors import (
    AccessDeniedError,
    DocumentNotFoundError,
    InvalidRequestError,
    UploadTooLargeError,
)
from app.ingest.parsers import get_parser
from app.ingest.pipeline import IngestResult
from app.ingest.registry import DocumentRecord, DocumentVersion

router = APIRouter(prefix="/api/documents", tags=["documents"])
Dependency = Annotated[Container, Depends(get_container)]


def origin(record: DocumentRecord) -> str:
    return (
        "seed"
        if record.doc_id.startswith(("hotpot:", "pm:", "syn:"))
        else record.extra.get("origin", "user")
    )


def origin_expression() -> ColumnElement[str]:
    return case(
        (
            or_(
                *(DocumentRecord.doc_id.startswith(prefix) for prefix in ("hotpot:", "pm:", "syn:"))
            ),
            "seed",
        ),
        else_=func.coalesce(DocumentRecord.extra["origin"].as_string(), "user"),
    )


def serialize(record: DocumentRecord) -> dict[str, Any]:
    return {
        **{
            column.name: getattr(record, column.name)
            for column in DocumentRecord.__table__.columns
            if column.name != "minhash"
        },
        "origin": origin(record),
    }


def active(container: Container, doc_id: str) -> DocumentRecord:
    record = container.registry.get(doc_id)
    if record is None or record.status != "active":
        raise DocumentNotFoundError(doc_id)
    return record


def protect(container: Container, record: DocumentRecord, token: str | None) -> None:
    configured = container.settings.admin_token
    if origin(record) == "seed" and (
        (
            configured
            and not secrets.compare_digest(
                (token or "").encode(), configured.get_secret_value().encode()
            )
        )
        or (not configured and container.settings.app_env == "prod")
    ):
        raise AccessDeniedError("An admin token is required to modify seed documents")


async def upload(file: UploadFile, container: Container) -> bytes:
    try:
        get_parser(file.filename or "")
        data = await file.read(container.settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > container.settings.max_upload_mb * 1024 * 1024:
            raise UploadTooLargeError("Upload exceeds max_upload_mb")
        return data
    finally:
        await file.close()


def metadata_fields(metadata: str | None, doc_type: str | None) -> dict[str, Any]:
    try:
        fields = json.loads(metadata) if metadata else {}
    except ValueError as exc:
        raise InvalidRequestError("metadata must be a JSON object") from exc
    if not isinstance(fields, dict):
        raise InvalidRequestError("metadata must be a JSON object")
    if doc_type:
        fields["doc_type"] = doc_type
    return fields


@router.post("", response_model=IngestResult)
async def create(
    container: Dependency,
    file: Annotated[UploadFile, File()],
    doc_type: str | None = Form(None),
    metadata: str | None = Form(None),
) -> IngestResult:
    fields = metadata_fields(metadata, doc_type)
    fields["origin"] = "user"
    data = await upload(file, container)
    result = await run_in_threadpool(
        container.pipeline.ingest, data, file.filename or "", extra_metadata=fields
    )
    return result


@router.get("", response_model=DocumentList)
def listing(
    container: Dependency,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    doc_type: str | None = None,
    q: str | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    statement = select(DocumentRecord).where(DocumentRecord.status == "active")
    if doc_type:
        statement = statement.where(DocumentRecord.doc_type == doc_type)
    if q:
        statement = statement.where(DocumentRecord.title.ilike(f"%{q}%"))
    if origin:
        statement = statement.where(origin_expression() == origin)
    with container.registry.session() as session:
        total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        records = [
            serialize(r)
            for r in session.scalars(
                statement.order_by(DocumentRecord.doc_id).offset(offset).limit(limit)
            )
        ]
    return {"items": records, "total": total}


@router.get("/{doc_id}", response_model=DocumentDetail)
def detail(doc_id: str, container: Dependency) -> dict[str, Any]:
    record = active(container, doc_id)
    with container.registry.session() as session:
        versions = [
            {c.name: getattr(v, c.name) for c in DocumentVersion.__table__.columns}
            for v in session.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.doc_id == doc_id)
                .order_by(DocumentVersion.version)
            )
        ]
    return {**serialize(record), "metadata": serialize(record), "versions": versions}


@router.get("/{doc_id}/chunks")
def chunks(doc_id: str, container: Dependency) -> list[dict[str, Any]]:
    active(container, doc_id)
    return [c.payload for c in container.store.get_document_chunks(doc_id)]


@router.put("/{doc_id}", response_model=IngestResult)
async def replace(
    doc_id: str,
    container: Dependency,
    file: Annotated[UploadFile, File()],
    doc_type: str | None = Form(None),
    metadata: str | None = Form(None),
    x_admin_token: str | None = Header(None),
) -> IngestResult:
    record = active(container, doc_id)
    protect(container, record, x_admin_token)
    preserved = {key: value for key, value in record.extra.items() if key != "format"}
    fields = {**preserved, **metadata_fields(metadata, doc_type), "origin": origin(record)}
    data = await upload(file, container)
    result = await run_in_threadpool(
        container.pipeline.ingest, data, file.filename or "", doc_id, fields
    )
    return result


@router.delete("/{doc_id}", status_code=204)
def delete(
    doc_id: str, container: Dependency, x_admin_token: str | None = Header(None)
) -> Response:
    protect(container, active(container, doc_id), x_admin_token)
    container.pipeline.delete(doc_id)
    return Response(status_code=204)
