import os
from unittest.mock import Mock

import pytest

from app.agent.evidence import EvidenceStore
from app.agent.nli import FakeNli, OnnxNliModel
from app.agent.synthesizer import AnswerMetadata, Claim, Contradiction
from app.agent.verifier import Verifier
from app.core.config import Settings
from tests.agent.test_agent import chunk

TEXT = (
    "Incident INC-2031 began at 09:00. Responders reviewed the deployment logs. "
    "The affected services were payment-gateway and fraud-api. "
    "CHG-1042 changed the connection pool. The rollback restored service. "
    "The review was completed on Friday."
)


def test_short_window_support():
    evidence = EvidenceStore()
    evidence.add(chunk(text=TEXT))
    nli = Mock()
    nli.predict_batch.side_effect = lambda pairs: [
        {
            "entailment": float("affected services" in a and len(a.split()) < 15),
            "contradiction": 0.0,
        }
        for a, b in pairs
    ]
    report = Verifier(nli, Settings(_env_file=None)).verify(
        "Payment-gateway was affected 【E1】.", AnswerMetadata(), evidence
    )
    assert not report.abstained
    assert report.metadata.claims[0].supported
    assert all(a != TEXT for a, b in nli.predict_batch.call_args_list[0].args[0])


def test_meta_and_question_excluded():
    evidence = EvidenceStore()
    evidence.add(chunk())
    report = Verifier(FakeNli(), Settings(_env_file=None)).verify(
        "What happened?\nThe documents confirming this are syn:review-INC-2031 (E1).\n"
        "payment-service rollback succeeded [E1].",
        AnswerMetadata(),
        evidence,
        question="What happened?",
    )
    assert not report.abstained
    assert [c.kind for c in report.metadata.claims] == ["excluded", "citation", "factual"]


@pytest.mark.parametrize(
    "reverse,entailment,expected", [(0.2, 0.0, 0), (0.96, 0.4, 0), (0.96, 0.0, 1)]
)
def test_bidirectional_contradictions(reverse, entailment, expected):
    evidence = EvidenceStore()
    evidence.add(chunk(text="payment-service rollback succeeded."))
    evidence.add(chunk("b", "payment-service rollback not succeeded.", doc_id="other"))
    nli = Mock()
    nli.predict_batch.side_effect = lambda pairs: [
        {"contradiction": 0.96 if i % 2 == 0 else reverse, "entailment": entailment}
        for i, _ in enumerate(pairs)
    ]
    report = Verifier(nli, Settings(_env_file=None)).verify("", AnswerMetadata(), evidence)
    assert len(report.metadata.contradictions) == expected


def test_llm_conflict_requires_distinct_documents():
    evidence = EvidenceStore()
    evidence.add(chunk())
    evidence.add(chunk("b"))
    metadata = AnswerMetadata(
        contradictions=[Contradiction(description="Conflict", evidence=["E1", "E2"])]
    )
    report = Verifier(None, Settings(_env_file=None)).verify("", metadata, evidence)
    assert not report.metadata.contradictions


@pytest.mark.models
@pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="Opt-in model download")
def test_real_window_support():
    evidence = EvidenceStore()
    evidence.add(chunk(text=TEXT))
    metadata = AnswerMetadata(
        claims=[
            Claim(text="Payment-gateway was affected.", evidence=["E1"]),
            Claim(text="The incident was caused by CHG-1047.", evidence=["E1"]),
        ]
    )
    report = Verifier(
        OnnxNliModel("Xenova/nli-deberta-v3-xsmall"), Settings(_env_file=None)
    ).verify("", metadata, evidence)
    assert report.metadata.claims[0].supported
    assert not report.metadata.claims[1].supported


class ParaphraseNli:
    def __init__(self, contradiction=0.02):
        self.contradiction = contradiction

    def predict_batch(self, pairs):
        return [{"entailment": 0.06, "contradiction": self.contradiction} for _ in pairs]


@pytest.mark.parametrize("separator", ["; ", ", and "])
def test_grounded_compound(separator):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption. INC-42 affected payment-service."))
    answer = (
        "The disruption was caused by CHG-1042"
        + separator
        + "payment-service was affected by INC-42 [E1]."
    )
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        answer, AnswerMetadata(), evidence
    )
    claim = report.metadata.claims[0]
    assert claim.supported and claim.support_method == "grounding"
    assert claim.grounding_score >= 0.5
    assert not report.abstained


