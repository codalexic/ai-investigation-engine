import csv
import io
import json
import re
import unicodedata
from pathlib import Path
from typing import Protocol
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup, Comment
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from app.agent.textnorm import DASHES
from app.core.config import get_settings
from app.core.errors import IngestionError, UnsupportedFormatError
from app.ingest.models import ParsedDocument, Section


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.translate(DASHES)).replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestionError("Unable to decode document")


def assemble(sections: list[Section], metadata: dict) -> ParsedDocument:
    sections = [Section(s.heading, s.level, normalize_text(s.text)) for s in sections]
    sections = [s for s in sections if s.text]
    text = "\n\n".join(s.text for s in sections)
    check_text_length(text)
    return ParsedDocument(text, sections, metadata)


def check_text_length(text: str) -> None:
    if len(text) > get_settings().max_extracted_chars:
        raise IngestionError("Extracted text exceeds max_extracted_chars")


def validate_docx(data: bytes) -> None:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if sum(m.file_size for m in members) > get_settings().max_extracted_mb * 1024**2:
                raise UnsupportedFormatError("DOCX expansion exceeds max_extracted_mb")
            for member in members:
                if member.file_size > 25 * 1024**2:
                    raise UnsupportedFormatError("DOCX member exceeds 25 MB")
                if member.file_size / max(1, member.compress_size) > 100:
                    raise UnsupportedFormatError("DOCX compression ratio exceeds 100")
    except BadZipFile as exc:
        raise IngestionError("Invalid DOCX zip archive") from exc


class Parser(Protocol):
    extensions: tuple[str, ...]

    def parse(self, data: bytes, filename: str) -> ParsedDocument: ...


class PDFParser:
    extensions = (".pdf",)

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise IngestionError("Encrypted PDF is unsupported")
            info = reader.metadata
            metadata = {"format": "pdf", "page_count": len(reader.pages)}
            if info:
                metadata.update(title=info.title, author=info.author, created_at=info.creation_date)
            return assemble(
                [Section(None, 0, p.extract_text() or "") for p in reader.pages], metadata
            )
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(f"Cannot parse PDF: {filename}") from exc


class DOCXParser:
    extensions = (".docx",)

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        validate_docx(data)
        try:
            doc = Document(io.BytesIO(data))
            sections = [Section(None, 0, "")]
            for element in doc.element.body:
                if element.tag == qn("w:p"):
                    paragraph = Paragraph(element, doc)
                    match = re.fullmatch(r"Heading (\d+)", paragraph.style.name or "")
                    if match:
                        sections.append(Section(paragraph.text, int(match[1]), paragraph.text))
                    else:
                        sections[-1].text += "\n" + paragraph.text
                elif element.tag == qn("w:tbl"):
                    table = Table(element, doc)
                    sections[-1].text += "\n" + "\n".join(
                        " | ".join(cell.text for cell in row.cells) for row in table.rows
                    )
            props = doc.core_properties
            return assemble(
                sections,
                {
                    "format": "docx",
                    "title": props.title,
                    "author": props.author,
                    "created_at": props.created,
                },
            )
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(f"Cannot parse DOCX: {filename}") from exc


class MarkdownParser:
    extensions = (".md", ".markdown", ".txt")

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        text = normalize_text(decode(data))
        metadata = {"format": Path(filename).suffix.lstrip(".").lower()}
        if text.startswith("---\n"):
            parts = text.split("\n---", 1)
            if len(parts) == 2:
                for line in parts[0].splitlines()[1:]:
                    key, sep, value = line.partition(":")
                    if sep:
                        metadata[key.strip()] = value.strip().strip("\"'")
                text = parts[1].lstrip("\n")
        sections = [Section(None, 0, "")]
        for line in text.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", line)
            if match:
                sections.append(Section(match[2], len(match[1]), line))
            else:
                sections[-1].text += "\n" + line
        return assemble(sections, metadata)


class HTMLParser:
    extensions = (".html", ".htm")

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        soup = BeautifulSoup(decode(data), "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else None
        for tag in soup(["script", "style", "nav", "title"]):
            tag.decompose()
        sections = [Section(None, 0, "")]
        for node in soup.descendants:
            if isinstance(node, Comment):
                continue
            if getattr(node, "name", None) in [f"h{i}" for i in range(1, 7)]:
                sections.append(Section(node.get_text(" ", strip=True), int(node.name[1]), ""))
            elif getattr(node, "name", None) in ("p", "div", "li", "br", "tr", "section"):
                sections[-1].text += "\n"
            elif isinstance(node, str):
                sections[-1].text += str(node)
        return assemble(sections, {"format": "html", "title": title})


class JSONParser:
    extensions = (".json", ".jsonl", ".ndjson")

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            text = decode(data)
            records = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if Path(filename).suffix.lower() != ".json"
                else json.loads(text)
            )
            records = records if isinstance(records, list) else [records]
            metadata = {"format": Path(filename).suffix.lstrip(".").lower()}
            sections = []
            for record in records:
                if not isinstance(record, dict):
                    raise IngestionError("JSON records must be objects")
                fields = {"text", "body", "content", "description", "summary", "message"}
                for key, value in record.items():
                    if key not in fields and isinstance(value, (str, int, float, bool)):
                        metadata.setdefault(key, value)
                sections.append(
                    Section(None, 0, "\n".join(f"{key}: {value}" for key, value in record.items()))
                )
            return assemble(sections, metadata)
        except (ValueError, TypeError) as exc:
            raise IngestionError(f"Cannot parse JSON: {filename}") from exc


class CSVParser:
    extensions = (".csv",)

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        metadata = {"format": "csv"}
        sections = []
        try:
            for row in csv.DictReader(io.StringIO(decode(data))):
                for key, value in row.items():
                    if key and "date" in key.lower() and value:
                        metadata.setdefault("created_at", value)
                sections.append(
                    Section(None, 0, "; ".join(f"{key}: {value}" for key, value in row.items()))
                )
            return assemble(sections, metadata)
        except csv.Error as exc:
            raise IngestionError(f"Cannot parse CSV: {filename}") from exc


PARSERS: tuple[Parser, ...] = (
    PDFParser(),
    DOCXParser(),
    MarkdownParser(),
    HTMLParser(),
    JSONParser(),
    CSVParser(),
)


def get_parser(filename: str) -> Parser:
    extension = Path(filename).suffix.lower()
    for parser in PARSERS:
        if extension in parser.extensions:
            return parser
    raise UnsupportedFormatError(f"Unsupported document format: {extension}")
