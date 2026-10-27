from itertools import pairwise

from app.agent.textnorm import normalize_llm_text
from app.ingest.chunking import sentence_spans
from app.ingest.metadata import extract_entities
from app.retrieval.text import analyze


def content_tokens(text: str) -> set[str]:
    return set(analyze(normalize_llm_text(text)))


def support_windows(text: str, claim: str, top_k: int) -> list[str]:
    text = normalize_llm_text(text)
    sentences = [text[a:b].strip() for a, b in sentence_spans(text, 0, len(text))]
    windows = list(dict.fromkeys([*sentences, *(a + " " + b for a, b in pairwise(sentences))]))
    return sorted(windows, key=lambda window: -len(content_tokens(window) & content_tokens(claim)))[
        :top_k
    ]


def evidence_excerpt(text: str, query: str, max_sentences: int = 4) -> str:
    """Keep the sentences an investigator needs: query overlap, identifiers and the opening line.

    Sentences naming change/incident ids, services or dates carry most investigative facts even when
    they share few words with the question, so each entity counts double. Original order is kept.
    """
    text = normalize_llm_text(text)
    sentences = [text[a:b].strip() for a, b in sentence_spans(text, 0, len(text))]
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    wanted = content_tokens(query)

    def score(index: int) -> float:
        sentence = sentences[index]
        entities = sum(len(values) for values in extract_entities(sentence).values())
        return len(content_tokens(sentence) & wanted) + 2 * entities + (1 if index == 0 else 0)

    keep = sorted(sorted(range(len(sentences)), key=score, reverse=True)[:max_sentences])
    return " ".join(sentences[i] for i in keep)
