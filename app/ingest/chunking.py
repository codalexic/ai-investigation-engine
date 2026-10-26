import re
from itertools import pairwise
from typing import Protocol

from app.core.config import Settings
from app.core.errors import IngestionError
from app.ingest.dedup import content_hash
from app.ingest.metadata import extract_entities
from app.ingest.models import Chunk, DocumentMetadata, ParsedDocument


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class RegexTokenCounter:
    def count(self, text: str) -> int:
        return len(re.findall(r"\w+|[^\w\s]", text))


class Chunker(Protocol):
    name: str

    def chunk(
        self, doc_id: str, version: int, parsed: ParsedDocument, metadata: DocumentMetadata
    ) -> list[Chunk]: ...


def _chunks(
    doc_id: str,
    version: int,
    parsed: ParsedDocument,
    metadata: DocumentMetadata,
    spans: list[tuple[int, int, list[str]]],
    counter: TokenCounter,
) -> list[Chunk]:
    result = []
    seen = set()
    for start, end, path in spans:
        text = parsed.text[start:end]
        digest = content_hash(text)
        if not text.strip() or digest in seen:
            continue
        seen.add(digest)
        index = len(result)
        fields = metadata.model_dump(
            mode="json", include={"title", "doc_type", "source", "created_at"}
        )
        fields["entities"] = extract_entities(text)
        result.append(
            Chunk(
                f"{doc_id}:{version}:{index}",
                doc_id,
                version,
                index,
                text,
                list(path),
                start,
                end,
                counter.count(text),
                fields,
            )
        )
    return result


def _windows(
    text: str, start: int, end: int, size: int, overlap: int, counter: TokenCounter
) -> list[tuple[int, int]]:
    tokens = list(re.finditer(r"\w+|[^\w\s]", text[start:end]))
    result = []
    i = 0
    while i < len(tokens):
        j = min(i + size, len(tokens))
        while (
            j > i
            and counter.count(text[start + tokens[i].start() : start + tokens[j - 1].end()]) > size
        ):
            j -= 1
        if j == i:
            raise IngestionError("A token exceeds the configured chunk size")
        if j < len(tokens):
            boundary = j
            while (
                boundary > i + 1
                and not text[
                    start + tokens[boundary - 1].end() : start + tokens[boundary].start()
                ].isspace()
            ):
                boundary -= 1
            if boundary > i + 1:
                j = boundary
        result.append((start + tokens[i].start(), start + tokens[j - 1].end()))
        if j == len(tokens):
            break
        i = max(i + 1, j - overlap)
    return result


class FixedWindowChunker:
    name = "fixed"

    def __init__(
        self, size: int = 400, overlap: int = 60, token_counter: TokenCounter | None = None
    ) -> None:
        if size < 1 or overlap < 0 or overlap >= size:
            raise IngestionError("Require size > overlap >= 0")
        self.size, self.overlap = size, overlap
        self.counter = token_counter or RegexTokenCounter()

    def chunk(
        self, doc_id: str, version: int, parsed: ParsedDocument, metadata: DocumentMetadata
    ) -> list[Chunk]:
        spans = [
            (a, b, [])
            for a, b in _windows(
                parsed.text, 0, len(parsed.text), self.size, self.overlap, self.counter
            )
        ]
        return _chunks(doc_id, version, parsed, metadata, spans, self.counter)


def sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    boundaries = [start]
    for match in re.finditer(r"(?:[.!?]+\s+|\n\s*\n)", text[start:end]):
        point = start + match.start()
        prefix = text[start : point + 1]
        if re.search(r"\b(?:e\.g|i\.e|Inc|Dr|Mr|Mrs|Ms|vs|etc)\.$", prefix, re.I):
            continue
        boundaries.append(start + match.end())
    boundaries.append(end)
    return [(a, b) for a, b in pairwise(boundaries) if text[a:b].strip()]


