"""Populate the runtime model cache during image construction."""

from app.agent.nli import OnnxNliModel
from app.core.config import Settings
from app.retrieval.embeddings import FastEmbedEmbedder
from app.retrieval.rerank import CrossEncoderReranker


def download_models(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    _ = FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir).model
    _ = CrossEncoderReranker(settings.reranker_model, cache_dir=settings.model_cache_dir).model
    OnnxNliModel(settings.nli_model, settings.model_cache_dir)._load()


if __name__ == "__main__":
    download_models()
