from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class Section:
    heading: str | None
    level: int
    text: str


@dataclass
class ParsedDocument:
    text: str
    sections: list[Section]
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentMetadata(BaseModel):
    doc_id: str
    source: str
    format: str
    title: str
    doc_type: str
    created_at: date | None = None
    entities: dict[str, list[str]] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    version: int
    index: int
    text: str
    section_path: list[str]
    char_start: int
    char_end: int
    token_count: int
    metadata: dict[str, Any]
