import argparse
from contextlib import ExitStack
from pathlib import Path

from sqlalchemy import create_engine

from app.agent.engine import InvestigationEngine
from app.agent.nli import FakeNli, OnnxNliModel
from app.container import close_llm
from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.evaluation.cache import EvaluationCachedClient
from app.evaluation.common import questions, safe_name
from app.evaluation.connection import connect
from app.llm.client import build_llm

logger = get_logger(__name__)


def benchmark_main() -> None:
    from app.evaluation.benchmark import run, select_questions

    parser = argparse.ArgumentParser(
        description="Benchmark retrieval on the existing documents index"
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", default="1,4,8")
    args = parser.parse_args()
    selected = select_questions(limit=args.limit)
    settings = settings_for("documents", "sqlite:///./data/registry_documents.db")
    if settings.app_env == "test":
        raise ConfigurationError("The benchmark CLI requires real models")
    with connect(settings) as connection:
        run(
            connection,
            selected,
            tuple(int(c) for c in args.concurrency.split(",")),
            Path("eval/results/benchmark.json"),
        )


def settings_for(collection: str, database_url: str | None = None) -> Settings:
    safe_name(collection)
    overrides = {"qdrant_collection": collection}
    if database_url:
        overrides["database_url"] = database_url
    elif (
        collection != Settings().qdrant_collection
        or Settings().database_url == "sqlite:///./data/app.db"
    ):
        overrides["database_url"] = f"sqlite:///./data/registry_{collection}.db"
    return Settings(**overrides)


def retrieval_main() -> None:
    from app.evaluation.retrieval_eval import CONFIGS, run

    parser = argparse.ArgumentParser(description="Evaluate document retrieval on existing indexes")
    parser.add_argument("--collection", default="documents")
    parser.add_argument("--database-url")
    parser.add_argument(
        "--questions", default="eval/data/hotpotqa_questions.jsonl,eval/questions.jsonl"
    )
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--k", default="5,10,20")
    args = parser.parse_args()
    with connect(settings_for(args.collection, args.database_url)) as connection:
        run(
            connection.retriever,
            questions(args.questions, args.limit),
            args.configs.split(","),
            tuple(int(k) for k in args.k.split(",")),
            Path(f"eval/results/retrieval_{safe_name(args.collection)}.json"),
        )


def chunking_main() -> None:
    from app.evaluation.chunking import run

    parser = argparse.ArgumentParser(description="Compare existing chunking collections")
    parser.add_argument("--collections", default="documents,documents_fixed")
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    names = args.collections.split(",")
    if len(names) != 2 or names[0] == names[1]:
        raise ConfigurationError("Specify two different collections")
    with ExitStack() as stack:
        connections = {
            name: stack.enter_context(
                connect(settings_for(name, f"sqlite:///./data/registry_{safe_name(name)}.db"))
            )
            for name in names
        }
        run(
            connections,
            questions(args.questions, args.limit),
            args.k,
            Path("eval/results/chunking.json"),
        )


def embeddings_main() -> None:
    from app.evaluation.embeddings import run

    parser = argparse.ArgumentParser(description="Compare embeddings in isolated collections")
    parser.add_argument(
        "--models", default="BAAI/bge-small-en-v1.5,sentence-transformers/all-MiniLM-L6-v2"
    )
    parser.add_argument("--subset-questions", type=int, default=300)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    run(Settings(), args.models.split(","), args.subset_questions, limit=args.limit, k=args.k)


def e2e_main() -> None:
    from app.evaluation.e2e import CONFIGS, run

    parser = argparse.ArgumentParser(
        description="Evaluate investigation quality with resumable caches"
    )
    parser.add_argument("--config", choices=CONFIGS, default="full")
    parser.add_argument("--collection", default="documents")
    parser.add_argument("--database-url")
    parser.add_argument("--questions", default="eval/questions.jsonl")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--judge", choices=("auto", "none", "groq", "gemini", "openrouter"), default="auto"
    )
    parser.add_argument("--pause", type=float, default=2)
    args = parser.parse_args()
    settings = settings_for(args.collection, args.database_url)
    provider = "gemini" if args.config == "gemini" else "groq"
    generator_settings = settings.model_copy(
        update={
            "llm_provider_order": [provider],
            "llm_cache_enabled": False,
            "llm_primary_model": "openai/gpt-oss-20b"
            if args.config == "small_model"
            else settings.llm_primary_model,
        }
    )
    selected = questions(args.questions, args.limit)
    with ExitStack() as stack:
        connection = stack.enter_context(connect(settings))
        cache_path = Path("eval/cache/llm.db")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_engine = create_engine(f"sqlite:///{cache_path.as_posix()}")
        stack.callback(cache_engine.dispose)
        generator = build_llm(generator_settings)
        stack.callback(close_llm, generator)
        generator = EvaluationCachedClient(generator, cache_engine)
        judge = None
        available = [
            p for p in ("gemini", "groq", "openrouter") if getattr(settings, p + "_api_key")
        ]
        judge_provider = args.judge
        if judge_provider == "auto":
            judge_provider = next(
                (p for p in available if p != provider), available[0] if available else "none"
            )
        if judge_provider != "none":
            judge_settings = settings.model_copy(
                update={"llm_provider_order": [judge_provider], "llm_cache_enabled": False}
            )
            judge = build_llm(judge_settings, judge=True)
            stack.callback(close_llm, judge)
            judge = EvaluationCachedClient(judge, cache_engine)
        else:
            logger.warning("evaluation_judge_unavailable scores=missing")
        nli = FakeNli() if settings.app_env == "test" else OnnxNliModel(settings.nli_model)
        investigator = InvestigationEngine(
            connection.retriever,
            connection.store,
            generator,
            nli if settings.nli_enabled else None,
            settings,
        )
        result = run(
            investigator,
            selected,
            args.config,
            judge,
            output=Path(f"eval/results/e2e_{args.config}.json"),
            pause=args.pause,
        )
        if result["stopped_on_rate_limit"]:
            logger.warning(
                "Resume after quota recovery: rerun the same eval_e2e.py "
                "command; completed questions are cached."
            )


def dataset_main() -> None:
    from app.evaluation.dataset import build

    parser = argparse.ArgumentParser(description="Assemble and validate the evaluation dataset")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    build(args.root)


def report_main() -> None:
    from app.evaluation.report import build

    parser = argparse.ArgumentParser(description="Build the evaluation report from saved results")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    build(args.root)
