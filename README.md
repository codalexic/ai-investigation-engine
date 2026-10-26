# AI Investigation Engine

An agentic retrieval system for **investigating** large, mixed document collections — not "chat with a PDF".
It answers questions whose answer is spread across several documents, links facts between them, cites every claim,
flags contradicting sources and refuses to answer when the evidence is not there.

> *"Which system changes caused the payment processing disruption in March, which services were affected, and which
> documents confirm it?"* — the engine plans sub-questions, searches incident reviews, the change log and the
> architecture doc, connects `INC-2031 → CHG-1042 → payment-gateway → fraud-api`, cites each step, and reports that the
> preliminary incident report blamed a different change and that two sources disagree on the outage duration.

**Live demo:** _link added after deployment_ · **Docs:** [Architecture](docs/ARCHITECTURE.md) ·
[Evaluation report](docs/EVALUATION_REPORT.md) · [Deployment](docs/DEPLOYMENT.md)

## Highlights

- **66,795 documents indexed** (HotpotQA paragraphs, real public post-mortems, a synthetic incident knowledge base) —
  ~67k chunks in Qdrant.
- **Six input formats** (PDF, DOCX, Markdown/TXT, HTML, JSON, CSV) with metadata and entity extraction, two chunking
  strategies, exact + MinHash/LSH near-duplicate detection, versioned updates and deletes.
- **Hybrid retrieval with custom ranking**: own BM25 served as Qdrant sparse vectors + dense embeddings → weighted
  reciprocal rank fusion → entity/date boosts → cross-encoder reranking → MMR diversification. Every result explains
  its rank.
- **Agentic RAG**: planner, deterministic seed retrieval, bounded native tool calling (`search_documents`,
  `get_document`, `find_related`, `timeline`), streamed synthesis with `[E#]` citations.
- **Verification outside the LLM**: citation checks, NLI-based claim support, sentence-level contradiction mining,
  abstention when evidence is missing or unsupported; prompt-injection defences for retrieved text.
- **Production concerns**: provider fallback with retries and circuit breakers, response and answer caches, rate limiting,
  SSE streaming, Prometheus metrics, persisted traces, 230+ automated tests, CI.
- **Automated evaluation**: 66-question end-to-end set (multi-hop, multi-document, contradiction, unanswerable, injection)
  plus a 1,000-question retrieval benchmark with confidence intervals and configuration comparisons.

## Architecture

```
Browser UI ──► FastAPI (/api, SSE, /metrics)
                 │
   ┌─────────────┼──────────────────────────────┐
   ▼             ▼                              ▼
Ingestion     Hybrid retrieval              Investigation engine
parse→meta    dense + own BM25              plan → seed search → tool loop
→dedup→chunk  → RRF → boosts                → streamed synthesis → NLI verifier
   │          → rerank → MMR                        │
   ▼             ▼                                  ▼
Postgres      Qdrant (dense + sparse        LLM layer: Groq / Gemini / OpenRouter
(registry,    named vectors, payload)       retries · fallback · cache · cost
 BM25 stats,
 caches, traces)
```

Design decisions and trade-offs are recorded as ten ADRs in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack

| Concern | Choice | Why |
|---|---|---|
| API / backend | Python 3.11, FastAPI, pydantic | typed, async streaming, OpenAPI docs at `/docs` |
| Vector database | Qdrant | dense + sparse vectors in one collection, payload filters, free cloud tier |
| Keyword search | own BM25 encoder | identifiers like `CHG-1042` tokenised correctly; incremental statistics |
| Embeddings / reranker | `bge-small-en-v1.5`, `ms-marco-MiniLM-L-6-v2` via fastembed (ONNX) | no PyTorch, small image, fast CPU inference |
| Verification | `nli-deberta-v3-xsmall` (ONNX) | measurable claim support and contradiction signal |
| LLMs | Groq `llama-3.3-70b-versatile` (primary), Gemini (fallback/judge), OpenRouter | free tiers, OpenAI-compatible tool calling |
| Relational store | Postgres (Neon) / SQLite locally, SQLAlchemy 2 | registry, versions, BM25 stats, caches, traces |
| UI | static HTML + vanilla JS | no build step; served by the API |
| Hosting | Hugging Face Spaces (Docker), Qdrant Cloud, Neon | all free tiers |

## Data

