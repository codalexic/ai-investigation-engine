import os
from unittest.mock import Mock

import numpy as np
import pytest

from app.core.errors import RetrievalError
from app.retrieval.embeddings import FastEmbedEmbedder
from app.retrieval.rerank import CrossEncoderReranker, FakeReranker, NoopReranker
from app.retrieval.store import ScoredChunk


def test_rerankers(monkeypatch):
    chunks = [ScoredChunk("a", 2, {"text": "dog"}), ScoredChunk("b", 1, {"text": "cat dog"})]
    assert NoopReranker().rerank("cat", chunks, 1) == [(chunks[0], 2)]
    assert FakeReranker().rerank("cat", chunks, 2)[0] == (chunks[1], 1)
    model = Mock()
    model.rerank.return_value = iter([0.1, 0.9])
    constructor = Mock(return_value=model)
    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", constructor)
    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert reranker._model is None
    assert reranker.rerank("cat", chunks, 1) == [(chunks[1], 0.9)]
    constructor.assert_called_once_with(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
    model.rerank.side_effect = RuntimeError("failure")
    with pytest.raises(RetrievalError):
        reranker.rerank("cat", chunks, 1)
    assert reranker.rerank("cat", [], 1) == []


@pytest.mark.models
@pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="RUN_MODEL_TESTS=1 required")
def test_real_models():
    embedder = FastEmbedEmbedder("BAAI/bge-small-en-v1.5")
    vectors = embedder.embed_documents(["payment service rollback"])
    assert vectors.shape == (1, embedder.dim)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
    assert embedder.embed_query("payment rollback").shape == (embedder.dim,)
    chunks = [ScoredChunk("a", 0, {"text": "payment service rollback"})]
    assert (
        len(
            CrossEncoderReranker("Xenova/ms-marco-MiniLM-L-6-v2").rerank(
                "payment rollback", chunks, 1
            )
        )
        == 1
    )
