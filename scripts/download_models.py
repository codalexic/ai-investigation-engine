"""Populate the runtime model cache during image construction."""

import argparse

from app.core.config import Settings
from app.retrieval.embeddings import FastEmbedEmbedder


def download_models(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    _ = FastEmbedEmbedder(settings.embedding_model, cache_dir=settings.model_cache_dir).model
    if settings.rerank_enabled:
        from app.retrieval.rerank import CrossEncoderReranker

        _ = CrossEncoderReranker(settings.reranker_model, cache_dir=settings.model_cache_dir).model
    if settings.nli_enabled:
        from app.agent.nli import OnnxNliModel

        OnnxNliModel(settings.nli_model, settings.model_cache_dir)._load()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["full", "lite"], default="full")
    download_models(Settings(deployment_profile=parser.parse_args().profile))
