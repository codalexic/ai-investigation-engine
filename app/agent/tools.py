from datetime import date
from html import escape
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.evidence import EvidenceStore
from app.core.errors import RetrievalError
from app.ingest.metadata import extract_entities, parse_date
from app.llm.types import ToolSpec
from app.retrieval.hybrid import HybridRetriever, RetrievalConfig, RetrievedChunk
from app.retrieval.store import QdrantStore, QueryFilters, ScoredChunk
from app.security.injection import sanitize_evidence


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchArgs(Arguments):
    query: str = Field(min_length=1)
    doc_types: list[str] | None = None
    services: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class DocumentArgs(Arguments):
    doc_id: str = Field(min_length=1)
    max_chunks: int = Field(default=12, ge=1, le=50)


class RelatedArgs(Arguments):
    entity: str = Field(min_length=1)


class TimelineArgs(Arguments):
    service: str | None = None
    date_from: str | None = None
    date_to: str | None = None


ARGUMENTS = {
    "search_documents": SearchArgs,
    "get_document": DocumentArgs,
    "find_related": RelatedArgs,
    "timeline": TimelineArgs,
}
TOOL_SPECS = [
    ToolSpec(name=name, description=name.replace("_", " "), parameters=model.model_json_schema())
    for name, model in ARGUMENTS.items()
]


class InvestigationTools:
    def __init__(
        self,
        retriever: HybridRetriever,
        store: QdrantStore,
        evidence: EvidenceStore,
        filters: QueryFilters | None = None,
        retrieval_config: RetrievalConfig | dict[str, Any] | None = None,
    ) -> None:
        self.retriever, self.store, self.evidence = retriever, store, evidence
        self.filters = filters or QueryFilters()
        self.config = retrieval_config
        self.date_range: tuple[date, date] | None = None

    def _filters(self, **values: Any) -> QueryFilters:
        base = self.filters.model_dump(exclude_none=True)
        for key, value in values.items():
            if value is None:
                continue
            if key in base and isinstance(value, list):
                base[key] = [v for v in value if v in base[key]]
            elif key == "date_from" and key in base:
                base[key] = max(
                    base[key], date.fromisoformat(value) if isinstance(value, str) else value
                )
            elif key == "date_to" and key in base:
                base[key] = min(
                    base[key], date.fromisoformat(value) if isinstance(value, str) else value
                )
            else:
                base[key] = value
        return QueryFilters.model_validate(base)

    def _scroll(self, filters: QueryFilters) -> list[ScoredChunk]:
        chunks, offset = [], None
        while len(chunks) < 256:
            points, offset = self.store.client.scroll(
                self.store.collection,
                scroll_filter=filters.to_qdrant(),
                limit=min(64, 256 - len(chunks)),
                offset=offset,
                with_payload=True,
            )
            chunks.extend(self.store._scored(p) for p in points)
            if offset is None:
                break
        return chunks

    def _summary(
        self, chunks: list[RetrievedChunk] | list[ScoredChunk], tool: str, query: str
    ) -> str:
        rows = []
        for chunk in chunks:
            if not isinstance(chunk, RetrievedChunk):
                chunk = RetrievedChunk(
                    chunk.chunk_id,
                    chunk.payload["doc_id"],
                    chunk.payload["text"],
                    chunk.payload,
                    chunk.score,
                    {},
                )
            key = self.evidence.add(chunk, tool, query)
            text, _ = sanitize_evidence(chunk.text)
            text = escape(text[:300], quote=False)
            attrs = {
                "id": key,
                "doc_id": chunk.doc_id,
                "title": chunk.payload.get("title", ""),
                "date": chunk.payload.get("created_at")
                or ", ".join(chunk.payload.get("entities", {}).get("dates", [])),
            }
            header = " ".join(f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items())
            rows.append(f"<evidence {header}>{text}</evidence>")
        return "\n".join(rows) or "No evidence found."

    def search_documents(self, args: SearchArgs) -> str:
        data = args.model_dump(exclude={"query", "top_k"}, exclude_none=True)
        config = (
            self.config.model_dump()
            if isinstance(self.config, RetrievalConfig)
            else dict(self.config or {})
        )
        config["top_k"] = args.top_k
        chunks = self.retriever.search(
            args.query, config=config, filters=self._filters(**data), date_range=self.date_range
        ).chunks
        return self._summary(chunks, "search_documents", args.query)

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in ARGUMENTS:
            return f"Tool error: unknown tool {name}"
        try:
            args = ARGUMENTS[name].model_validate(arguments)
            if name == "search_documents":
                return self.search_documents(args)
            if name == "get_document":
                if self.filters.model_dump(exclude_none=True):
                    chunks = self._scroll(self._filters(doc_ids=[args.doc_id]))
                else:
                    chunks = self.store.get_document_chunks(args.doc_id)
                chunks.sort(key=lambda c: c.payload.get("index", 0))
                chunks = chunks[: args.max_chunks]
            elif name == "find_related":
                entities = extract_entities(args.entity)
                fields = {k: v for k, v in entities.items() if v and k != "dates"}
                if not fields:
                    fields = {"services": [args.entity]}
                chunks = self._scroll(self._filters(**fields))[:50]
            else:
                filters = self._filters(
                    services=[args.service] if args.service else None,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    doc_types=["incident_report", "postmortem", "changelog", "change"],
                )
                chunks = self._scroll(
                    filters.model_copy(update={"date_from": None, "date_to": None})
                )
                dated = []
                for chunk in chunks:
                    values = [
                        chunk.payload.get("created_at"),
                        *chunk.payload.get("entities", {}).get("dates", []),
                    ]
                    dates = sorted(
                        {
                            day
                            for value in values
                            if (
                                day := parse_date(value)
                                or parse_date(value[:10] if isinstance(value, str) else value)
                            )
                        }
                    )
                    for day in dates:
                        if filters.date_from and day < filters.date_from:
                            continue
                        if filters.date_to and day > filters.date_to:
                            continue
                        dated.append(
                            ScoredChunk(
                                chunk.chunk_id,
                                chunk.score,
                                {**chunk.payload, "created_at": day.isoformat()},
                            )
                        )
                chunks = sorted(dated, key=lambda chunk: chunk.payload["created_at"])
            return self._summary(chunks, name, str(arguments))
        except (ValidationError, ValueError, RetrievalError) as exc:
            return f"Tool error: {exc}"
        except Exception as exc:
            from app.core.logging import get_logger

            get_logger(__name__).warning(
                "tool_failed tool=%s error_type=%s", name, type(exc).__name__
            )
            return f"Tool error: {name} could not complete"
