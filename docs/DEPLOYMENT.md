# Deployment

```mermaid
flowchart LR
  Browser --> Space[HF Space: FastAPI + UI + ONNX models]
  Space --> Qdrant[Qdrant Cloud: vectors and payloads]
  Space --> Neon[Neon Postgres: registry, BM25, caches, traces]
  Space --> LLM[LLM APIs]
```

## First deployment

1. Create Hugging Face, Qdrant Cloud, Neon, and generation-provider accounts. Select
   Qdrant and Neon free plans. Check eligibility for Docker Spaces before proceeding:
   [HF currently requires a paid plan to create Docker Spaces](https://huggingface.co/docs/hub/spaces-overview),
   although CPU Basic has no hourly charge. A fully $0 setup depends on account eligibility
   or a grant; do not assume a new free account can create this Docker Space.
2. Index locally using `uv run python -m scripts.index_corpus --help`. Use an isolated
   database and collection while another indexing job runs. Finish indexing and stop
   source mutations before migration; copying an actively changing index is not a snapshot.
3. Create a Qdrant cluster and API key. Create a Neon database and copy its SSL connection
   string, using `postgresql+psycopg://` as its SQLAlchemy scheme and `sslmode=require`.
   Put target `QDRANT_URL`, `QDRANT_API_KEY`, and `DATABASE_URL` in the gitignored `.env`.
4. Run from the repository root (PowerShell):

   ```powershell
   uv run python -m scripts.migrate_to_cloud --source-qdrant http://localhost:6333 --source-collection documents --source-db sqlite:///./data/registry_documents.db --batch 256
   ```

   Targets default to `.env` settings; CLI overrides include `--target-qdrant`,
   `--target-api-key`, `--target-collection`, and `--target-db`. Prefer environment
   secrets to command-line values, which may enter shell history. Source SQLite opens
   read-only. Only five index tables are copied; request caches and logs stay local.
   Vector batches retry and checkpoint at `data/migrate_checkpoint.json` after confirmed
   upserts. Rerun the same command after interruption. SQL upserts are transactional
   and repeatable. Counts must match; stale target rows require `--replace`, which
   deletes target data before copying. It never deletes source data. Use a dedicated
   target and checkpoint for each migration. Verify source document/chunk counts first.
5. Set `HF_TOKEN` with write access, a strong `ADMIN_TOKEN`, and available provider keys
   in `.env`. Select supported generation model IDs: older defaults may be retired;
   check [Groq models](https://console.groq.com/docs/models) and Gemini's model catalog.
   Review the repository link in `deploy/space/README.md` if publishing a fork.
6. Preview with `uv run python -m scripts.deploy_space username/space --dry-run`.
   It prints filenames and secret names only. Deploy with the same command without
   `--dry-run`. Only the Docker build inputs and the Space README are uploaded.
   Models download during the image build, then load lazily. Production warm-up runs
   in a background thread; `/health` does not wait for it. `WARMUP=false` disables it.
7. Check the build logs, `/health`, `/ready`, `/api/stats`, search and an investigation
   with citations. `/ready` touches both remote databases. Compare migrated counts.

## Secrets and automation

`.env` is gitignored and must never be uploaded. Provider keys, database URL,
Qdrant endpoint/key and admin token become HF Space secrets. `HF_TOKEN` remains on
 the deployment machine or in GitHub secrets, never inside the Space. Ordinary model
IDs and collection settings become Space variables. Public Space source is visible.

For workflows, set repository variable `SPACE_ID=username/space` and `SPACE_URL` to
its direct `https://username-space.hf.space` URL. Add repository secrets `HF_TOKEN`,
`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`,
`DATABASE_URL`, and `ADMIN_TOKEN`. Manual dispatch or a `v*` tag runs deployment.
Configure model variables in the Space if defaults no longer work; local deployment
also propagates configured model IDs. Remove unused secrets directly in Space settings:
redeployment updates supplied secrets but does not delete existing ones.

## Persistence and availability

The container is stateless. Qdrant holds vectors and payloads; Postgres holds registry,
versions, BM25 statistics, index version, request caches and traces. Restarts discard
container disk; the image retains its model cache. Never use SQLite or in-memory
Qdrant for a production Space. Model IDs must match the image's downloaded models;
changing models requires rebuilding and, for embeddings, rebuilding the index.

### Free-tier limits and how the app copes

Figures as documented by the providers at the time of writing (October 2026); they change, so check the linked pages.

| Service | Free tier | Limitation that matters | Mitigation in this project |
| --- | --- | --- | --- |
| [Hugging Face Spaces](https://huggingface.co/docs/hub/spaces-overview) (CPU Basic) | 2 vCPU, 16 GB RAM, ephemeral disk | Sleeps after ~48 h without traffic; cold start rebuilds nothing but reloads models | Models baked into the image, lazy loading + background warm-up, keep-alive workflow every 2 days |
| [Qdrant Cloud](https://qdrant.tech/documentation/cloud/create-cluster/) | 1 node, 1 GB RAM, 0.5 vCPU, 4 GB disk | Suspended after 1 week of inactivity, deleted after 4 weeks | Keep-alive calls `/ready` (touches Qdrant); the local index plus `migrate_to_cloud.py` can restore the cluster without re-embedding |
| [Neon Postgres](https://neon.com/faqs/free-plan-limits-and-quotas) | 0.5 GB storage per project, 100 CU-hours/month, up to 2 CU | Compute scales to zero after 5 min idle (cold start on first query) | Connection pre-ping and retries; registry rows are small (~1 KB each incl. MinHash) |
| [Groq](https://console.groq.com/docs/rate-limits) (openai/gpt-oss-120b) | ≈30 requests/min, ≈1,000 requests/day, ≈12k tokens/min per organisation | One investigation uses 3–8 calls, so roughly 150–300 investigations/day | Fallback to Gemini/OpenRouter, circuit breaker, LLM response cache, answer cache, per-IP rate limit (10/min), abstention instead of errors |
| [Gemini API](https://ai.google.dev/gemini-api/docs/rate-limits) | Free tier with per-model RPM/RPD limits | Lower throughput; also used as the evaluation judge | Used as fallback generator and as judge (different provider from the generator) |

Hugging Face has been changing free hardware eligibility; some accounts report that new free Docker Spaces need a
subscription. If CPU Basic is not available on the account, the same image runs unchanged on any container host with
≥2 GB RAM (for example a Koyeb or Render instance, or an Oracle Cloud Always Free VM); only `deploy_space.py` is HF-specific.

## Sizing and costs

67,000 float32 dense vectors at 384 dimensions need 102,912,000 bytes, about 98 MiB,
for raw dense values alone. Payload text, sparse postings, HNSW, replicas and service
memory add overhead; measure the actual collection. The
[Qdrant free tier](https://qdrant.tech/pricing/) is intended for prototypes.
Budget roughly 1-3 GiB for the three CPU model sessions plus tokenizers and working
buffers as a planning estimate, not a measured bound. Load testing should include
concurrent reranking/NLI, LSH rebuild, Postgres connections and process RSS.

| Component | Infrastructure / usage estimate |
| --- | --- |
| HF CPU Basic compute | $0 hourly; account subscription may be required |
| Qdrant free cluster | $0 within free-tier limits |
| Neon free database | $0 within free-tier limits |
| Infrastructure target | $0 only with eligible HF access and free-tier capacity |
| Example investigation | 20k input + 3k output tokens at $0.15/$0.60 per million: ≈ $0.005 |
| Cached answer | No new generation charge on a full answer-cache hit |

The generation example uses Groq's list rates for `openai/gpt-oss-120b` (the default model) as a paid-tier reference;
on the free tier the actual charge is $0, and the estimate shows what the same traffic would cost after leaving it. Sum tokens across all planner,
tool and synthesis calls; retries and fallbacks can raise cost. Free API quotas may
reduce billed usage to $0. Verify current provider prices and model availability.

## Operations

Run the app with a single worker process. The LSH index, BM25 statistics snapshot, and rate limiter are process-local; multiple workers cannot keep them consistent. The Dockerfile runs one worker. Keep WEB_CONCURRENCY and UVICORN_WORKERS set to 1.


Redeploy by rerunning the script or workflow. Rotate keys at their provider, update
local and GitHub secrets, then deploy to update HF secrets and verify readiness.
Do not log connection strings or key values. Change `ADMIN_TOKEN` at the same time
in authorized clients. Review traces and `/metrics` for latency and provider failures.

Re-index into a new local collection/database, stop index writes, migrate into a new
remote collection/database, then switch Space secrets/variables and redeploy. Retain
old stores until validation passes. Restore from a stopped local index using a fresh
checkpoint and target; use `--replace` only when intentionally replacing that target.
Caches and traces are recreated empty after migration; back them up separately if
needed. A checkpoint is progress metadata, not a backup. Keep source SQL and Qdrant
snapshots together so registry, sparse statistics and vectors describe the same index.
