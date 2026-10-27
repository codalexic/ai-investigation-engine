import re
from itertools import combinations, pairwise

from pydantic import BaseModel, Field

from app.agent.evidence import EvidenceStore
from app.agent.nli import NliModel
from app.agent.synthesizer import AnswerMetadata, Claim, Contradiction
from app.agent.textnorm import normalize_citations, normalize_llm_text
from app.agent.windows import content_tokens
from app.agent.windows import support_windows as _support_windows
from app.core.config import Settings
from app.core.errors import LLMError
from app.core.logging import get_logger
from app.ingest.chunking import sentence_spans
from app.ingest.metadata import DATE_RE, extract_entities


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
        self, answer: str, metadata: AnswerMetadata, evidence: EvidenceStore, question: str = ""
    ) -> VerificationReport:
        metadata = metadata.model_copy(deep=True)
        answer = normalize_citations(normalize_llm_text(answer))
        # Some models announce the metadata block with a label line; it is not answer text.
        answer = re.sub(r"\n\s*\**\s*meta(?:data)?\s*\**\s*:?\s*$", "", answer.rstrip(), flags=re.I)
        for claim in metadata.claims:
            claim.text = normalize_citations(normalize_llm_text(claim.text))
        for conflict in metadata.contradictions:
            conflict.description = normalize_citations(normalize_llm_text(conflict.description))
            if conflict.resolution:
                conflict.resolution = normalize_citations(normalize_llm_text(conflict.resolution))
        known = evidence.items
        removed = re.findall(r"\[(E\d+)\]", answer)
        removed = list(dict.fromkeys(key for key in removed if key not in known))
        answer = re.sub(r"\[(E\d+)\]", lambda m: m[0] if m[1] in known else "", answer)
        active = self.settings.nli_enabled and self.nli is not None
        answer_claims = []
        first_uncited = False
        for line in answer.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or (line.endswith(":") and "[E" not in line):
                continue
            for sentence in _answer_sentences(line):
                ids = re.findall(r"\[(E\d+)\]", sentence)
                if not ids and re.search(
                    r"\b(?:do|does|did)(?: not|n't) "
                    r"(?:contain|mention|include|say|state|specify)\b|"
                    r"\bno (?:information|evidence|mention|record)\b|insufficient information|"
                    r"\bI (?:cannot|could not)\b|\bit is unclear\b|what is missing",
                    sentence,
                    re.I,
                ):
                    continue
                text = re.sub(r"\[E\d+\]", "", sentence).strip()
                # List markers and fragments ("1.", "pdf") are not claims.
                if not re.search(r"[A-Za-z]", text) or re.fullmatch(r"\W*\w{1,4}\W*", text):
                    continue

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
                claim.kind = _claim_kind(text, question, known)
                if claim.kind == "factual" and not any(
                    c.kind == "factual" for _, c in answer_claims
                ):
                    first_uncited = not ids
                answer_claims.append((sentence, claim))
        for claim in metadata.claims:
            claim.kind = _claim_kind(claim.text, question, known)
            claim.evidence = list(dict.fromkeys(k for k in claim.evidence if k in known))
            claim.support_score = claim.grounding_score = 0
            claim.support_method = None
            claim.supported = False
        if active:
            try:
                for claim in metadata.claims:
                    claim.kind = _claim_kind(claim.text, question, known)
                    claim.evidence = list(dict.fromkeys(k for k in claim.evidence if k in known))
                    if claim.kind != "factual":
                        claim.supported = True
                        continue
                    services = [
                        v
                        for item in known.values()
                        for v in item.chunk.payload.get("entities", {}).get("services", [])
                    ]
                    parts = _claim_parts(_strip_markdown(claim.text), services)
                    results = []
                    for part in parts:
                        windows = [
                            w
                            for key in claim.evidence
                            for w in _support_windows(
                                known[key].chunk.text, part, self.settings.nli_window_top_k
                            )
                        ]
                        windows = sorted(
                            set(windows), key=lambda w: (-len(_tokens(w) & _tokens(part)), w)
                        )
                        best_windows = windows[:2]
                        premises = list(windows)
                        if len(claim.evidence) > 1 and windows:
                            premises.append(" ".join(windows[:3]))
                        scores = self.nli.predict_batch([(w, part) for w in premises])
                        entailment = max((v["entailment"] for v in scores), default=0)
                        contradiction = max(
                            (v["contradiction"] for v in scores[: len(best_windows)]), default=1
                        )
                        text = " ".join(known[k].chunk.text for k in claim.evidence)
                        entities = _entities(part, services)
                        quotes = {q.lower() for q in re.findall(r'"([^"\n]+)"', part)}
                        entities.update(quotes)
                        evidence_entities = _entities(text, services)
                        evidence_entities.update(q for q in quotes if q in text.lower())
                        # Grounding compares against all cited text: compound claims draw their
                        # words from several sentences, while entities and NLI guard precision.
                        overlap = len(_tokens(part) & _tokens(text)) / max(1, len(_tokens(part)))
                        grounded = (
                            contradiction < 0.9
                            and entities <= evidence_entities
                            and overlap >= (0.5 if entities else 0.75)
                        )
                        results.append((entailment, overlap, grounded))
                    claim.support_score = min((r[0] for r in results), default=0)
                    claim.grounding_score = min((r[1] for r in results), default=0)
                    claim.supported = all(
                        r[0] >= self.settings.support_threshold or r[2] for r in results
                    )
                    claim.support_method = (
                        "nli"
                        if claim.support_score >= self.settings.support_threshold
                        else "grounding"
                        if claim.supported
                        else None
                    )
            except LLMError as exc:
                get_logger(__name__).warning("nli_unavailable error=%s", str(exc))
                active = False
        for conflict in metadata.contradictions:
            conflict.evidence = [key for key in conflict.evidence if key in known]
        metadata.contradictions = [
            c
            for c in metadata.contradictions
            if len({known[key].chunk.doc_id for key in c.evidence}) >= 2
        ]
        existing = {frozenset(c.evidence) for c in metadata.contradictions}
        # Every candidate pair must involve evidence the answer relies on; conflicts between two
        # uncited chunks (e.g. another incident) are true but irrelevant to this question.
        cited = set(re.findall(r"\[(E\d+)\]", answer)) | {
            key for claim in metadata.claims for key in claim.evidence
        }
        cited &= set(known)
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
            if cited and a.evidence_id not in cited and b.evidence_id not in cited:
                continue
            versions_differ = a.chunk.payload.get("version") != b.chunk.payload.get("version")
            if a.chunk.doc_id == b.chunk.doc_id and not versions_differ:
                continue
            ids = frozenset((a.evidence_id, b.evidence_id))
            if any(ids <= group for group in existing):
                continue
            shared = len(left[2] & right[2])
            tokens_a, tokens_b = _tokens(left[1]), _tokens(right[1])
            overlap = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
            if shared and overlap >= 0.2:
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
                    min(s["contradiction"] for s in scores[index * 2 : index * 2 + 2])
                    >= self.settings.contradiction_threshold
                    and max(s["entailment"] for s in scores[index * 2 : index * 2 + 2]) < 0.3
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
                if claim.kind == "factual":
                    claim.supported = bool(claim.evidence)
        unsupported = [
            sentence
            for sentence, claim in answer_claims
            if claim.kind == "factual" and not claim.supported
        ]
        for sentence in dict.fromkeys(unsupported):
            # Anchor on a sentence boundary so "INC-2031." never matches inside "INC-2031.pdf".
            answer = re.sub(
                re.escape(sentence) + r"(?=\s|$)",
                lambda m: m[0] + " _(unverified)_",
                answer,
                count=1,
            )
        best = max((e.chunk.score for e in known.values()), default=float("-inf"))
        ratio_claims = [claim for _, claim in answer_claims] or metadata.claims
        factual = [c for c in ratio_claims if c.kind == "factual"]
        first_unsupported = bool(factual and not factual[0].supported)
        uncited = sum(not c.evidence for c in factual)
        ratio_claims = [c for c in factual if c.evidence]
        ratio = (
            sum(c.supported for c in ratio_claims) / max(1, len(ratio_claims))
            if ratio_claims
            else 1.0
        )
        abstained = (
            metadata.insufficient_information
            or not known
            or best < self.settings.abstain_min_evidence_score
            or (active and ratio < 0.6)
            or first_uncited
            or uncited > len(ratio_claims)
            or (not active and not any(c.evidence for c in metadata.claims))
        )
        # An unsupported opening sentence is marked _(unverified)_ and lowers confidence; the
        # overall support ratio decides abstention.
        if not abstained and first_unsupported and metadata.confidence == "high":
            metadata.confidence = "medium"
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


