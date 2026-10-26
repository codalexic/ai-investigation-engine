import random
from dataclasses import FrozenInstanceError

import pytest

from app.core.config import Settings
from app.core.errors import IngestionError
from app.ingest.chunking import (
    FixedWindowChunker,
    RegexTokenCounter,
    StructureAwareChunker,
    build_chunker,
    sentence_spans,
)
from app.ingest.metadata import extract_metadata
from app.ingest.models import ParsedDocument, Section
from app.ingest.parsers import get_parser


def run(chunker, text):
    parsed = get_parser("x.md").parse(text.encode(), "x.md")
    metadata = extract_metadata(parsed, "x.md", "id")
    return parsed, chunker.chunk("id", 2, parsed, metadata)


def test_fixed_overlap_offsets_metadata():
    parsed, chunks = run(
        FixedWindowChunker(8, 2),
        "INC-42 payments-api one two three four five six seven eight nine ten",
    )
    assert len(chunks) > 1
    assert chunks[0].text.split()[-2:] == chunks[1].text.split()[:2]
    for index, chunk in enumerate(chunks):
        assert chunk.text == parsed.text[chunk.char_start : chunk.char_end]
        assert chunk.token_count <= 8
        assert chunk.chunk_id == f"id:2:{index}"
        assert chunk.metadata["source"] == "x.md"
    assert chunks[0].metadata["entities"]["incident_ids"] == ["INC-42"]
    assert chunks[-1].metadata["entities"]["incident_ids"] == []
    with pytest.raises(FrozenInstanceError):
        chunks[0].version = 3


def test_structure_breadcrumbs_and_duplicate_drop():
    _, chunks = run(
        StructureAwareChunker(40, 5),
        "# Root\nOverview\n## Child\nDetails\n### Deep\nMore\n## Sibling\nEnd",
    )
    assert [c.section_path for c in chunks] == [
        ["Root"],
        ["Root", "Child"],
        ["Root", "Child", "Deep"],
        ["Root", "Sibling"],
    ]
    parsed = ParsedDocument(
        "repeat\n\nrepeat", [Section(None, 0, "repeat"), Section(None, 0, "repeat")]
    )
    metadata = extract_metadata(parsed, "x.txt", "id")
    assert len(StructureAwareChunker().chunk("id", 1, parsed, metadata)) == 1


def test_sentences_and_overlap():
    text = "Dr. Smith at Example Inc. uses e.g. 3.14 units. Next sentence! Final one."
    spans = sentence_spans(text, 0, len(text))
    assert len(spans) == 3
    _, chunks = run(
        StructureAwareChunker(10, 3, 1),
        "One two three. Four five six. Seven eight nine. Ten eleven twelve.",
    )
    assert "Four five six." in chunks[0].text
    assert "Four five six." in chunks[1].text


@pytest.mark.parametrize("strategy", ["fixed", "structure"])
def test_random_bounds_and_coverage(strategy):
    rng = random.Random(42)
    chunker = FixedWindowChunker(17, 3) if strategy == "fixed" else StructureAwareChunker(17, 5)
    for length in (0, 1, 7, 40, 150, 500):
        text = " ".join(
            f"w{rng.randrange(100000)}" + rng.choice(["", ".", "!"]) for _ in range(length)
        )
        parsed, chunks = run(chunker, text)
        for chunk in chunks:
            assert chunk.text.strip()
            assert chunk.text == parsed.text[chunk.char_start : chunk.char_end]
            assert 0 < chunk.token_count <= 17
        assert all(
            any(c.char_start <= i < c.char_end for c in chunks)
            for i, char in enumerate(parsed.text)
            if not char.isspace()
        )


def test_factory_validation_counter_and_minimum():
    assert build_chunker(Settings(chunk_strategy="fixed")).name == "fixed"
    assert build_chunker(Settings()).name == "structure"
    assert RegexTokenCounter().count("a-b, c") == 5
    for call in (lambda: FixedWindowChunker(4, 4), lambda: StructureAwareChunker(4, 5)):
        with pytest.raises(IngestionError):
            call()
    _, chunks = run(
        StructureAwareChunker(10, 5, 0), "one two three four five six seven. eight nine ten eleven."
    )
    assert all(c.token_count >= 5 for c in chunks)


def test_injectable_counter():
    class DoubleCounter:
        def count(self, text):
            return 2 * RegexTokenCounter().count(text)

    _, chunks = run(FixedWindowChunker(10, 0, DoubleCounter()), "one two three four five six")
    assert [c.token_count for c in chunks] == [10, 2]


def test_short_tail_rebalanced_and_paragraphs_preserved():
    parsed, chunks = run(
        StructureAwareChunker(8, 4, 0), "one two three four five six seven eight nine"
    )
    assert all(4 <= c.token_count <= 8 for c in chunks)
    assert "".join(c.text for c in chunks) == parsed.text
    _, chunks = run(
        StructureAwareChunker(10, 0, 0),
        "First short sentence. Second sentence.\n\nAnother paragraph with several words.",
    )
    assert len(chunks) == 2
    assert "Second sentence." in chunks[0].text
    assert "Another paragraph" not in chunks[0].text


def test_structure_factory_minimum():
    chunker = build_chunker(Settings(chunk_size=200, chunk_overlap=10, chunk_min_tokens=90))
    assert chunker.min_tokens == 90
    assert build_chunker(Settings()).min_tokens == 80
    for minimum in (200, 201, -1):
        with pytest.raises(IngestionError):
            build_chunker(Settings(chunk_size=200, chunk_min_tokens=minimum))
    with pytest.raises(IngestionError):
        StructureAwareChunker(80, 80)