@pytest.mark.parametrize(
    "claim",
    [
        "CHG-1043 caused the disruption",
        "CHG-1042 caused 25 failures",
        'CHG-1042 caused the "missing quote" disruption',
        "CHG-1042 affected unknown-service",
    ],
)
def test_grounding_requires_every_entity(claim):
    evidence = EvidenceStore()
    evidence.add(chunk(text='CHG-1042 caused 20 failures and the "pool" disruption.'))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        claim + " [E1].", AnswerMetadata(), evidence
    )
    assert not report.metadata.claims[0].supported
    assert report.abstained


@pytest.mark.parametrize("contradiction,expected", [(0.89, True), (0.9, False)])
def test_grounding_contradiction_veto(contradiction, expected):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption."))
    report = Verifier(ParaphraseNli(contradiction), Settings(_env_file=None)).verify(
        "CHG-1042 caused the disruption [E1].", AnswerMetadata(), evidence
    )
    assert report.metadata.claims[0].supported == expected


@pytest.mark.parametrize("uncited,abstained", [(1, False), (2, True)])
def test_ratio_counts_cited_claims_only(uncited, abstained):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption."))
    answer = "CHG-1042 caused the disruption [E1].\n" + "\n".join(
        f"Unsupported assertion number {i}." for i in range(uncited)
    )
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        answer, AnswerMetadata(), evidence
    )
    assert report.abstained == abstained
    if not abstained:
        assert "_(unverified)_" in report.answer


def test_compound_requires_all_parts():
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption. INC-42 affected payment-service."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        "CHG-1042 caused the disruption; INC-99 affected payment-service [E1].",
        AnswerMetadata(),
        evidence,
    )
    assert report.abstained


def test_relevant_evidence_rendering():
    evidence = EvidenceStore()
    evidence.add(chunk(text="Unrelated introduction. " * 100 + "CHG-1042 caused the disruption."))
    rendered = evidence.render(150, "What caused CHG-1042 disruption?")
    assert "CHG-1042 caused the disruption" in rendered
    assert rendered.count("Unrelated introduction") < 4


@pytest.mark.parametrize("first", ["Uncited direct answer.", "INC-99 caused the disruption [E1]."])
def test_direct_answer_must_be_cited_and_supported(first):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        first + "\nCHG-1042 caused the disruption [E1].", AnswerMetadata(), evidence
    )
    assert report.abstained


@pytest.mark.parametrize(
    "line", ["Sources: syn:review (id E1)", "- hotpot:123 (id E1)", "pm:report [E1]"]
)
def test_source_listing_is_not_factual(line):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        "CHG-1042 caused the disruption [E1].\n" + line, AnswerMetadata(), evidence
    )
    assert not report.abstained
    assert report.metadata.claims[-1].kind == "citation"


@pytest.mark.parametrize(
    "claim,supported",
    [
        ("Rollback restored service.", True),
        ("Rollback restored all database connections.", False),
        ('The "pool" caused disruption.', True),
    ],
)
def test_grounding_without_identifiers(claim, supported):
    evidence = EvidenceStore()
    evidence.add(chunk(text="Rollback restored service. The pool caused disruption."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        claim + " [E1]", AnswerMetadata(), evidence
    )
    assert report.metadata.claims[0].supported == supported


def test_nli_support_method():
    evidence = EvidenceStore()
    evidence.add(chunk())
    report = Verifier(FakeNli(), Settings(_env_file=None)).verify(
        "payment-service rollback succeeded [E1].", AnswerMetadata(), evidence
    )
    assert report.metadata.claims[0].support_method == "nli"


def test_shared_window_ranking_and_stemming():
    from app.agent.windows import content_tokens, support_windows

    assert "restor" in content_tokens("The service restored connections")
    assert support_windows("Unrelated sentence. CHG-42 restored service.", "CHG-42", 1) == [
        "CHG-42 restored service."
    ]


def test_spec_paraphrase_is_grounded():
    evidence = EvidenceStore()
    evidence.add(chunk(text="The investigation attributed the incident to CHG-1042."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        "The disruption was caused by change CHG-1042 [E1].", AnswerMetadata(), evidence
    )
    assert not report.abstained
    assert report.metadata.claims[0].support_method == "grounding"


@pytest.mark.parametrize("date,expected", [("2026-10-27", True), ("2026-10-28", False)])
def test_grounding_dates(date, expected):
    evidence = EvidenceStore()
    evidence.add(chunk(text="CHG-1042 caused the disruption on 2026-10-27."))
    report = Verifier(ParaphraseNli(), Settings(_env_file=None)).verify(
        f"CHG-1042 caused the disruption on {date} [E1].", AnswerMetadata(), evidence
    )
    assert report.metadata.claims[0].supported == expected
