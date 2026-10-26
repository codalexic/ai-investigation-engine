from contextlib import ExitStack
from dataclasses import dataclass
from time import perf_counter

from fastapi import Request
from sqlalchemy.engine import Engine

from app.agent.engine import InvestigationEngine
from app.agent.nli import FakeNli, OnnxNliModel
from app.core.config import Settings
from app.core.logging import get_logger
from app.ingest.chunking import Chunker, build_chunker
from app.ingest.dedup import LSHIndex, MinHasher
from app.ingest.pipeline import IngestionPipeline
from app.ingest.registry import DocumentRegistry, make_engine
from app.llm.cache import CachedClient
from app.llm.client import FallbackClient, LLMClient, build_llm
from app.retrieval.bm25 import Bm25Statistics
from app.retrieval.factory import build_retrieval
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.store import QdrantStore


@dataclass
class Container:
    settings: Settings
    engine: Engine
    registry: DocumentRegistry
    store: QdrantStore
    retriever: HybridRetriever
    pipeline: IngestionPipeline
    llm: LLMClient | None
    investigator: InvestigationEngine | None

    @classmethod
    def build(cls, settings: Settings) -> "Container":
        with ExitStack() as resources:
            engine = make_engine(settings.database_url)
            resources.callback(engine.dispose)
            registry = DocumentRegistry(engine)
            store, retriever = build_retrieval(settings, engine)
            resources.callback(store.client.close)
            pipeline = IngestionPipeline(
                registry, store, build_chunker(settings), MinHasher(), LSHIndex()
            )
            started = perf_counter()
            pipeline.rebuild_lsh()
            get_logger(__name__).info(
                "lsh_rebuilt", extra={"duration_ms": (perf_counter() - started) * 1000}
            )
            providers = [
                p for p in settings.llm_provider_order if getattr(settings, f"{p}_api_key", None)
            ]
            llm = (
                build_llm(settings.model_copy(update={"llm_cache_enabled": False}))
                if providers
                else None
            )
            if llm:
                resources.callback(close_llm, llm)
            if llm and settings.llm_cache_enabled:
                llm = CachedClient(llm, engine)
            nli = (
                FakeNli()
                if settings.app_env == "test"
                else OnnxNliModel(settings.nli_model, settings.model_cache_dir)
            )
            investigator = (
                InvestigationEngine(
                    retriever, store, llm, nli if settings.nli_enabled else None, settings
                )
                if llm
                else None
            )
            result = cls(settings, engine, registry, store, retriever, pipeline, llm, investigator)
            resources.pop_all()
            return result

    def warm_models(self) -> None:
        try:
            self.store.embedder.embed_query("warmup")
            if self.settings.rerank_enabled:
                _ = self.retriever.reranker.model
            if self.settings.nli_enabled:
                nli = self.investigator.nli if self.investigator else None
                if not isinstance(nli, OnnxNliModel):
                    nli = OnnxNliModel(self.settings.nli_model, self.settings.model_cache_dir)
                nli._load()
        except Exception:
            get_logger(__name__).exception("model_warmup_failed")

    def close(self) -> None:
        try:
            close_llm(self.llm)
        finally:
            try:
                self.store.client.close()
            finally:
                self.engine.dispose()

    @property
    def bm25_stats(self) -> Bm25Statistics:
        return self.store.bm25.stats

    @property
    def chunker(self) -> Chunker:
        return self.pipeline.chunker

    @property
    def minhasher(self) -> MinHasher:
        return self.pipeline.minhasher

    @property
    def lsh(self) -> LSHIndex:
        return self.pipeline.lsh


def close_llm(llm: LLMClient | None) -> None:
    inner = llm.inner if isinstance(llm, CachedClient) else llm
    clients = inner.clients if isinstance(inner, FallbackClient) else [inner] if inner else []
    for client in clients:
        close = getattr(client, "close", None)
        if close:
            close()


def get_container(request: Request) -> Container:
    return request.app.state.container
