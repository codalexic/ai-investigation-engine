from dataclasses import dataclass, field
from html import escape

from app.llm.tokens import fit_to_budget
from app.retrieval.hybrid import RetrievedChunk
from app.security.injection import sanitize_evidence


@dataclass
class Evidence:
    evidence_id: str
    chunk: RetrievedChunk
    discoveries: list[dict] = field(default_factory=list)


class EvidenceStore:
    def __init__(self) -> None:
        self.items: dict[str, Evidence] = {}
        self.chunk_ids: dict[str, str] = {}

    def add(self, chunk: RetrievedChunk, tool: str = "search_documents", query: str = "") -> str:
        key = self.chunk_ids.get(chunk.chunk_id)
        if key is None:
            key = f"E{len(self.items) + 1}"
            self.chunk_ids[chunk.chunk_id] = key
            self.items[key] = Evidence(key, chunk)
        item = self.items[key]
        if chunk.score > item.chunk.score:
            item.chunk = chunk
        discovery = {"tool": tool, "query": query, "explain": chunk.explain}
        if discovery not in item.discoveries:
            item.discoveries.append(discovery)
        return key

    def render(self, budget_tokens: int) -> str:
        blocks = []
        for item in sorted(self.items.values(), key=lambda e: e.chunk.score, reverse=True):
            chunk = item.chunk
            text, _ = sanitize_evidence(chunk.text)
            text = escape(text, quote=False).replace(
                "&amp;lt;/evidence&amp;gt;", "&lt;/evidence&gt;"
            )
            attrs = {
                "id": item.evidence_id,
                "doc_id": chunk.doc_id,
                "title": chunk.payload.get("title", ""),
                "date": chunk.payload.get("created_at", ""),
            }
            header = " ".join(
                f'{key}="{escape(str(value), quote=True)}"' for key, value in attrs.items()
            )
            blocks.append(f"<evidence {header}>\n{text}\n</evidence>")
        return "\n".join(fit_to_budget(blocks, budget_tokens))
