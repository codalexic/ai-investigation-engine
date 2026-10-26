import re
from itertools import combinations, pairwise

from pydantic import BaseModel, Field

from app.agent.evidence import EvidenceStore
from app.agent.nli import NliModel
from app.agent.synthesizer import AnswerMetadata, Claim, Contradiction
from app.core.config import Settings
from app.core.errors import LLMError
from app.core.logging import get_logger
from app.ingest.chunking import sentence_spans
from app.ingest.metadata import extract_entities


class VerificationReport(BaseModel):
    answer: str
    abstained: bool
    metadata: AnswerMetadata
    verification_mode: str = "nli"
    unsupported_sentences: list[str] = Field(default_factory=list)
    removed_citations: list[str] = Field(default_factory=list)


class Verifier:
    def __init__(self, nli: NliModel | None, settings: Settings) -> None:
        self.nli, self.settings = nli, settings

    def verify(
        self, answer: str, metadata: AnswerMetadata, evidence: EvidenceStore
    ) -> VerificationReport:
        metadata = metadata.model_copy(deep=True)
        known = evidence.items
        removed = re.findall(r"\[(E\d+)\]", answer)
        removed = list(dict.fromkeys(key for key in removed if key not in known))
        answer = re.sub(r"\[(E\d+)\]", lambda m: m[0] if m[1] in known else "", answer)
        active = self.settings.nli_enabled and self.nli is not None
        answer_claims = []
        first_uncited = False
        sentence_number = 0
        for line in answer.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or (line.endswith(":") and "[E" not in line):
                continue
            for sentence in _answer_sentences(line):
                sentence_number += 1
                ids = re.findall(r"\[(E\d+)\]", sentence)
                if not ids and re.match(
                    r"(?:the documents? (?:do not|don't|does not)|I (?:cannot|could not)|"
                    r"insufficient information|it is unclear|what is missing)",
                    sentence,
                    re.I,
                ):
                    continue
                text = re.sub(r"\[E\d+\]", "", sentence).strip()
                if not re.search(r"\w", text):
                    continue
                if sentence_number == 1:
                    first_uncited = not ids
                claim = next(
                    (
                        c
                        for c in metadata.claims
                        if c.text.strip().rstrip(".!?") == text.rstrip(".!?")
                    ),
                    None,
                )
                if claim is None:
                    claim = Claim(text=text, evidence=ids)
                    metadata.claims.append(claim)
                else:
                    claim.evidence = ids
                answer_claims.append((sentence, claim))
        support_pairs = []
        owners = []
        for index, claim in enumerate(metadata.claims):
            claim.evidence = [key for key in claim.evidence if key in known]
            texts = [known[key].chunk.text for key in claim.evidence]
            for text in [*texts, "\n".join(texts)] if texts else []:
                support_pairs.append((_claim_context(text, claim.text), claim.text))
                owners.append(index)
            claim.support_score = 0
            claim.supported = bool(claim.evidence) if not active else False
        if active:
            try:
                predictions = self.nli.predict_batch(support_pairs)
            except LLMError as exc:
                get_logger(__name__).warning("nli_unavailable error=%s", str(exc))
                active = False
                predictions = []
            for index, score in zip(owners if active else [], predictions, strict=True):
                claim = metadata.claims[index]
                claim.support_score = max(claim.support_score, score["entailment"])
                claim.supported = claim.support_score >= self.settings.support_threshold
        for conflict in metadata.contradictions:
            conflict.evidence = [key for key in conflict.evidence if key in known]
        metadata.contradictions = [c for c in metadata.contradictions if len(c.evidence) >= 2]
        existing = {frozenset(c.evidence) for c in metadata.contradictions}
        sentences = []
        for item in known.values():
            text = item.chunk.text
            services = item.chunk.payload.get("entities", {}).get("services", [])
            for start, end in sentence_spans(text, 0, len(text)):
                sentence = text[start:end].strip()
                entities = extract_entities(sentence, services)
                values = {v.lower() for group in entities.values() for v in group}
                sentences.append((item, sentence, values))
        candidates = []
        for left, right in combinations(sentences, 2):
            a, b = left[0], right[0]
            versions_differ = a.chunk.payload.get("version") != b.chunk.payload.get("version")
            if a.chunk.doc_id == b.chunk.doc_id and not versions_differ:
                continue
            ids = frozenset((a.evidence_id, b.evidence_id))
            if any(ids <= group for group in existing):
                continue
            shared = len(left[2] & right[2])
            if shared or (a.chunk.doc_id == b.chunk.doc_id and versions_differ):
                candidates.append((shared, left, right))
        candidates.sort(key=lambda row: row[0], reverse=True)
        candidates = candidates[:40]
        if active:
            pairs = [
                (a[1], b[1])
                for _, left, right in candidates
                for a, b in ((left, right), (right, left))
            ]
            try:
                scores = self.nli.predict_batch(pairs)
            except LLMError as exc:
                get_logger(__name__).warning("nli_unavailable error=%s", str(exc))
                active = False
                scores = []
            for index, (_, left, right) in enumerate(candidates if active else []):
                ids = [left[0].evidence_id, right[0].evidence_id]
                if any(frozenset(ids) <= group for group in existing):
                    continue
                if (
                    max(s["contradiction"] for s in scores[index * 2 : index * 2 + 2])
                    >= self.settings.contradiction_threshold
                ):
                    metadata.contradictions.append(
                        Contradiction(
                            description=(
                                f'"{left[1][:200]}" [{ids[0]}] conflicts with '
                                f'"{right[1][:200]}" [{ids[1]}].'
                            ),
                            evidence=ids,
                        )
                    )
                    existing.add(frozenset(ids))
        if not active:
            for claim in metadata.claims:
                claim.support_score = 0
                claim.supported = bool(claim.evidence)
        unsupported = [sentence for sentence, claim in answer_claims if not claim.supported]
        for sentence in dict.fromkeys(unsupported):
            answer = answer.replace(sentence, sentence + " _(unverified)_")
        best = max((e.chunk.score for e in known.values()), default=float("-inf"))
        ratio_claims = [claim for _, claim in answer_claims] or metadata.claims
        ratio = sum(c.supported for c in ratio_claims) / max(1, len(ratio_claims))
        abstained = (
            metadata.insufficient_information
            or not known
            or best < self.settings.abstain_min_evidence_score
            or (active and ratio < 0.6)
            or first_uncited
            or (not active and not any(c.evidence for c in metadata.claims))
        )
        if abstained:
            metadata.confidence = "low"
            if not metadata.missing:
                metadata.missing.append("Sufficient supported evidence to answer the question.")
            if not metadata.insufficient_information:
                answer = "I could not verify an answer from the indexed documents."
                answer += "\n\n## What is missing\n" + "\n".join(
                    f"- {item}" for item in metadata.missing
                )
                supported = [c for c in metadata.claims if c.supported]
                if supported:
                    answer += "\n\n## Partially supported findings\n" + "\n".join(
                        f"- {c.text} " + " ".join(f"[{key}]" for key in c.evidence)
                        for c in supported
                    )
        return VerificationReport(
            answer=answer,
            abstained=abstained,
            metadata=metadata,
            removed_citations=removed,
            verification_mode="nli" if active else "citations_only",
            unsupported_sentences=unsupported,
        )