class StructureAwareChunker:
    name = "structure"

    def __init__(
        self,
        max_tokens: int = 400,
        min_tokens: int = 60,
        overlap_sentences: int = 1,
        token_counter: TokenCounter | None = None,
    ) -> None:
        if max_tokens < 1 or not 0 <= min_tokens < max_tokens or overlap_sentences < 0:
            raise IngestionError("Invalid structure chunk limits")
        self.max_tokens, self.min_tokens = max_tokens, min_tokens
        self.overlap_sentences = overlap_sentences
        self.counter = token_counter or RegexTokenCounter()

    def chunk(
        self, doc_id: str, version: int, parsed: ParsedDocument, metadata: DocumentMetadata
    ) -> list[Chunk]:
        spans = []
        headings: list[tuple[int, str]] = []
        cursor = 0
        sections = parsed.sections
        if not sections:
            return FixedWindowChunker(self.max_tokens, 0, self.counter).chunk(
                doc_id, version, parsed, metadata
            )
        for section in sections:
            if section.heading:
                headings = [(level, title) for level, title in headings if level < section.level]
                headings.append((section.level, section.heading))
            path = [title for _, title in headings]
            start = parsed.text.find(section.text, cursor)
            if start < 0:
                raise IngestionError("Section text is absent from document")
            end = start + len(section.text)
            cursor = end
            if self.counter.count(section.text) <= self.max_tokens:
                spans.append((start, end, path))
                continue
            units = []
            paragraph_bounds = [start]
            paragraph_bounds.extend(start + m.end() for m in re.finditer(r"\n\s*\n", section.text))
            paragraph_bounds.append(end)
            for pa, pb in pairwise(paragraph_bounds):
                if not parsed.text[pa:pb].strip():
                    continue
                if self.counter.count(parsed.text[pa:pb]) <= self.max_tokens:
                    units.append((pa, pb))
                    continue
                for a, b in sentence_spans(parsed.text, pa, pb):
                    if self.counter.count(parsed.text[a:b]) > self.max_tokens:
                        units.extend(_windows(parsed.text, a, b, self.max_tokens, 0, self.counter))
                    else:
                        units.append((a, b))
            packed = []
            i = 0
            overlap_start: int | None = None
            while i < len(units):
                chunk_start = overlap_start if overlap_start is not None else units[i][0]
                j = i + 1
                while (
                    j < len(units)
                    and self.counter.count(parsed.text[chunk_start : units[j][1]])
                    <= self.max_tokens
                ):
                    j += 1
                chunk_end = units[j - 1][1]
                packed.append((chunk_start, chunk_end, path))
                if j == len(units):
                    break
                overlap_start = None
                if self.overlap_sentences:
                    previous = sentence_spans(parsed.text, chunk_start, chunk_end)
                    for a, _ in previous[-self.overlap_sentences :]:
                        if self.counter.count(parsed.text[a : units[j][1]]) <= self.max_tokens:
                            overlap_start = a
                            break
                i = j
            packed = self._merge_small(parsed.text, packed)
            spans.extend(packed)
        return _chunks(doc_id, version, parsed, metadata, spans, self.counter)

    def _merge_small(
        self, text: str, spans: list[tuple[int, int, list[str]]]
    ) -> list[tuple[int, int, list[str]]]:
        """The maximum is hard; rebalance neighbours when a merged span would exceed it."""
        i = 0
        while i < len(spans) and len(spans) > 1:
            start, end, path = spans[i]
            if self.counter.count(text[start:end]) >= self.min_tokens:
                i += 1
                continue
            left = i - 1 if i else 0
            right = i if i else 1
            a, b = spans[left][0], spans[right][1]
            if self.counter.count(text[a:b]) <= self.max_tokens:
                spans[left : right + 1] = [(a, b, path)]
                i = max(0, left - 1)
                continue
            candidates = [a + m.end() for m in re.finditer(r"\s+", text[a:b])]
            for split in sorted(candidates, key=lambda point: abs(point - (a + b) // 2)):
                before, after = self.counter.count(text[a:split]), self.counter.count(text[split:b])
                if self.min_tokens <= before <= self.max_tokens and (
                    self.min_tokens <= after <= self.max_tokens
                ):
                    spans[left : right + 1] = [(a, split, path), (split, b, path)]
                    break
            i += 1
        return spans


def build_chunker(settings: Settings) -> Chunker:
    if settings.chunk_strategy == "fixed":
        return FixedWindowChunker(settings.chunk_size, settings.chunk_overlap)
    return StructureAwareChunker(settings.chunk_size, settings.chunk_min_tokens)