| Source | Records | Purpose |
|---|---|---|
| [HotpotQA](https://huggingface.co/datasets/hotpotqa/hotpot_qa) distractor validation | 66,555 unique paragraphs | scale, multi-hop questions with gold supporting documents |
| [danluu/post-mortems](https://github.com/danluu/post-mortems) | 240 incident summaries | real incident domain |
| Synthetic "Northwind Pay" knowledge base | 45 documents in 7 formats | planted cross-document facts, 4 contradictions, 3 gaps, near-duplicate, versioned runbook, 2 injection payloads |

Everything is rebuilt deterministically by `make data`; ground truth lives in `eval/data/`.

## Quick start

Requirements: Python 3.11, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
cp .env.example .env            # add at least one LLM key (GROQ_API_KEY or GEMINI_API_KEY) to enable investigations
docker compose up -d qdrant     # local Qdrant on :6333
make data                       # download/build the corpora and the evaluation set
make index                      # embed and index everything (~1.5 h on a laptop CPU)
make run                        # http://localhost:7860
```

Search and document management work without an LLM key; investigations need one. `docker compose up` runs the
API and Qdrant together.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/documents` | upload a document (multipart) → created / duplicate / near-duplicate |
| `GET` | `/api/documents`, `/api/documents/{id}`, `/api/documents/{id}/chunks` | list, inspect, view chunks |
| `PUT` / `DELETE` | `/api/documents/{id}` | replace (new version) / delete |
| `POST` | `/api/search` | retrieval only, with per-result ranking explanation |
| `POST` | `/api/investigate`, `/api/investigate/stream` | full investigation as JSON or Server-Sent Events |
| `GET` | `/api/stats`, `/api/traces` | index statistics, stored investigation traces |
| `GET` | `/health`, `/ready`, `/metrics` | liveness, readiness, Prometheus metrics |

## Evaluation

`docs/EVALUATION_REPORT.md` contains the methodology, all results and the error analysis. Headline numbers:

| Retrieval on HotpotQA (n = 1,018, 66.8k-document index) | Recall@10 | MRR@10 | p50 latency |
|---|---|---|---|
| dense (bge-small) | 0.839 | 0.898 | 27 ms |
| BM25 (own) | 0.760 | 0.795 | 19 ms |
| hybrid (weighted RRF) | 0.862 | 0.881 | 41 ms |
| **hybrid + cross-encoder rerank** | **0.874** | **0.933** | 804 ms (CPU) |

- `bge-small-en-v1.5` beats `all-MiniLM-L6-v2` on dense Recall@10, 0.937 vs 0.868, with non-overlapping 95% CIs.
- Structure-aware chunking reaches the first evidence chunk with 3× less context than fixed windows (201 vs 626 tokens)
  at statistically indistinguishable recall.
- Single-shot retrieval is weakest on multi-hop investigation questions (Recall@10 ≈ 0.65): the second-hop document is
  never named in the question. This is the case the agent's tool loop targets.

Reproduce with `make index-chunking eval-retrieval eval-chunking eval-embeddings eval-e2e report`.

## Project layout

```
app/
  core/        settings, logging, errors
  ingest/      parsers, metadata, chunking, dedup, registry, pipeline
  retrieval/   embeddings, BM25, Qdrant store, fusion/MMR, reranker, hybrid retriever
  llm/         provider client, fallback, cache, accounting
  agent/       planner, investigator, tools, synthesizer, verifier, NLI
  security/    prompt-injection scanning
  api/ ui/     REST/SSE API and web interface
  corpus/      dataset builders, indexer, cloud migration
  evaluation/  metrics and evaluation runners
scripts/       CLIs for data, indexing, evaluation, deployment
eval/          questions, ground truth, results
tests/         unit, integration and API tests
```

## Testing

```bash
make lint
make test          # 230+ tests, no network needed (fake models and LLMs)
RUN_MODEL_TESTS=1 uv run python -m pytest -m models   # optional: real ONNX models
```

## Deployment

The app runs as one Docker container on Hugging Face Spaces with Qdrant Cloud and Neon Postgres, all on free tiers.
The corpus is embedded once locally and migrated, so the cloud never re-embeds. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
for the architecture, secrets handling, free-tier limits and costs.

## Limitations

- The synthetic corpus is template-generated; real incident archives are messier.
- The NLI model is small and works best on short premises; long multi-hop claims are checked against combined evidence,
  which is an approximation.
- Abstention thresholds were tuned by hand on the evaluation set.
- Free-tier LLM quotas bound throughput; the app degrades to cached answers or abstention rather than failing.
