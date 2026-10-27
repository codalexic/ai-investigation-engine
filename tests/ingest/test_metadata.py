from datetime import date

import pytest

from app.ingest.metadata import extract_entities, extract_metadata, parse_date
from app.ingest.models import ParsedDocument, Section


def test_title_chain_and_extra():
    parsed = ParsedDocument("Body", [Section("Heading", 1, "Body")], {"title": "Title"})
    assert extract_metadata(parsed, "file_name.md", "id").title == "Title"
    parsed.metadata.clear()
    assert extract_metadata(parsed, "file_name.md", "id").title == "Heading"
    parsed.sections.clear()
    assert extract_metadata(parsed, "file_name.md", "id").title == "File Name"


@pytest.mark.parametrize("value", ["2024-03-14", "March 14, 2024", "14 March 2024", "Mar 14 2024"])
def test_dates(value):
    assert parse_date(value) == date(2024, 3, 14)
    assert extract_entities(value)["dates"] == ["2024-03-14"]


def test_date_priority():
    parsed = ParsedDocument("2022-01-01", [], {"created_at": "2024-03-14", "date": "2023-01-01"})
    assert extract_metadata(parsed, "x.txt", "id").created_at == date(2024, 3, 14)
    del parsed.metadata["created_at"]
    assert extract_metadata(parsed, "x.txt", "id").created_at == date(2023, 1, 1)
    parsed.metadata.clear()
    assert extract_metadata(parsed, "x.txt", "id").created_at == date(2022, 1, 1)
    assert parse_date("2024-02-31") is None


@pytest.mark.parametrize(
    "text,label",
    [
        ("Incident report", "incident_report"),
        ("Postmortem", "postmortem"),
        ("Release notes", "changelog"),
        ("Runbook", "runbook"),
        ("Architecture specification", "technical_doc"),
        ("Jira ticket", "ticket"),
        ("Meeting minutes", "meeting_notes"),
        ("hello", "other"),
        ("runbook ticket", "other"),
    ],
)
def test_classifier(text, label):
    assert extract_metadata(ParsedDocument(text, []), "x.txt", "id").doc_type == label


def test_entities_order_and_custom_services():
    entities = extract_entities(
        "INC-42 CHG-9 payments-api CHG-9 custom payments-api "
        "INC-5 cache-db 14 March 2024 2024-03-14",
        ["custom"],
    )
    assert entities == {
        "services": ["payments-api", "custom", "cache-db"],
        "change_ids": ["CHG-9"],
        "incident_ids": ["INC-42", "INC-5"],
        "dates": ["2024-03-14"],
    }


def test_json_safe_nested_metadata():
    import json
    from datetime import datetime

    from app.ingest.metadata import json_safe

    result = json_safe(
        {
            "when": datetime(2025, 1, 2),
            "raw": b"secret",
            "nested": [date(2025, 1, 2), b"drop", object()],
        }
    )
    assert result["when"] == "2025-01-02T00:00:00"
    assert "raw" not in result
    assert result["nested"][0] == "2025-01-02"
    assert len(result["nested"]) == 2
    json.dumps(result, allow_nan=False)