def _claim_context(text: str, claim: str) -> str:
    # Reserve space for the hypothesis and pair separators in the NLI token budget.
    budget = max(0, 508 - len(re.findall(r"\w+|[^\w\s]", claim)))
    words = set(re.findall(r"\w+", claim.lower()))
    sentences = [text[a:b] for a, b in sentence_spans(text, 0, len(text))]
    ranked = sorted(
        enumerate(sentences), key=lambda row: -len(words & set(re.findall(r"\w+", row[1].lower())))
    )
    selected = []
    for index, sentence in ranked:
        tokens = list(re.finditer(r"\w+|[^\w\s]", sentence))
        if not budget:
            break
        count = min(budget, len(tokens))
        if count:
            selected.append((index, sentence[: tokens[count - 1].end()]))
            budget -= count
    return " ".join(sentence for _, sentence in sorted(selected))


def _answer_sentences(line: str) -> list[str]:
    boundaries = [0]
    for match in re.finditer(r"[.!?]+(?:[ \t]*\[E\d+\])*[ \t]+(?=\S)(?!\[E\d+\])", line):
        prefix = line[: match.start() + 1]
        if re.search(r"\b(?:e\.g|i\.e|Inc|Dr|Mr|Mrs|Ms|vs|etc)\.$", prefix, re.I):
            continue
        boundaries.append(match.end())
    boundaries.append(len(line))
    return [line[a:b].strip() for a, b in pairwise(boundaries) if line[a:b].strip()]