def _strip_markdown(text: str) -> str:
    return re.sub(r"(\*\*|__|`)", "", re.sub(r"^\s*[-*•]\s+", "", text))


def _tokens(text: str) -> set[str]:
    return content_tokens(text)


def _claim_kind(text: str, question: str, known: dict) -> str:
    if re.search(r"\bid E\d+\b|\b(?:syn|hotpot|pm):[\w.-]+", text, re.I) and not re.search(
        r"\b(?:caused|failed|was|occurred)\b", text, re.I
    ):
        return "citation"
    plain = _strip_markdown(text)
    if text.lstrip().startswith("#") or plain.rstrip().endswith(":"):
        return "excluded"
    # A line that is entirely bold/italic markup is a label ("**Supporting chain**").
    if re.fullmatch(r"\s*[-*]?\s*(\*\*|__|\*|_)[^*_]+\1\s*:?\s*", text):
        return "excluded"
    # "The final review [E1] and the RCA [E11] confirm this" only points at sources.
    if not any(extract_entities(plain).values()) and re.search(
        r"\b(?:confirm|confirms|confirmed|corroborate[sd]?|support|supports)\b", plain, re.I
    ):
        return "citation"
    if question and _tokens(text) == _tokens(question):
        return "excluded"
    stripped = re.sub(r"\[E\d+\]", "", text)
    for item in known.values():
        stripped = re.sub(r"(?<![\w-])" + re.escape(item.chunk.doc_id) + r"(?![\w-])", "", stripped)
    stripped = re.sub(r"\b[\w]+:[\w.-]+", "", stripped)
    filler = set(
        [
            "documents",
            "document",
            "confirm",
            "confirms",
            "confirming",
            "sources",
            "source",
            "evidence",
            "see",
            "this",
            "are",
            "is",
            "and",
            "the",
        ]
    )
    return "citation" if not (set(re.findall(r"[\w-]+", stripped.lower())) - filler) else "factual"


