import pytest

from app.agent.textnorm import normalize_citations, normalize_llm_text, normalized_deltas
from app.ingest.parsers import normalize_text


@pytest.mark.parametrize(
    "text", ["\u3010E12\u3011", "\u3010E12\u2020source\u3011", "(E12)", "[E12]"]
)
def test_single_citation(text):
    assert normalize_citations(text) == "[E12]"


@pytest.mark.parametrize("text", ["[E12, E13]", "[E12][E13]", "[E12,E13]"])
def test_multiple_citations(text):
    assert normalize_citations(text) == "[E12][E13]"


def test_streaming():
    assert "".join(normalized_deltas(["Text \u3010E1", "2\u3011 (E", "13)"])) == "Text [E12] [E13]"


def test_unicode():
    dashes = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
    assert normalize_llm_text(dashes) == "-" * len(dashes)
    assert normalize_text(dashes) == "-" * len(dashes)
    assert normalize_llm_text("\u201cCHG\u20111042\u201d\u2018x\u2019\u00a0") == "\"CHG-1042\"'x' "
