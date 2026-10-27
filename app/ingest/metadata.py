import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.ingest.models import DocumentMetadata, ParsedDocument

MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
DATE_RE = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|{MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{MONTH}\s+\d{{4}})\b",
    re.I,
)
CHANGE_RE = re.compile(r"\bCHG-\d+\b", re.I)
INCIDENT_RE = re.compile(r"\bINC-\d+\b", re.I)
SERVICE_RE = re.compile(r"\b[a-z][a-z0-9]+(?:-[a-z0-9]+)*-(?:service|svc|api|gateway|worker|db)\b")
TYPE_RULES = {
    "incident_report": [(r"incident[ _-]?(?:report)?", 2)],
    "postmortem": [(r"post[ _-]?mortem|root cause analysis", 4)],
    "changelog": [(r"change[ _-]?log|release notes", 3)],
    "runbook": [(r"runbook|playbook|operational procedure", 3)],
    "technical_doc": [(r"architecture|technical|design document|specification", 2)],
    "ticket": [(r"ticket|jira|bug report", 3)],
    "meeting_notes": [(r"meeting|minutes|standup", 3)],
}


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    match = DATE_RE.search(value)
    if not match:
        return None
    text = match[0].replace(",", "")
    for fmt in ("%Y-%m-%d", "%B %d %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def extract_entities(text: str, extra_services: Iterable[str] = ()) -> dict[str, list[str]]:
    services = [(m.start(), m[0]) for m in SERVICE_RE.finditer(text)]
    for service in extra_services:
        services.extend(
            (m.start(), service) for m in re.finditer(rf"(?<!\w){re.escape(service)}(?!\w)", text)
        )
    dates = [parsed.isoformat() for m in DATE_RE.finditer(text) if (parsed := parse_date(m[0]))]
    return {
        "services": list(dict.fromkeys(value for _, value in sorted(services))),
        "change_ids": list(dict.fromkeys(m[0].upper() for m in CHANGE_RE.finditer(text))),
        "incident_ids": list(dict.fromkeys(m[0].upper() for m in INCIDENT_RE.finditer(text))),
        "dates": list(dict.fromkeys(dates)),
    }


def extract_metadata(
    parsed: ParsedDocument, filename: str, doc_id: str, extra_services: Iterable[str] = ()
) -> DocumentMetadata:
    info = parsed.metadata
    title = info.get("title") or next(
        (s.heading for s in parsed.sections if s.level == 1 and s.heading), None
    )
    title = title or re.sub(r"[_-]+", " ", Path(filename).stem).strip().title()
    created = (
        parse_date(info.get("created_at"))
        or parse_date(info.get("date"))
        or parse_date(parsed.text[:2000])
    )
    context = f"{filename} {title} {parsed.text[:1000]}".lower()
    scores = {
        label: sum(weight * len(re.findall(pattern, context)) for pattern, weight in rules)
        for label, rules in TYPE_RULES.items()
    }
    best = max(scores.values())
    winners = [label for label, score in scores.items() if score == best]
    return DocumentMetadata(
        doc_id=doc_id,
        source=info.get("source", filename),
        format=info.get("format", "txt"),
        title=title,
        created_at=created,
        doc_type=info.get("doc_type") or (winners[0] if best and len(winners) == 1 else "other"),
        entities=extract_entities(parsed.text, extra_services),
        extra=json_safe(info),
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items() if not isinstance(v, bytes)}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value if not isinstance(v, bytes)]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)
