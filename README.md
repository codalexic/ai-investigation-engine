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

## Local development

Copy `.env.example` to `.env`, then run `docker compose up --build` for Qdrant
(6333/6334) and the API (7860). Qdrant persists in the `qdrant_data` volume.
Run `uv sync --group data` and `make data` to download the cached public corpora
and create the fictional Northwind Pay documents. `make index` indexes all sources;
`make index-fixed` builds the fixed-window comparison. For host indexing, set
`QDRANT_URL=http://localhost:6333` in `.env`. Each collection gets its own SQLite
registry under `data/`; reruns skip active records and apply the runbook revision once.
Use `--limit`, `--batch-size`, and `--recreate` on `scripts/index_corpus.py` to control
bulk runs. Reports are saved to `eval/results/indexing_<collection>.json`.
