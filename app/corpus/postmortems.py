import re
from pathlib import Path

import httpx

from app.core.errors import IngestionError
from app.corpus.common import short_hash, slug, write_jsonl

URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"


def parse_readme(text: str) -> list[dict]:
    category = "Uncategorized"
    records = {}
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)", line)
        if heading:
            category = heading[1].strip()
        match = re.match(r"^\s*(?:[-*+]\s+)?\[([^\]]+)\]\((https?://[^\s)]+)\)\s*(.*)", line)
        if not match:
            continue
        if category in {
            "Table of Contents",
            "Other lists of postmortems",
            "Analysis",
            "Contributors",
        }:
            continue
        company, url, summary = match.groups()
        key = f"pm:{slug(company)}-{short_hash(url)}"
        records[key] = {
            "doc_id": key,
            "text": f"{company}\n{summary}",
            "metadata": {
                "title": company,
                "source": url,
                "doc_type": "postmortem",
                "category": category,
                "summary": summary,
            },
        }
    return list(records.values())


def build(root: Path = Path(".")) -> dict[str, int]:
    cache = root / "data/raw/postmortems.md"
    if not cache.exists():
        try:
            response = httpx.get(URL, follow_redirects=True, timeout=60)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IngestionError("Cannot download postmortem directory") from exc
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(response.text, encoding="utf-8")
    records = parse_readme(cache.read_text(encoding="utf-8"))
    if not records:
        raise IngestionError("No postmortem entries found in cached README")
    write_jsonl(root / "data/corpus/postmortems.jsonl", records)
    return {"records": len(records)}
