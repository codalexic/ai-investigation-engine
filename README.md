# AI Investigation Engine

A system for answering questions that need more than one document. You ask something like *"Which changes caused the
March payment disruption, which services were hit, and which documents confirm it?"* and the engine plans the
investigation, searches across incident reports, change logs and architecture docs, follows the links between them, and
answers with a citation on every claim. If the sources disagree it says so, and if the evidence isn't there it refuses to
guess.

**Live demo:** [ai-investigation-engine-x3zw.onrender.com](https://ai-investigation-engine-x3zw.onrender.com)
(free tier: the first request after 15 idle minutes takes about a minute while the service wakes up)

**Docs:** [Architecture and decisions](docs/ARCHITECTURE.md) · [Evaluation report](docs/EVALUATION_REPORT.md) ·
[Deployment](docs/DEPLOYMENT.md) · [AI usage](docs/AI_USAGE_REPORT.md)

## What it does

For the March example above, the engine finds the incident review for INC-2031, reads that change CHG-1042 caused it,
follows CHG-1042 to the change log and the payment-gateway runbook, and points out two problems in the record: the
preliminary report blamed a different change, and two sources give different outage durations.

- **Ingestion.** PDF, DOCX, Markdown/TXT, HTML, JSON and CSV. Title, dates, document type and entities (service names,
  `INC-`/`CHG-` ids) are extracted at ingest. Exact duplicates are caught by hash, near-duplicates by MinHash/LSH.
  Documents can be added, replaced (a new version is kept) and deleted. Two chunking strategies are implemented and
  compared.
- **Search.** Hybrid retrieval in Qdrant: dense embeddings plus my own BM25 stored as sparse vectors. Results are merged with
  weighted reciprocal rank fusion, boosted for matching entities and dates, re-ranked with a cross-encoder and diversified
  with MMR. Every result shows why it ranked where it did.
- **Investigation.** A planner breaks the question into sub-questions. A bounded tool loop then lets the model call
  `search_documents`, `get_document`, `find_related` and `timeline`, and the answer streams back with `[E#]` citations.
- **Verification.** This runs outside the model: every cited claim is checked against its source, contradictions between
  sources are flagged, and the engine abstains when too few claims are supported. Retrieved text is treated as data,
  never as instructions (prompt-injection defence).
- **Reliability.** Provider fallback (Groq → Gemini) with retries, rate-limit handling and a circuit breaker; response and
  answer caches; Prometheus metrics; stored traces of every investigation.

## Architecture

```
Browser UI ──► FastAPI (REST + SSE streaming, /metrics)
                 │
   ┌─────────────┼──────────────────────────────┐
   ▼             ▼                              ▼
Ingestion     Hybrid retrieval              Investigation
parse → meta  dense + BM25 (sparse)         plan → seed search → tool loop
→ dedup       → weighted RRF → boosts       → streamed answer → verifier
→ chunk       → rerank → MMR                        │
   │             │                                  ▼
   ▼             ▼                          LLMs: Groq gpt-oss-120b,
Postgres      Qdrant (dense + sparse        Gemini as fallback / judge
(registry,    vectors, payloads)
 versions, BM25 stats, caches, traces)
```

The reasoning behind each major choice is written up as ten ADRs in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why these choices

| Area | Choice | Reason |
|---|---|---|
| Vector DB | Qdrant | Dense and sparse vectors live in one collection, so hybrid search is a single query. It has payload filters and a free cloud tier. |
| Keyword search | My own BM25 | Off-the-shelf tokenisers split ids like `CHG-1042`; mine keeps them whole. The statistics update incrementally when documents are added or removed. |
| Fusion | Weighted RRF + boosts + MMR | Rank-based fusion doesn't need dense and BM25 scores on the same scale. Boosts reward matching entities and dates; MMR stops one document from filling the context. |
| Embeddings | `bge-small-en-v1.5` (ONNX via fastembed) | Measured better recall than `all-MiniLM-L6-v2` (Recall@10 0.937 vs 0.868). Small and CPU-friendly, with no PyTorch in the image. |
| Reranker | `ms-marco-MiniLM-L-6-v2` | +5 points of MRR on HotpotQA. It is the most expensive step, so it can be switched off. |
| Verification | NLI model + grounding checks | A deterministic check that doesn't depend on the model judging its own answer. |
| LLMs | Groq `gpt-oss-120b`, Gemini fallback | Free tiers with OpenAI-compatible tool calling. The judge comes from a different provider than the generator. |
| Storage | Postgres (Neon) / SQLite locally | Registry, versions, BM25 statistics, caches and traces survive restarts. |
| UI | Static HTML + vanilla JS | No build step; FastAPI serves it directly. |
| Hosting | Render + Qdrant Cloud + Neon | All free. Hugging Face Spaces now needs PRO, and Cloud Run needs a billing account. |

## Data

| Source | Records | Why |
|---|---|---|
| [HotpotQA](https://huggingface.co/datasets/hotpotqa/hotpot_qa) (distractor, validation) | 66,555 paragraphs | Scale, plus multi-hop questions with gold supporting documents for retrieval metrics |
| [danluu/post-mortems](https://github.com/danluu/post-mortems) | 240 incidents | Real incident write-ups |
| Synthetic "Northwind Pay" company | 45 documents, 7 formats | Planted cross-document facts, 4 contradictions, 3 gaps, a near-duplicate, a versioned runbook and 2 injection attempts. These are cases public datasets don't provide. |

In total that is 66,795 documents and about 67k chunks. Everything is rebuilt deterministically with `make data`; ground
truth is in `eval/data/`.

## Results

Full methodology and error analysis are in the [evaluation report](docs/EVALUATION_REPORT.md).

**Retrieval** (HotpotQA, 1,018 questions, full 66.8k-document index):

| Config | Recall@10 | MRR@10 | p50 latency |
|---|---|---|---|
| dense | 0.839 | 0.898 | 27 ms |
| BM25 | 0.760 | 0.795 | 19 ms |
| hybrid | 0.862 | 0.881 | 41 ms |
| hybrid + rerank | **0.874** | **0.933** | 804 ms (CPU) |

**End to end** (54 questions across 7 categories; both rows use the same model, gemini-3.5-flash-lite):

| | Correctness | Citation recall | False abstention | Multi-hop correctness | Tokens/question |
|---|---|---|---|---|---|
| single-shot RAG | 0.66 | 0.78 | 0.43 | 0.33 | 1.9k |
| agent | **0.81** | **0.85** | **0.28** | **0.86** | 7.9k |

The agent's gain comes almost entirely from multi-hop questions, where the second document is never named in the
question and a single search can't find it. Neither configuration ever answered an unanswerable question, and every
injection attempt failed. Structure-aware chunking reached the evidence with about a third of the context that fixed
windows needed, at the same recall.

## Running it locally

You need Python 3.11, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync
cp .env.example .env            # add GROQ_API_KEY and/or GEMINI_API_KEY
docker compose up -d qdrant     # Qdrant on :6333
make data                       # download and build the corpora and eval set
make index                      # embed and index everything (~1.5 h on a laptop CPU)
make run                        # http://localhost:7860
```

Search and document management work without an LLM key; investigations need one. `docker compose up` starts the API
and Qdrant together.

To reproduce the evaluation:

```bash
make index-chunking eval-retrieval eval-chunking eval-embeddings eval-e2e report
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/documents` | Upload a document → created / duplicate / near-duplicate |
| `GET` | `/api/documents`, `/api/documents/{id}`, `/api/documents/{id}/chunks` | List, inspect, view chunks |
| `PUT` / `DELETE` | `/api/documents/{id}` | Replace (new version) / delete |
| `POST` | `/api/search` | Retrieval only, with a ranking explanation per result |
| `POST` | `/api/investigate`, `/api/investigate/stream` | Full investigation as JSON or Server-Sent Events |
| `GET` | `/api/stats`, `/api/traces` | Index statistics, stored investigation traces |
| `GET` | `/health`, `/ready`, `/metrics` | Liveness, readiness, Prometheus metrics |

Interactive docs are at `/docs`.

## Project layout

```
app/
  core/        settings, logging, errors
  ingest/      parsers, metadata, chunking, dedup, registry, pipeline
  retrieval/   embeddings, BM25, Qdrant store, fusion/MMR, reranker, hybrid retriever
  llm/         provider client, fallback, cache, cost accounting
  agent/       planner, investigator, tools, synthesizer, verifier, NLI
  security/    prompt-injection scanning
  api/ ui/     REST/SSE API and web interface
  corpus/      dataset builders, indexer, cloud migration
  evaluation/  metrics and evaluation runners
scripts/       command-line entry points
eval/          questions, ground truth, results
tests/         unit, integration and API tests
```

## Tests

```bash
make lint
make test      # 348 tests; no network needed (fake models and LLMs)
RUN_MODEL_TESTS=1 uv run python -m pytest -m models   # optional: real ONNX models
```

CI runs lint and tests on every push and pull request.

## Deployment

The demo runs on Render's free web service (512 MB RAM, 0.1 vCPU), with Qdrant Cloud for vectors and Neon Postgres
for everything else, so the container itself holds no state. The corpus is embedded once locally and migrated, so the
cloud never re-embeds anything. API keys live only in Render's secret store and in a git-ignored `.env`.

512 MB isn't enough for the cross-encoder and the NLI model, so the demo uses a **lite profile**: no reranking (Recall@10
0.862 instead of 0.874), and grounding checks instead of NLI. The full profile is the default anywhere with 2 GB or
more. A GitHub Actions job pings the service every two days so the free Qdrant and Neon tiers aren't suspended for
inactivity. Costs, limits and the step-by-step setup are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Limitations

- The synthetic company is template-generated; real incident archives are messier.
- The NLI model is small and works best on short sentences, so long multi-hop claims are only approximately verified.
- The abstention thresholds were tuned by hand on the evaluation set itself, so the end-to-end numbers may be slightly
  optimistic.
- Free-tier LLM quotas limit throughput. When they run out, the app falls back to another provider, to cached answers, or
  to abstaining rather than failing.
- Run a single worker process: the LSH index, BM25 statistics snapshot and rate limiter live in process memory.
