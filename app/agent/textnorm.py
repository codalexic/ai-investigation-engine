import re
from collections.abc import Iterable, Iterator

DASHES = str.maketrans(
    {c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"}
)


def normalize_llm_text(text: str) -> str:
    return text.translate(DASHES).translate(
        str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u00a0": " "})
    )


def normalize_citations(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return "".join(f"[{key}]" for key in re.findall(r"E\d+", match[0].split("\u2020")[0]))

    return re.sub(
        r"\u3010E\d+[^\u3011]*\u3011|\(E\d+(?:\s*,\s*E\d+)*\)|\[E\d+(?:\s*,\s*E\d+)*\]",
        replace,
        text,
    )


def normalized_deltas(deltas: Iterable[str]) -> Iterator[str]:
    pending = ""
    for delta in deltas:
        pending += normalize_llm_text(delta)
        match = re.search(r"[\u3010\[(][^\u3011\])]*$", pending)
        end = match.start() if match else len(pending)
        if end:
            yield normalize_citations(pending[:end])
            pending = pending[end:]
    if pending:
        yield normalize_citations(pending)
