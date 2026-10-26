# AI Investigation Engine

A multi-source investigation engine for large document collections, with hybrid retrieval,
citations, contradiction detection, and abstention. Built with FastAPI, Qdrant, and Postgres.

## Local development

Run `uv sync`, copy `.env.example` to `.env`, then run `uv run uvicorn app.api.main:app --reload`. Open http://127.0.0.1:8000 for the UI and `/docs` for the API. Set a provider API key to enable investigations; document management and search work without one. Set `DATABASE_URL` and `QDRANT_COLLECTION` to an isolated workspace when an indexer is active. Readiness is at `/ready` and Prometheus metrics at `/metrics`.

Run checks with `uv run ruff format --check .`, `uv run ruff check .`, and `uv run python -m pytest -q -p no:cacheprovider --basetemp=.pytest_tmp` (set `UV_CACHE_DIR=.uv-cache`).

## Deployment

See [the deployment guide](docs/DEPLOYMENT.md) for HF Spaces, Qdrant Cloud, Neon, migration, secrets, and operations.
