# AI Investigation Engine

A multi-source investigation engine for large document collections, with hybrid retrieval,
citations, contradiction detection, and abstention. Built with FastAPI, Qdrant, and Postgres.

Status: work in progress

Use Python 3.11 and uv for local development:

```sh
uv sync
cp .env.example .env
uv run uvicorn app.api.main:app --reload --port 7860
```

Check health at `http://localhost:7860/health`. Run tests with `uv run pytest -q`.
