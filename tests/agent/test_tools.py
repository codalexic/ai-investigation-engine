import pytest
from sqlalchemy import create_engine

from app.agent.evidence import EvidenceStore
from app.agent.tools import InvestigationTools
from app.core.config import Settings
from app.ingest.models import Chunk
from app.retrieval.factory import build_retrieval
from app.retrieval.store import QueryFilters


@pytest.fixture
def tools():
    engine = create_engine("sqlite:///:memory:")
    store, retriever = build_retrieval(Settings(_env_file=None, app_env="test"), engine)
    store.upsert_chunks(
        [
            Chunk(
                key,
                doc,
                1,
                index,
                text,
                [],
                0,
                len(text),
                5,
                {
                    "title": "Incident",
                    "doc_type": "incident_report",
                    "created_at": day,
                    "entities": {"services": [service], "incident_ids": ["INC-1"]},
                },
            )
            for key, doc, index, text, day, service in [
                ("a", "d1", 0, "payment-service failed INC-1", "2025-01-01", "payment-service"),
                ("b", "d1", 1, "payment-service recovered INC-1", "2025-01-02", "payment-service"),
                ("c", "d2", 0, "other-api failed INC-1", "2025-01-03", "other-api"),
            ]
        ]
    )
    yield InvestigationTools(retriever, store, EvidenceStore())
    store.client.close()
    engine.dispose()


def test_tools(tools):
    assert "E1" in tools.execute("search_documents", {"query": "payment-service failed"})
    assert "recovered" in tools.execute("get_document", {"doc_id": "d1"})
    assert "other-api" in tools.execute("find_related", {"entity": "INC-1"})
    timeline = tools.execute("timeline", {"service": "payment-service"})
    assert timeline.index("failed") < timeline.index("recovered")
    assert "other-api" not in timeline


@pytest.mark.parametrize(
    "name,args",
    [
        ("unknown", {}),
        ("search_documents", {}),
        ("search_documents", {"query": "x", "top_k": -1}),
        ("timeline", {"date_from": "bad"}),
        ("get_document", {"doc_id": "d1", "max_chunks": True}),
    ],
)
def test_bad_arguments(tools, name, args):
    assert tools.execute(name, args).startswith("Tool error:")


def test_filters_cannot_expand(tools):
    tools.filters = QueryFilters(services=["payment-service"])
    assert tools.execute("find_related", {"entity": "other-api"}) == "No evidence found."
    assert tools.execute("get_document", {"doc_id": "d2"}) == "No evidence found."


def test_timeline_entity_dates(tools):
    tools.store.upsert_chunks(
        [
            Chunk(
                "dated",
                "d3",
                1,
                0,
                "payment-service event",
                [],
                0,
                21,
                3,
                {
                    "title": "Review",
                    "doc_type": "postmortem",
                    "entities": {
                        "services": ["payment-service"],
                        "dates": ["2025-02-01", "2025-02-03"],
                    },
                },
            )
        ]
    )
    text = tools.execute("timeline", {"service": "payment-service", "date_from": "2025-02-02"})
    assert "2025-02-03" in text and "2025-02-01" not in text
    assert "2025-01-01" not in text
