# Architecture

This document describes how the AI Investigation Engine is put together and why. The README covers setup;
`docs/EVALUATION_REPORT.md` covers measured quality; `docs/DEPLOYMENT.md` covers hosting.

## 1. What the system does

The engine answers investigation-style questions over a large, mixed document collection — questions whose answer is spread
across several documents, may be contradicted by some of them, or may not be in the collection at all:

> "Which system changes caused the payment processing disruption in March, which services were affected, and which documents
> confirm it?"

For such a question the engine plans sub-questions, gathers evidence with hybrid search and tool calls, writes an answer where
every factual sentence cites evidence, checks those citations with an NLI model, mines contradictions between sources, and
abstains when the evidence does not support an answer.

## 2. Component overview

```
             ┌──────────────────────────── FastAPI app (app/api) ─────────────────────────────┐
 Browser UI ─┤ /api/documents  /api/search  /api/investigate(/stream)  /api/stats  /metrics     │
 (app/ui)    └──────┬───────────────┬────────────────────┬────────────────────────────────────┘
                    │               │                    │
        ┌───────────▼──────┐ ┌──────▼────────┐  ┌────────▼──────────────────────────────────┐
        │ Ingestion        │ │ Retrieval     │  │ Investigation engine (app/agent)          │
        │ (app/ingest)     │ │ (app/retrieval)│ │ planner → investigator (tool loop) →      │
        │ parse → metadata │ │ dense + BM25  │◄─┤ synthesizer (streamed) → verifier (NLI)   │
        │ → dedup → chunk  │ │ → RRF → boost │  └────────┬──────────────────────────────────┘
        │ → registry       │ │ → rerank → MMR│           │
        └──────┬───────────┘ └──────┬────────┘  ┌────────▼────────┐
               │                    │           │ LLM layer       │  Groq / Gemini / OpenRouter
               ▼                    ▼           │ (app/llm)       │  retries, fallback, circuit
        ┌─────────────┐     ┌──────────────┐    │ cache, costing  │  breaker, response cache
        │ Postgres /  │     │ Qdrant       │    └─────────────────┘
        │ SQLite      │     │ dense+sparse │
        │ registry,   │     │ named vectors│
        │ BM25 stats, │     │ + payload    │
        │ caches, logs│     └──────────────┘
        └─────────────┘
```

| Package | Responsibility |
|---|---|
| `app/core` | settings (pydantic-settings, `.env`), structured logging with request ids, error types |
| `app/ingest` | parsers for 6 formats, metadata/entity extraction, two chunkers, exact + near-duplicate detection, document registry, ingestion pipeline (create/update/delete/bulk) |
| `app/retrieval` | embeddings (fastembed/ONNX), own BM25 sparse encoder, Qdrant store, fusion/boost/MMR algorithms, reranker, hybrid retriever |
| `app/llm` | provider-agnostic OpenAI-compatible client, fallback chain, response cache, token budgeting, cost accounting |
| `app/agent` | evidence store, tools, planner, investigator loop, synthesizer, NLI verifier, engine + event stream |
| `app/security` | prompt-injection scanning and evidence sanitisation |
| `app/corpus` | reproducible dataset builders and the bulk indexer |
| `app/evaluation` | metrics and evaluation runners |
| `app/api`, `app/ui` | REST/SSE API and the static web UI |

## 3. Request flows

### 3.1 Ingestion
1. **Parse** — a parser registry picks the parser by extension (PDF, DOCX, Markdown/TXT, HTML, JSON, CSV). Text is normalised
   (NFKC, whitespace, encoding fallback) and split into sections where the format has structure (headings, DOCX styles, CSV rows).
2. **Metadata** — title and date fallback chains, a rule-based document-type classifier, and regex entity extraction
   (service names, `CHG-`/`INC-` ids, dates normalised to ISO). Entities are stored per document and per chunk; they power
   metadata filters, entity boosting, the `find_related`/`timeline` tools and contradiction candidate selection.
3. **Deduplicate** — SHA-256 of normalised text catches exact duplicates; a MinHash signature (128 permutations) with LSH banding
   (32 bands × 4 rows) finds near-duplicates, verified against an estimated Jaccard threshold of 0.9. Near-duplicates are indexed
   and flagged (`duplicate_of`) by default, or skipped by policy.
4. **Chunk** — structure-aware (default) or fixed-window chunking; chunk ids encode `doc_id:version:index`.
5. **Index** — dense embeddings and BM25 sparse vectors are written to one Qdrant point per chunk; the registry stores document
   metadata, version history and the MinHash signature. Updating a document bumps its version and replaces all its chunks;
   deleting removes chunks, decrements BM25 statistics and marks the registry row deleted.

### 3.2 Retrieval
```
query ─┬─ dense search (bge-small, cosine, top 50) ─┐
       └─ sparse search (own BM25, top 50) ─────────┴─► weighted RRF ─► entity & date boosts ─► cross-encoder rerank (top 30)
                                                                                                  ─► MMR ─► per-doc cap ─► top k
```
Every returned chunk carries an `explain` record (dense rank, sparse rank, fused score, boost, rerank score) and the result carries
per-stage timings, which the UI and the evaluation use.

### 3.3 Investigation
1. **Plan** — for non-trivial questions the LLM returns sub-questions, entities and an optional time range (JSON mode). Short
   single-entity questions skip this call.
2. **Seed evidence** — hybrid search for the question and each sub-question, plus an entity-targeted search. Plan output is only a
   soft signal (boosts); hard filters come only from the user.
