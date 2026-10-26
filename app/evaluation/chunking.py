import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from app.core.errors import ConfigurationError
from app.evaluation.common import aggregate, write_result
from app.evaluation.connection import EvaluationConnection
from app.evaluation.metrics import mrr, normalize, recall_at_k
from app.evaluation.retrieval_eval import retrieval_config
from app.llm.tokens import count_tokens
from app.retrieval.store import QdrantStore


def collection_statistics(store: QdrantStore) -> dict:
    docs = Counter()
    tokens = []
    offset = None
    while True:
        points, offset = store.client.scroll(
            store.collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for point in points:
            payload = point.payload or {}
            docs[payload["doc_id"]] += 1
            tokens.append(payload.get("token_count") or count_tokens(payload.get("text", "")))
        if offset is None:
            break
    return {
        "documents": sorted(docs),
        "document_count": len(docs),
        "chunk_count": len(tokens),
        "mean_chunk_tokens": sum(tokens) / len(tokens) if tokens else 0,
        "chunks_per_document": sum(docs.values()) / len(docs) if docs else 0,
    }


def run(
    connections: dict[str, EvaluationConnection],
    questions: list[dict],
    k: int = 10,
    output: Path | None = None,
) -> dict:
    if k < 1:
        raise ConfigurationError("Chunking cutoff must be positive")
    stats = {name: collection_statistics(c.store) for name, c in connections.items()}
    document_sets = [s["documents"] for s in stats.values()]
    if document_sets and any(ids != document_sets[0] for ids in document_sets):
        raise ConfigurationError("Chunking comparison requires identical document sets")
    configs = {}
    for name, connection in connections.items():
        rows = []
        for q in questions:
            if (
                q["source"] != "synthetic"
                or not q["gold_doc_ids"]
                or q["expected_behavior"] != "answer"
            ):
                continue
            started = perf_counter()
            chunks = connection.retriever.search(
                q["question"], config=retrieval_config("hybrid", k)
            ).chunks
            evidence = [q["reference_answer"]]
            if q.get("notes", "").startswith("{"):
                evidence.extend(json.loads(q["notes"]).values())
            evidence = [normalize(text) for text in evidence if normalize(text)]
            context = 0
            first_hit = None
            for chunk in chunks:
                context += chunk.payload.get("token_count") or count_tokens(chunk.text)
                if any(text in normalize(chunk.text) for text in evidence):
                    first_hit = context
                    break
            rows.append(
                {
                    **q,
                    "latency_ms": (perf_counter() - started) * 1000,
                    "metrics": {
                        f"evidence-hit@{k}": float(first_hit is not None),
                        f"Recall@{k}": recall_at_k(chunks, q["gold_doc_ids"], k),
                        f"MRR@{k}": mrr(chunks, q["gold_doc_ids"], k),
                        "context_tokens_to_first_hit": first_hit,
                    },
                }
            )
        configs[name] = {
            "summary": aggregate(rows),
            "statistics": {key: value for key, value in stats[name].items() if key != "documents"},
            "rows": rows,
        }
    result = {"kind": "chunking", "k": k, "configs": configs}
    if output:
        write_result(output, result)
    return result
