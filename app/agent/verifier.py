import re
from itertools import combinations

from pydantic import BaseModel, Field

from app.agent.evidence import EvidenceStore
from app.agent.nli import NliModel
from app.agent.synthesizer import AnswerMetadata, Contradiction
from app.core.config import Settings
from app.ingest.chunking import sentence_spans
from app.ingest.metadata import extract_entities


class VerificationReport(BaseModel):
    answer: str
    abstained: bool
    metadata: AnswerMetadata
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
        support_pairs = []
        owners = []
        for index, claim in enumerate(metadata.claims):
            claim.evidence = [key for key in claim.evidence if key in known]
            texts = [known[key].chunk.text for key in claim.evidence]
            for text in [*texts, "\n".join(texts)] if texts else []:
                support_pairs.append((_claim_context(text, claim.text), claim.text))
                owners.append(index)
            claim.support_score = 0
            claim.supported = False
        if active:
            for index, score in zip(owners, self.nli.predict_batch(support_pairs), strict=True):
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
            scores = self.nli.predict_batch(pairs)
            for index, (_, left, right) in enumerate(candidates):
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
        best = max((e.chunk.score for e in known.values()), default=float("-inf"))
        ratio = sum(c.supported for c in metadata.claims) / max(1, len(metadata.claims))
        abstained = (
            metadata.insufficient_information
            or not known
            or best < self.settings.abstain_min_evidence_score
            or ratio < 0.5
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
            answer=answer, abstained=abstained, metadata=metadata, removed_citations=removed
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