3. **Tool loop** — native function calling with `search_documents`, `get_document`, `find_related`, `timeline`; bounded by
   max steps and max tool calls. Tool results are compact summaries with evidence ids, never whole documents.
4. **Synthesis** — one streamed call; markdown answer with `[E#]` citations followed by a `<meta>` JSON block (claims with evidence
   ids, contradictions, insufficient-information flag, missing information, confidence). Malformed metadata gets one repair call.
5. **Verification** — unknown citations are removed; each claim is checked with an NLI model against its cited evidence;
   sentence-level contradiction mining runs over evidence from different documents that share entities; the engine abstains when the
   model reports insufficient information, when evidence is missing or weak, or when fewer than half of the claims are supported.

## 4. Architecture decisions

**ADR-1 · Qdrant as the vector database.** Native named dense + sparse vectors in one collection let BM25 and embeddings share point
ids and payload filters, so hybrid search needs no second engine. Payload indexes cover the metadata filters. A free 1 GB cloud
cluster holds the full corpus (~67k points × 384-d ≈ 100 MB of vectors plus payload), and the same image runs locally in Docker.
*Alternatives:* pgvector (would need a separate full-text path and tuning for hybrid), Chroma (no native sparse vectors at the time),
Pinecone (sparse-dense works but the free tier is serverless-only and less transparent).

**ADR-2 · Own BM25 as a sparse dot product.** Document vectors carry TF saturation and length normalisation, query vectors carry
IDF, so their dot product equals the BM25 score and Qdrant can serve it at scale. Term statistics live in SQL and are updated
incrementally on upsert/delete. This keeps the keyword half of hybrid search under our control (tokenisation that keeps
identifiers like `CHG-1042` and `payment-gateway` intact matters for incident data) and is proven equal to a reference BM25 in tests.
*Trade-off:* document weights use avgdl at index time; as the corpus grows the approximation drifts slightly, which a periodic
re-index removes.

**ADR-3 · Weighted Reciprocal Rank Fusion, then boosts, rerank and MMR.** RRF fuses rankings without calibrating incompatible score
scales (cosine vs BM25). Entity and date-proximity boosts encode investigation priors (a question about `INC-2040` in March should
prefer chunks mentioning it and dated in March). A cross-encoder reranks the fused head; MMR then trades a little relevance for
diversity so multi-document questions see more than one source; a per-document cap prevents one long document from filling the
context. All of these are pure functions in `app/retrieval/fusion.py`; their effect is measured in the evaluation.

**ADR-4 · fastembed (ONNX) instead of PyTorch.** `bge-small-en-v1.5` and `ms-marco-MiniLM-L-6-v2` run through ONNX Runtime, which keeps
the container image small and cold starts short on free CPU hosting. `bge-small` was chosen for its retrieval quality per FLOP; it is
compared with `all-MiniLM-L6-v2` in the evaluation.

**ADR-5 · Two chunking strategies.** Structure-aware chunking (headings → paragraphs → sentences, sentence overlap, small-chunk merging,
heading breadcrumbs) is the default because incident reviews and runbooks are sectioned and a section is usually one topic.
Fixed token windows with overlap are the baseline. They are compared on the long synthetic documents, where chunking actually
matters; HotpotQA paragraphs fit in one chunk either way.

**ADR-6 · Agentic RAG with bounded tool use.** Multi-hop questions need retrieval that depends on intermediate findings
(the review names `CHG-1051`; only the change log says what it changed; only the operations page says who owns the service).
A planner plus a bounded tool loop finds these links while step and tool-call limits cap cost and latency. Deterministic seed
searches run before the loop so a weak tool-caller still has evidence. A non-agentic mode exists for comparison.

**ADR-7 · Verification outside the LLM.** Citations are checked mechanically and claims with a small NLI model
(`nli-deberta-v3-xsmall`, ONNX) rather than by asking the same LLM whether it was right. This makes faithfulness measurable,
catches unsupported claims and gives contradiction detection a second, model-independent signal.

**ADR-8 · Provider-agnostic LLM layer over HTTP.** Groq, Gemini and OpenRouter all expose OpenAI-compatible endpoints, so one small
httpx client covers tool calling, JSON mode and streaming. A fallback chain with circuit breakers, retry with backoff honouring
`Retry-After`, a SQL response cache and token budgeting make the free tiers usable and the evaluation resumable.

**ADR-9 · Untrusted evidence.** Retrieved text is wrapped in `<evidence>` tags with escaped delimiters, instruction-like spans are
neutralised before they reach the model, and the system prompt states that evidence is data. The evaluation includes documents with
planted injection payloads.

**ADR-10 · Registry in Postgres, vectors in Qdrant.** Document metadata, versions, BM25 statistics, caches and query traces are
relational and transactional; vectors and searchable payload live in Qdrant. SQLite is used locally and in tests with the same
SQLAlchemy models.

## 5. Performance and cost notes
- Embedding throughput on a 12-thread laptop CPU is ~18 paragraphs/s for `bge-small`; the 66k-record corpus indexes in about an
  hour and is indexed once, then migrated to the cloud collection without re-embedding.
- Query-time cost is one query embedding (~10 ms), two Qdrant searches, and a cross-encoder pass over 30 candidates
  (the dominant retrieval cost on CPU).
- LLM usage per investigation is bounded by the planner call, at most `agent_max_steps` tool-loop calls and one synthesis call;
  the response and answer caches make repeated questions free. Token usage and an estimated cost (at public list prices) are
  reported per request and in `/metrics`.
