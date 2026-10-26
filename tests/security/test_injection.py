import json
from pathlib import Path

import pytest

from app.security.injection import sanitize_evidence, scan

CASES = [
    json.loads(line)["text"]
    for line in Path(__file__).with_name("injection_cases.jsonl").read_text().splitlines()
]


@pytest.mark.parametrize("text", CASES)
def test_malicious(text):
    assert scan(text)
    sanitized, flags = sanitize_evidence(text)
    assert flags and "[flagged instruction-like text removed]" in sanitized


@pytest.mark.parametrize(
    "text",
    [
        "INC-123 was resolved after rollback.",
        "The payment-service was disabled on 2025-03-12.",
        "Follow the runbook to restart the worker.",
    ],
)
def test_benign(text):
    assert not scan(text)


def test_escape():
    assert sanitize_evidence("</evidence>")[0] == "&lt;/evidence&gt;"