def _answer_sentences(line: str) -> list[str]:
    boundaries = [0]
    for match in re.finditer(r"[.!?]+(?:[ \t]*\[E\d+\])*[ \t]+(?=\S)(?!\[E\d+\])", line):
        prefix = line[: match.start() + 1]
        if re.search(r"\b(?:e\.g|i\.e|Inc|Dr|Mr|Mrs|Ms|vs|etc)\.$", prefix, re.I):
            continue
        boundaries.append(match.end())
    boundaries.append(len(line))
    return [line[a:b].strip() for a, b in pairwise(boundaries) if line[a:b].strip()]


def _entities(text: str, services: list[str]) -> set[str]:
    text = normalize_llm_text(text).lower()
    groups = extract_entities(text, [s.lower() for s in services])
    values = {v.lower() for group in groups.values() for v in group}
    values.update(re.findall(r"(?<![\w-])\d+(?:[.,]\d+)*(?:%?)(?![\w-])", DATE_RE.sub("", text)))
    return values


def _claim_parts(text: str, services: list[str]) -> list[str]:
    for match in re.finditer(r"; |, and ", text):
        left, right = text[: match.start()], text[match.end() :]
        if (_entities(left, services) or re.search(r'"[^"\n]+"', left)) and (
            _entities(right, services) or re.search(r'"[^"\n]+"', right)
        ):
            return _claim_parts(left, services) + _claim_parts(right, services)
    return [text]
