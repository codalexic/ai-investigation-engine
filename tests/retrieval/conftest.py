from datetime import date
from unittest.mock import Mock

import numpy as np
import pytest
from sqlalchemy import create_engine

from app.core.config import Settings
from app.ingest.models import Chunk
from app.retrieval.factory import build_retrieval


@pytest.fixture
def retrieval():
    engine = create_engine("sqlite:///:memory:")
    store, retriever = build_retrieval(Settings(_env_file=None, app_env="test"), engine)
    yield store, retriever
    store.client.close()
    engine.dispose()


@pytest.fixture
def chunk():
    def make(key="a", text="payment-service rollback CHG-1042", index=0, doc_id="doc", **metadata):
        return Chunk(
            key,
            doc_id,
            1,
            index,
            text,
            [],
            0,
            len(text),
            len(text.split()),
            {
                "title": "Title",
                "doc_type": "runbook",
                "source": "test.md",
                "created_at": date(2025, 3, 12).isoformat(),
                "entities": {"services": ["payment-service"], "change_ids": ["CHG-1042"]},
                **metadata,
            },
        )

    return make


@pytest.fixture
def fake_model():
    model = Mock()
    model.embedding_size = 3
    model.embed.side_effect = lambda texts, **kw: iter([np.array([3, 4, 0]) for _ in texts])
    model.query_embed.side_effect = lambda text: iter([np.array([0, 0, 2])])
    return model
