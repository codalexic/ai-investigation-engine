### Retrieval: what the numbers say

**Hybrid search beats either half alone, and reranking buys precision at the top.** On the HotpotQA questions
(n = 1,018: the 1,000-question sample plus the HotpotQA items of the investigation set; two gold paragraphs per question; 66.8k-document index) dense retrieval reaches Recall@10 0.839 and BM25 0.760;
weighted RRF fusion lifts Recall@10 to 0.862 and Recall@20 to 0.905 (dense 0.872), i.e. the two retrievers miss
*different* documents. Fusion alone slightly lowers MRR (0.881 vs 0.898 dense) because a strong dense first hit can be
outvoted by a lexical match; the cross-encoder repairs this and moves MRR@10 to 0.933 and nDCG@10 to 0.829 — the best
configuration on every HotpotQA metric. The cost is latency: p50 goes from ~40 ms to ~800 ms on a laptop CPU, almost
entirely the cross-encoder over 30 candidates.

**BM25 matters most where identifiers matter.** On the investigation set, BM25 alone ranks the gold document first for
every contradiction question (MRR 1.000) and every simple question beats dense on MRR (0.792 vs 0.438): questions such as
"What did CHG-1051 change?" hinge on an exact identifier that the embedding model barely distinguishes from CHG-1052. In
one traced example the change-log chunk was dense rank 25 but BM25 rank 2, and the hybrid ranked it first. This is the
reason the BM25 tokenizer keeps `CHG-1051` and `payment-gateway` as whole tokens.

**MMR does not help this benchmark.** `hybrid_rerank_mmr` is within noise of `hybrid_rerank` on HotpotQA and slightly
worse at depth on synthetic multi-hop questions (Recall@20 0.733 vs 0.783): when the second gold document is lexically
similar to the first, diversification pushes it down. MMR stays available but is not the default for evaluation.

**Embedding model.** On a 300-question subset (2,987 paragraphs) `bge-small-en-v1.5` reaches dense Recall@10 0.937
[0.917–0.957] vs 0.868 [0.840–0.895] for `all-MiniLM-L6-v2`; the confidence intervals do not overlap, so the quality gap is
real. MiniLM indexes ~33% faster (161 s vs 241 s) with similar query latency. bge-small is kept: indexing is a one-off cost,
retrieval quality is paid on every question.

**Chunking.** On the 284 long-form documents (synthetic knowledge base + post-mortems) fixed 400-token windows score
slightly higher on rank metrics (MRR@10 0.671 vs 0.547, Recall@10 0.872 vs 0.821) but the intervals overlap heavily
(n = 26), so the difference is not significant. The structure-aware chunker reaches the first evidence-bearing chunk with
**3× less context** (201 vs 626 tokens) because its chunks follow section boundaries (mean 91 vs 134 tokens). Since the
generator's context budget, cost and the NLI verifier's 512-token window all favour small, topical chunks, structure-aware
chunking remains the default; the rank gap points at its weakness — sections shorter than the minimum get merged with
neighbours, which occasionally dilutes a chunk.

### Performance at full scale

Measured on the 67k-point index (laptop CPU, 12 threads, local Qdrant). Without reranking the retrieval path is cheap:
dense p50 23 ms / 40 QPS, BM25 19 ms / 47 QPS, hybrid 36 ms / 28 QPS at concurrency 1, and throughput grows up to
~32–64 QPS at concurrency 4–8 while p95 stays under 300 ms. Qdrant search itself is 15–17 ms; fusion, boosts and MMR add
under 10 ms. The cross-encoder changes the picture completely: ~0.85 s p50 and ~1 QPS, and because ONNX inference already
uses every core, concurrency only adds queueing (p99 28 s at concurrency 8). Reranking is therefore the component that
decides capacity: it buys +5 points of MRR on HotpotQA (0.881 → 0.933) at ~25× the latency. On 2 shared vCPUs (the free
Space) it is the first thing to tune — fewer rerank candidates (`RERANK_TOP_N`), a quantised model, or skipping the rerank
when the fused ranking is already confident. Indexing throughput was 12.3 records/s (66,795 records, 66,995 chunks in
90 minutes), dominated by CPU embedding; it is a one-off cost because the index is migrated to the cloud, never rebuilt there.

### Where retrieval fails and why

1. **Second-hop documents are invisible to single-shot retrieval.** The weakest category is multi-hop (Recall@10
   0.64–0.73 across configs). The failures share one shape: *"Which team owns the service whose change caused INC-2040?"*
   retrieves every INC-2040 document (review, ticket, incident report, meeting notes) but never the change log or the
   operations page, because the bridge entity (`CHG-1051`, then `ledger-service`) is not in the question. HotpotQA bridge
   questions fail the same way (e.g. the venue of the 2014 FIBA final: the final's page is found, the arena's page is not).
   This is the gap the agent's tool loop is designed to close — it reads the review, extracts `CHG-1051`, and calls
   `find_related` / `search_documents` for it — and the end-to-end comparison of `full` vs `no_agent` measures exactly that.
2. **Near-duplicates crowd the context.** The duplicated export of the INC-2031 incident report is correctly flagged at
   ingestion (`duplicate_of`) but still occupies a second slot in the top-5, because the per-document cap works on
   `doc_id`, not on duplicate groups.
3. **Under-specified post-mortem questions.** "What went wrong at Cloudflare?" has one gold entry but the corpus holds
   several Cloudflare post-mortems; retrieval returns other, equally valid Cloudflare incidents (Recall@10 0.5–0.67, n = 6).
   This is a question-design flaw rather than a retrieval error — the question does not identify the incident.
4. **Tabular sources chunk poorly.** The change-log CSV is chunked as blocks of rows, so one chunk mixes a dozen unrelated
   changes and its embedding is a blur; identifier queries survive only thanks to BM25.

### Improvements

- **Retrieval for multi-hop:** query rewriting with entities extracted from first-round evidence (the agent does this; a
  cheap deterministic version — expand the query with `CHG-`/`INC-` ids found in the top-3 chunks — would help the
  non-agentic path too).
- **Collapse duplicate groups at query time** by treating `duplicate_of` as the cap key.
- **Row-level chunking for CSV/JSON records** with the header repeated in each chunk.
- **Rewrite post-mortem questions** to name the incident (date or system) so they have a single correct answer.
- **Latency:** rerank only when the fused score margin between ranks 1 and 10 is small, cache reranker scores per
  (query, chunk), or swap in a smaller cross-encoder; quantised ONNX models would roughly halve CPU time.
- **Chunking:** tune `chunk_min_tokens` so short sections stay separate, and add the section breadcrumb to the embedded
  text (currently stored but not embedded).
