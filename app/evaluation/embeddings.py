import json
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.corpus.common import short_hash, slug, write_jsonl
from app.corpus.hotpotqa import parse_rows
from app.corpus.indexer import run as index_corpus
from app.evaluation.common import questions, write_result
from app.evaluation.connection import connect
from app.evaluation.retrieval_eval import run as retrieval_run


def subset_records(root: Path, selected: list[dict]) -> list[dict]:
    import pyarrow.parquet as pq

    wanted = {q["id"] for q in selected}
    found = {}
    for path in sorted((root / "data/raw").rglob("*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
            for row in batch.to_pylist():
                if row["id"] in wanted:
                    found[row["id"]] = row
        if wanted <= found.keys():
            break
    if not wanted <= found.keys():
        raise ConfigurationError(
            "Missing cached HotpotQA contexts; run scripts/build_hotpotqa.py first"
        )
    records, _, _ = parse_rows([found[q["id"]] for q in selected])
    return records


def run(
    settings: Settings,
    models: list[str],
    subset_questions: int = 300,
    root: Path = Path("."),
    limit: int | None = None,
    k: int = 10,
    records: list[dict] | None = None,
) -> dict:
    if subset_questions < 1 or (limit is not None and limit < 0) or k < 1:
        raise ConfigurationError("Subset size must be positive")
    selected = questions(str(root / "eval/data/hotpotqa_questions.jsonl"), subset_questions)
    if limit is not None:
        selected = selected[:limit]
    records = subset_records(root, selected) if records is None else records
    configs = {}
    for model in models:
        scope = json.dumps(
            [
                model,
                [q["id"] for q in selected],
                records,
                settings.chunk_strategy,
                settings.chunk_size,
                settings.chunk_min_tokens,
                settings.chunk_overlap,
            ],
            sort_keys=True,
        )
        name = "emb_" + slug(model) + "_" + short_hash(scope)
        working = root / "eval/cache/embedding_inputs" / name
        write_jsonl(working / "data/corpus/hotpotqa.jsonl", records)
        registry = (working / "registry.db").resolve().as_posix()
        overrides = {
            "qdrant_collection": name,
            "database_url": f"sqlite:///{registry}",
            "embedding_model": model,
            "llm_provider_order": [],
        }
        current = settings.model_copy(update=overrides)
        started = perf_counter()
        index_result = index_corpus(current, ["hotpotqa"], root=working)
        index_seconds = perf_counter() - started
        with connect(current) as connection:
            scores = retrieval_run(connection.retriever, selected, ["dense", "hybrid"], (k,))
        for mode, value in scores["configs"].items():
            configs[f"{model}/{mode}"] = {
                **value,
                "model": model,
                "collection": name,
                "index_seconds": index_seconds,
                "indexing": index_result,
                "subset_questions": len(selected),
                "paragraphs": len(records),
            }
    result = {"kind": "embeddings", "configs": configs}
    write_result(root / "eval/results/embeddings.json", result)
    return result
