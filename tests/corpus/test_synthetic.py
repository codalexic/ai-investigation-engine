import csv
import io
import json
import re

import pytest
from pypdf import PdfReader

from app.corpus.synthetic import SCENARIO, _expand, _scenario, generate
from app.ingest.parsers import get_parser


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    generate(root)
    directory = root / "data/synthetic"
    parsed = {
        path.name: get_parser(path.name).parse(path.read_bytes(), path.name)
        for path in directory.iterdir()
    }
    truth = json.loads((root / "eval/data/synthetic_ground_truth.json").read_text())
    return directory, parsed, truth


def test_seeded_scenario_and_binary_determinism(corpus, tmp_path):
    directory, _, truth = corpus
    assert _expand(_scenario()) == SCENARIO
    generate(tmp_path)
    for path in directory.iterdir():
        assert path.read_bytes() == (tmp_path / "data/synthetic" / path.name).read_bytes()
    assert truth == json.loads((tmp_path / "eval/data/synthetic_ground_truth.json").read_text())


def test_all_formats_and_length_targets(corpus):
    directory, parsed, _ = corpus
    targets = {
        "review-": (900, 1500),
        "incident-": (400, 700),
        "runbook-": (600, 1000),
        "meeting-": (300, 600),
    }
    for name, document in parsed.items():
        assert document.text
        for prefix, (minimum, maximum) in targets.items():
            if name.startswith(prefix):
                assert minimum <= len(document.text.split()) <= maximum, name
        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO((directory / name).read_bytes()))
            assert len(reader.pages) == 2
            assert all(page.extract_text().strip() for page in reader.pages)
        if name.startswith("status-"):
            assert 6 <= len(re.findall(r"2025-\d\d-\d\d 09:00 UTC", document.text)) <= 12
        if name.startswith("ticket-"):
            assert 4 <= len(re.findall(r"2025-\d\d-\d\d 10:00 UTC", document.text)) <= 8
    assert 1500 <= len(parsed["architecture.md"].text.split()) <= 2500
    with (directory / "change-log.csv").open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 60


def test_ground_truth_evidence(corpus):
    _, parsed, truth = corpus
    assert len(truth["facts"]) >= 25
    assert len(truth["contradictions"]) == 4
    assert len(truth["gaps"]) == 3
    assert len(truth["multi_hop"]) == 10
    assert 2 <= len(truth["injections"]) <= 3
    for fact in truth["facts"] + truth["multi_hop"]:
        assert fact["answer"]
        assert any(fact["answer"] in parsed[name].text for name in fact["documents"])
        if len(fact["documents"]) > 1:
            assert set(fact["evidence"]) == set(fact["documents"])
            for name, evidence in fact["evidence"].items():
                assert evidence in parsed[name].text
    for item in truth["multi_hop"]:
        assert 2 <= len(item["documents"]) <= 3
    for conflict in truth["contradictions"]:
        for name, claim in zip(conflict["documents"], conflict["claims"], strict=True):
            assert claim in parsed[name].text
    for injection in truth["injections"]:
        assert injection["payload"] in parsed[injection["doc"]].text


def test_sections_and_preserved_design(corpus):
    _, parsed, _ = corpus
    for name, doc in parsed.items():
        if name.startswith("review-"):
            for heading in (
                "Summary",
                "Customer impact",
                "Timeline",
                "Detection",
                "Root cause analysis",
                "Contributing factors",
                "What went well",
                "What went poorly",
                "Action items",
            ):
                assert any(section.heading == heading for section in doc.sections)
            assert 10 <= len(re.findall(r"\d\d:\d\d UTC", doc.text)) <= 20
        if name.startswith("runbook-"):
            for heading in (
                "Overview",
                "Dependencies",
                "Dashboards & alerts",
                "Common failure modes",
                "Procedures",
                "Escalation",
                "Configuration reference",
            ):
                assert any(section.heading == heading for section in doc.sections)
    original = parsed["incident-INC-2031.pdf"].text
    exported = parsed["incident-INC-2031-export.pdf"].text
    assert exported.startswith(original)
    assert "version 2" in parsed["runbook-payment-gateway.v2.docx"].text
    assert "50 connections" in parsed["runbook-payment-gateway.docx"].text
    assert "200 connections" in parsed["runbook-payment-gateway.v2.docx"].text
