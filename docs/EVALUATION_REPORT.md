# Evaluation report

This report evaluates retrieval, chunking, embeddings, and end-to-end answer quality. Raw results live in eval/results/.

## Summary

### Retrieval — HotpotQA (n=1018)

| Config | Recall@5 | Recall@10 | Recall@20 | MRR@10 | nDCG@10 | Latency p50 ms | Latency p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dense | 0.778 | 0.839 [0.822–0.855] | 0.872 | 0.898 [0.882–0.913] | 0.792 | 26.503 | 47.915 |
| sparse | 0.641 | 0.760 [0.743–0.775] | 0.832 | 0.795 [0.775–0.814] | 0.669 | 18.503 | 34.397 |
| hybrid | 0.785 | 0.862 [0.849–0.877] | 0.905 | 0.881 [0.865–0.897] | 0.783 | 40.591 | 62.006 |
| hybrid_rerank | 0.813 | 0.874 [0.860–0.888] | 0.912 | 0.933 [0.921–0.946] | 0.829 | 804.015 | 1308.059 |
| hybrid_rerank_mmr | 0.812 | 0.872 [0.859–0.887] | 0.907 | 0.934 [0.921–0.947] | 0.827 | 831.845 | 1325.261 |

### Retrieval — investigation set by category

#### Recall@10

| Category | dense | sparse | hybrid | hybrid_rerank | hybrid_rerank_mmr |
| --- | --- | --- | --- | --- | --- |
| comparison/multi_doc | 1.000 | 0.950 | 1.000 | 1.000 | 1.000 |
| contradiction | 0.938 | 0.938 | 1.000 | 1.000 | 1.000 |
| injection | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| multi_hop | 0.725 | 0.592 | 0.658 | 0.642 | 0.642 |
| postmortem | 0.500 | 0.500 | 0.500 | 0.667 | 0.667 |
| simple | 0.875 | 1.000 | 1.000 | 1.000 | 1.000 |
| unanswerable | n/a | n/a | n/a | n/a | n/a |

#### MRR@10

| Category | dense | sparse | hybrid | hybrid_rerank | hybrid_rerank_mmr |
| --- | --- | --- | --- | --- | --- |
| comparison/multi_doc | 0.883 | 0.725 | 0.833 | 0.950 | 0.950 |
| contradiction | 0.854 | 1.000 | 0.938 | 1.000 | 1.000 |
| injection | 0.875 | 0.333 | 0.750 | 0.833 | 0.833 |
| multi_hop | 0.692 | 0.672 | 0.693 | 0.681 | 0.679 |
| postmortem | 0.190 | 0.417 | 0.292 | 0.230 | 0.228 |
| simple | 0.438 | 0.792 | 0.542 | 0.781 | 0.781 |
| unanswerable | n/a | n/a | n/a | n/a | n/a |

### Chunking

| Metric | chunk_structure | chunk_fixed |
| --- | --- | --- |
| evidence-hit@10 | 0.808 | 0.846 |
| Recall@10 | 0.821 | 0.872 |
| MRR@10 | 0.546 | 0.671 |
| context_tokens_to_first_hit | 200.667 | 626.091 |
| mean_chunk_tokens | 91.053 | 133.960 |
| chunks_per_document | 1.651 | 1.222 |
| chunk_count | 469.000 | 347.000 |

### Embeddings

| Model / mode | Recall@10 | MRR@10 | Index seconds | Query p50 ms |
| --- | --- | --- | --- | --- |
| BAAI/bge-small-en-v1.5/dense | 0.937 [0.917–0.957] | 0.943 [0.921–0.963] | 241.226 | 24.158 |
| BAAI/bge-small-en-v1.5/hybrid | 0.955 [0.938–0.972] | 0.898 [0.871–0.923] | 241.226 | 34.724 |
| sentence-transformers/all-MiniLM-L6-v2/dense | 0.868 [0.840–0.895] | 0.875 [0.845–0.904] | 160.550 | 19.786 |
| sentence-transformers/all-MiniLM-L6-v2/hybrid | 0.905 [0.878–0.928] | 0.850 [0.815–0.880] | 160.550 | 34.197 |

### End-to-end

Not run yet

#### Judge correctness by category

Not run yet

## Analysis

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


## Methodology

The evaluation set is assembled deterministically with seed 13 from synthetic facts, HotpotQA bridge/comparison questions, and postmortem summaries. Gold documents are validated against corpus identifiers. Category counts: {"comparison/multi_doc": 10, "contradiction": 8, "injection": 4, "multi_hop": 20, "postmortem": 6, "simple": 8, "unanswerable": 10}

Retrieval ranks are deduplicated by document before scoring. Recall@k measures the fraction of gold documents retrieved; precision@k divides relevant hits by k; MRR is the reciprocal rank of the first relevant document; binary nDCG discounts hits by log2(rank+1); Hit@k indicates any gold hit. Confidence intervals use 1,000 bootstrap samples, seed 0, 95% coverage. Latency percentiles use linear interpolation.

Retrieval configurations: dense, sparse, hybrid, hybrid_rerank, hybrid_rerank_mmr. Chunking compares identical document sets using evidence substring hits, document recall, MRR, chunk tokens and context tokens to the first hit (misses are excluded from that mean). Embedding experiments use only the original contexts of the first N sampled questions.

End-to-end configurations: full (primary 70B model), no_agent (one retrieval followed by synthesis and verification), small_model (8B), gemini. All use hybrid retrieval with reranking. The automatic judge prefers a different provider from the generator, uses a strict 0/0.5/1 correctness rubric, and checks injection assertions including paraphrases. Actual judge provider/model and usage are recorded per question; unavailable or disabled judges produce missing scores rather than substitute estimates.

Answer metrics include SQuAD normalized EM/token F1 for HotpotQA, document citation precision and recall, supported-claim share from the NLI verifier, abstention accuracy, false abstention and false answer rates conditional on expected behavior, gold-citing contradiction detection, and judge-checked injection resistance. Cost estimates use the configured model price table; cached calls incur no new estimated cost. Judge cost is reported separately.

### Reproducibility

```bash
make data
make index
make index-chunking
make eval-retrieval
make eval-chunking
make eval-embeddings
make eval-e2e
make report
```

Existing collection evaluations open registry databases read-only; embeddings use isolated emb_* collections and separate registry databases. End-to-end question and LLM caches live under eval/cache. Re-run the same command after quota recovery to resume; remove stale question caches when the dataset or configuration changes. Question-cache reuse is validated against the run context.

## Failure cases

### bridge (embeddings)

#### 5a81ebee554299676cceb16d (sentence-transformers/all-MiniLM-L6-v2/dense)

Question: What kind of movie directed by F. Javier gutierrez did an Italian model and actress star in?

Expected: American supernatural psychological horror film

Got: American supernatural psychological horror film

Metrics: {"Recall@10": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

#### 5a8cefc155429941ae14df55 (BAAI/bge-small-en-v1.5/hybrid)

Question: What is the english translation of the name of style of novel of which The Company is an example?

Expected: novel with a key

Got: novel with a key

Metrics: {"Recall@10": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

### bridge (retrieval)

#### 5a721bbc55429971e9dc9279 (dense)

Question: Which Grammy Nominated album was created by a band whose members include John Bowman?

Expected: Nature's Symphony in 432

Got: Nature's Symphony in 432

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

#### 5a721bbc55429971e9dc9279 (sparse)

Question: Which Grammy Nominated album was created by a band whose members include John Bowman?

Expected: Nature's Symphony in 432

Got: Nature's Symphony in 432

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

### comparison (embeddings)

#### 5a778b345542992a6e59decf (sentence-transformers/all-MiniLM-L6-v2/dense)

Question: Who was born first, Susan Oliver or W. S. Van Dyke?

Expected: Woodbridge Strong Van Dyke II

Got: Woodbridge Strong Van Dyke II

Metrics: {"Recall@10": 0.5, "MRR@10": 0.5, "nDCG@10": 0.38685280723454163, "Hit@10": 1.0}

#### 5a778b345542992a6e59decf (sentence-transformers/all-MiniLM-L6-v2/hybrid)

Question: Who was born first, Susan Oliver or W. S. Van Dyke?

Expected: Woodbridge Strong Van Dyke II

Got: Woodbridge Strong Van Dyke II

Metrics: {"Recall@10": 0.5, "MRR@10": 0.25, "nDCG@10": 0.2640681225725909, "Hit@10": 1.0}

### comparison (retrieval)

#### 5a7385c45542992d56e7e359 (sparse)

Question: Who was born first, British novelist Doris Lessing or American writer Philip K. Dick?

Expected: Doris May Lessing

Got: Doris May Lessing

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 1.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

#### 5a7574e25542996c70cfaf01 (dense)

Question: Who was born first Mahbub ul Haq or Ibn Arabi?

Expected: ibnʿArabī

Got: ibnʿArabī

Metrics: {"Recall@5": 0.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.16666666666666666, "nDCG@10": 0.4227898344066503, "Hit@10": 1.0}

### comparison/multi_doc (chunking)

#### comparison-syn-1 (chunk_structure)

Question: Which teams own ledger-service and notification-worker, respectively?

Expected: Financial Records; Customer Messaging

Got: []

Metrics: {"evidence-hit@10": 0.0, "Recall@10": 0.5, "MRR@10": 0.16666666666666666, "context_tokens_to_first_hit": null}

#### comparison-syn-0 (chunk_structure)

Question: Which teams own payment-gateway and fraud-api, respectively?

Expected: Payments Platform; Risk Engineering

Got: []

Metrics: {"evidence-hit@10": 0.0, "Recall@10": 1.0, "MRR@10": 0.5, "context_tokens_to_first_hit": null}

### comparison/multi_doc (retrieval)

#### comparison-syn-0 (sparse)

Question: Which teams own payment-gateway and fraud-api, respectively?

Expected: Payments Platform; Risk Engineering

Got: ["syn:review-INC-2031", "syn:architecture", "syn:runbook-fraud-api", "syn:ticket-INC-2031", "syn:architecture", "syn:change-log", "syn:incident-INC-2031", "syn:incident-INC-2031-export", "syn:change-log", "syn:change-log", "syn:runbook-payment-gateway", "syn:operations-payment-gateway", "syn:runbook-fraud-api", "syn:operations-fraud-api", "syn:runbook-payment-gateway", "hotpot:paytm-2ea11ce3", ...

Metrics: {"Recall@5": 0.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.1111111111111111, "nDCG@10": 0.36181498356361597, "Hit@10": 1.0}

#### comparison-syn-0 (hybrid)

Question: Which teams own payment-gateway and fraud-api, respectively?

Expected: Payments Platform; Risk Engineering

Got: ["syn:architecture", "syn:architecture", "syn:runbook-fraud-api", "syn:ticket-INC-2031", "syn:change-log", "syn:review-INC-2031", "syn:change-log", "syn:change-log", "syn:operations-fraud-api", "syn:operations-payment-gateway", "hotpot:paymate-6d87d8ff", "syn:operations-reporting-api", "syn:runbook-payment-gateway", "syn:operations-auth-service", "pm:cloudflare-38e7a2c9", "syn:incident-INC-2031...

Metrics: {"Recall@5": 0.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.16666666666666666, "nDCG@10": 0.4227898344066503, "Hit@10": 1.0}

### contradiction (chunking)

#### conflict-pool-0 (chunk_structure)

Question: What database connection pool size does the payment-gateway runbook currently recommend?

Expected: Configure the database connection pool with 50 connections. Configure the database connection pool with 200 connections. The current v2 runbook supersedes v1: use 200 connections.

Got: []

Metrics: {"evidence-hit@10": 0.0, "Recall@10": 1.0, "MRR@10": 1.0, "context_tokens_to_first_hit": null}

#### conflict-pool-0 (chunk_fixed)

Question: What database connection pool size does the payment-gateway runbook currently recommend?

Expected: Configure the database connection pool with 50 connections. Configure the database connection pool with 200 connections. The current v2 runbook supersedes v1: use 200 connections.

Got: []

Metrics: {"evidence-hit@10": 0.0, "Recall@10": 1.0, "MRR@10": 1.0, "context_tokens_to_first_hit": null}

### contradiction (retrieval)

#### conflict-duration-0 (sparse)

Question: How long did the customer impact of INC-2031 last?

Expected: The customer disruption lasted three hours. The INC-2031 customer disruption lasted five hours, with degraded payment authorisation on 2025-03-04..2025-03-05. The sources disagree; no explicit supersession resolves the duration.

Got: ["syn:review-INC-2031", "syn:runbook-payment-gateway", "syn:meeting-INC-2031", "syn:incident-INC-2031", "syn:incident-INC-2031-export", "syn:ticket-INC-2031", "syn:review-INC-2031", "syn:review-INC-2031", "syn:review-INC-2050", "syn:review-INC-2020", "syn:review-INC-2040", "syn:review-INC-2044", "hotpot:slavery-in-libya-04aab7eb", "syn:status-payment-gateway", "pm:google-e575ceff", "pm:google-9...

Metrics: {"Recall@5": 0.5, "Recall@10": 0.5, "Recall@20": 1.0, "MRR@10": 1.0, "nDCG@10": 0.6131471927654584, "Hit@10": 1.0}

#### conflict-duration-0 (hybrid)

Question: How long did the customer impact of INC-2031 last?

Expected: The customer disruption lasted three hours. The INC-2031 customer disruption lasted five hours, with degraded payment authorisation on 2025-03-04..2025-03-05. The sources disagree; no explicit supersession resolves the duration.

Got: ["syn:review-INC-2031", "syn:ticket-INC-2031", "syn:meeting-INC-2031", "syn:incident-INC-2031", "syn:incident-INC-2031-export", "syn:status-payment-gateway", "syn:ticket-INC-2031", "syn:review-INC-2031", "syn:review-INC-2050", "syn:review-INC-2044", "syn:ticket-INC-2020", "syn:runbook-payment-gateway", "syn:review-INC-2031", "syn:ticket-INC-2050", "syn:ticket-INC-2040", "syn:review-INC-2020", "...

Metrics: {"Recall@5": 0.5, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 1.0, "nDCG@10": 0.8315546295836225, "Hit@10": 1.0}

### injection (chunking)

#### injection-0-0 (chunk_structure)

Question: What problem was reported in the ticket for INC-2020?

Expected: Authentication retries

Got: []

Metrics: {"evidence-hit@10": 1.0, "Recall@10": 1.0, "MRR@10": 0.5, "context_tokens_to_first_hit": 36}

#### injection-0-0 (chunk_fixed)

Question: What problem was reported in the ticket for INC-2020?

Expected: Authentication retries

Got: []

Metrics: {"evidence-hit@10": 1.0, "Recall@10": 1.0, "MRR@10": 1.0, "context_tokens_to_first_hit": 489}

### injection (retrieval)

#### injection-0-0 (dense)

Question: What problem was reported in the ticket for INC-2020?

Expected: Authentication retries

Got: ["syn:meeting-INC-2020", "syn:ticket-INC-2020", "syn:review-INC-2020", "syn:ticket-INC-2020", "syn:change-log", "syn:change-log", "syn:change-log", "syn:ticket-INC-2044", "syn:ticket-INC-2031", "syn:ticket-INC-2040", "syn:meeting-INC-2044", "syn:meeting-INC-2031", "syn:ticket-INC-2050", "syn:meeting-INC-2040", "syn:meeting-INC-2050", "syn:review-INC-2044", "syn:review-INC-2050", "syn:review-INC...

Metrics: {"Recall@5": 1.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.5, "nDCG@10": 0.6309297535714575, "Hit@10": 1.0}

#### injection-0-0 (sparse)

Question: What problem was reported in the ticket for INC-2020?

Expected: Authentication retries

Got: ["syn:review-INC-2020", "syn:meeting-INC-2020", "syn:ticket-INC-2020", "syn:incident-INC-2020", "syn:review-INC-2020", "syn:ticket-INC-2020", "syn:review-INC-2050", "hotpot:mazda-rx-9-792a792b", "hotpot:2020-summer-olympics-984fa29c", "syn:ticket-INC-2040", "syn:review-INC-2050", "hotpot:pan-am-railways-32ffe5fe", "hotpot:stand-up-speak-up-bf8ff852", "hotpot:next-croatian-presidential-election-...

Metrics: {"Recall@5": 1.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.3333333333333333, "nDCG@10": 0.5, "Hit@10": 1.0}

### multi_hop (chunking)

#### multi-causal-owner (chunk_structure)

Question: Which team owns the service whose change caused INC-2040?

Expected: Financial Records

Got: []

Metrics: {"evidence-hit@10": 0.0, "Recall@10": 0.0, "MRR@10": 0.0, "context_tokens_to_first_hit": null}

#### multi-causal-dependencies (chunk_structure)

Question: What does the service whose change caused INC-2031 depend on?

Expected: auth-service and ledger-service

Got: []

Metrics: {"evidence-hit@10": 1.0, "Recall@10": 0.3333333333333333, "MRR@10": 0.25, "context_tokens_to_first_hit": 690}

### multi_hop (retrieval)

#### hp-5a7f669a5542994857a76729 (hybrid_rerank)

Question: What character did the actor born on January 19, 1944 play in "As the World Turns?"

Expected: James Stenbeck

Got: ["hotpot:daniel-hughes-as-the-world-turns-55b144cf", "hotpot:mike-edmonds-ad0e3f5a", "hotpot:terri-conn-e9b6a7a6", "hotpot:liberty-ciccone-e8f460ad", "hotpot:bob-hughes-db06bd72", "hotpot:scott-holmes-e6a93d6b", "hotpot:michael-louden-888f7e81", "hotpot:abigail-williams-as-the-world-turns-687fb24e", "hotpot:anthony-herrera-66ceb1da", "hotpot:patrick-tovatt-d8531c84", "hotpot:cane-ashby-e92000b7...

Metrics: {"Recall@5": 0.0, "Recall@10": 0.5, "Recall@20": 1.0, "MRR@10": 0.1111111111111111, "nDCG@10": 0.18457569677956817, "Hit@10": 1.0}

#### hp-5adc7b855542994650320d1e (sparse)

Question: What county is the congressional district that Hansen Clarke was a U.S. Representative for in?

Expected: Wayne County

Got: ["hotpot:hansen-clarke-aa4652b6", "hotpot:carolyn-cheeks-kilpatrick-2e958aef", "hotpot:gary-peters-politician-c9e06621", "hotpot:bill-foster-politician-bb77b617", "hotpot:frederick-r-lehlbach-5cf96906", "hotpot:rick-nolan-6df1d013", "hotpot:jaime-herrera-beutler-c5ddb5d9", "hotpot:electoral-history-of-hansen-clarke-c5170d5f", "hotpot:adam-kinzinger-8e959739", "hotpot:john-shimkus-b8629824", "ho...

Metrics: {"Recall@5": 0.0, "Recall@10": 0.5, "Recall@20": 0.5, "MRR@10": 0.125, "nDCG@10": 0.19342640361727081, "Hit@10": 1.0}

### postmortem (retrieval)

#### postmortem-pm-amazon-900cd6f9 (dense)

Question: What went wrong at Amazon?

Expected: . A configuration change in the Seoul region incorrectly removed the setting that specifies the minimum healthy hosts for the EC2 DNS resolver fleet, so the system fell back to a very low default. The fleet's healthy host count dropped and in-VPC DNS queries from EC2 instances failed for ~84 minutes until capacity was manually restored. AWS added semantic config validation and per-hour throttling on host removal as remediations.

Got: ["pm:amazon-b6a80e63", "pm:amazon-6973eb94", "pm:amazon-d639dbd0", "pm:amazon-b7ac2058", "pm:amazon-2d6786ee", "pm:pagerduty-7f5a45aa", "pm:sentry-df8aa932", "pm:razorpay-35358f5f", "pm:google-09836889", "syn:change-log", "pm:fastly-23e926a3", "syn:change-log", "syn:change-log", "pm:allegro-8e9398f0", "pm:etsy-022b26f7", "pm:etsy-b2eda9d6", "pm:reddit-6d995c77", "pm:chef-io-0ee4289a", "pm:micro...

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

#### postmortem-pm-amazon-900cd6f9 (sparse)

Question: What went wrong at Amazon?

Expected: . A configuration change in the Seoul region incorrectly removed the setting that specifies the minimum healthy hosts for the EC2 DNS resolver fleet, so the system fell back to a very low default. The fleet's healthy host count dropped and in-VPC DNS queries from EC2 instances failed for ~84 minutes until capacity was manually restored. AWS added semantic config validation and per-hour throttling on host removal as remediations.

Got: ["pm:sentry-df8aa932", "hotpot:the-departure-album-144a2c3d", "hotpot:meeting-of-waters-e28cbce9", "hotpot:rick-dalzell-d13cec06", "hotpot:souq-com-02b0e01a", "hotpot:why-freud-was-wrong-1ffcff95", "pm:owasa-c7506de2", "hotpot:description-error-fe1592ce", "pm:amazon-6973eb94", "hotpot:going-wrong-86ceef25", "pm:amazon-b7ac2058", "pm:amazon-d639dbd0", "hotpot:nordcurrent-b32dc330", "hotpot:mulfo...

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

### simple (chunking)

#### simple-CHG-1042 (chunk_structure)

Question: What change was made in CHG-1042?

Expected: DB connection pool reduced from 200 to 50

Got: []

Metrics: {"evidence-hit@10": 1.0, "Recall@10": 1.0, "MRR@10": 0.5, "context_tokens_to_first_hit": 125}

#### simple-CHG-1042 (chunk_fixed)

Question: What change was made in CHG-1042?

Expected: DB connection pool reduced from 200 to 50

Got: []

Metrics: {"evidence-hit@10": 1.0, "Recall@10": 1.0, "MRR@10": 0.5, "context_tokens_to_first_hit": 797}

### simple (retrieval)

#### simple-INC-2040 (dense)

Question: What problem occurred in INC-2040?

Expected: Ledger write failures and settlement delays

Got: ["syn:ticket-INC-2040", "syn:meeting-INC-2040", "pm:google-6bfedae8", "syn:change-log", "syn:change-log", "syn:change-log", "pm:ccp-games-59d35f48", "pm:square-ab7b4d31", "syn:meeting-INC-2044", "syn:meeting-INC-2050", "pm:amazon-d639dbd0", "pm:nasa-a3ec42e5", "pm:platform-sh-7c3fee70", "pm:intel-53d73577", "pm:github-6b44a37d", "pm:cloudflare-beec53a0", "pm:travisci-1ff3dd33", "pm:dropbox-3025...

Metrics: {"Recall@5": 0.0, "Recall@10": 0.0, "Recall@20": 0.0, "MRR@10": 0.0, "nDCG@10": 0.0, "Hit@10": 0.0}

#### simple-CHG-1042 (dense)

Question: What change was made in CHG-1042?

Expected: DB connection pool reduced from 200 to 50

Got: ["syn:review-INC-2031", "syn:change-log", "syn:change-log", "syn:change-log", "syn:review-INC-2050", "syn:incident-INC-2031-export", "syn:incident-INC-2031", "pm:google-5b7cb7a7", "hotpot:chief-financial-officers-act-290f4959", "hotpot:airline-deregulation-act-10eec4f6", "syn:ticket-INC-2050", "syn:ticket-INC-2050", "syn:review-INC-2040", "hotpot:repeal-of-the-implementation-of-the-nics-improve...

Metrics: {"Recall@5": 1.0, "Recall@10": 1.0, "Recall@20": 1.0, "MRR@10": 0.5, "nDCG@10": 0.6309297535714575, "Hit@10": 1.0}

## Appendix: detailed results

### Retrieval

#### retrieval_documents

##### dense

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9697 | 0.9583-0.9792 | 1056 |
| MRR@10 | 0.8843 | 0.8678-0.9007 | 1056 |
| Recall@10 | 0.8385 | 0.8220-0.8534 | 1056 |
| Recall@20 | 0.8722 | 0.8573-0.8867 | 1056 |
| Recall@5 | 0.7760 | 0.7590-0.7921 | 1056 |
| nDCG@10 | 0.7847 | 0.7701-0.7995 | 1056 |

Latency (ms): {"p50": 26.273700001183897, "p95": 47.777450003195554}

retrieval_config: {"mode": "dense", "rerank": false, "mmr": false, "top_k": 20, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9665 | 0.9535-0.9781 | 775 |
| MRR@10 | 0.8736 | 0.8525-0.8934 | 775 |
| Recall@10 | 0.8019 | 0.7819-0.8213 | 775 |
| Recall@20 | 0.8419 | 0.8239-0.8594 | 775 |
| Recall@5 | 0.7290 | 0.7071-0.7490 | 775 |
| nDCG@10 | 0.7485 | 0.7298-0.7661 | 775 |

Latency (ms): {"p50": 27.140999998664483, "p95": 48.79274000195437}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9911 | 0.9778-1.0000 | 225 |
| MRR@10 | 0.9741 | 0.9548-0.9911 | 225 |
| Recall@10 | 0.9689 | 0.9489-0.9867 | 225 |
| Recall@20 | 0.9756 | 0.9578-0.9911 | 225 |
| Recall@5 | 0.9467 | 0.9222-0.9689 | 225 |
| nDCG@10 | 0.9382 | 0.9184-0.9551 | 225 |

Latency (ms): {"p50": 24.397599998337682, "p95": 44.97649999975692}

###### category: comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 10 |
| MRR@10 | 0.8833 | 0.7333-1.0000 | 10 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 10 |
| nDCG@10 | 0.9184 | 0.8222-0.9920 | 10 |

Latency (ms): {"p50": 21.749999999883585, "p95": 35.43179000407688}

###### category: contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.8542 | 0.6667-1.0000 | 8 |
| Recall@10 | 0.9375 | 0.8125-1.0000 | 8 |
| Recall@20 | 0.9375 | 0.8125-1.0000 | 8 |
| Recall@5 | 0.9375 | 0.8125-1.0000 | 8 |
| nDCG@10 | 0.8463 | 0.7126-0.9519 | 8 |

Latency (ms): {"p50": 23.14249999835738, "p95": 40.90841999568511}

###### category: injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 4 |
| MRR@10 | 0.8750 | 0.6250-1.0000 | 4 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 4 |
| nDCG@10 | 0.9077 | 0.7232-1.0000 | 4 |

Latency (ms): {"p50": 25.283749997470295, "p95": 31.728614997700788}

###### category: multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 20 |
| MRR@10 | 0.6917 | 0.5375-0.8250 | 20 |
| Recall@10 | 0.7250 | 0.6167-0.8333 | 20 |
| Recall@20 | 0.8250 | 0.7167-0.9250 | 20 |
| Recall@5 | 0.5500 | 0.4250-0.6750 | 20 |
| nDCG@10 | 0.5942 | 0.4861-0.6936 | 20 |

Latency (ms): {"p50": 22.99164999567438, "p95": 36.281729997426744}

###### category: postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.1905 | 0.0238-0.3571 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.3333 | 0.0000-0.6667 | 6 |
| nDCG@10 | 0.2659 | 0.0556-0.4763 | 6 |

Latency (ms): {"p50": 19.22674999877927, "p95": 20.03892500033544}

###### category: simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.8750 | 0.6250-1.0000 | 8 |
| MRR@10 | 0.4375 | 0.2500-0.6250 | 8 |
| Recall@10 | 0.8750 | 0.6250-1.0000 | 8 |
| Recall@20 | 0.8750 | 0.6250-1.0000 | 8 |
| Recall@5 | 0.8750 | 0.6250-1.0000 | 8 |
| nDCG@10 | 0.5481 | 0.3693-0.7194 | 8 |

Latency (ms): {"p50": 20.72000000043772, "p95": 33.80962000228464}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9725 | 0.9627-0.9823 | 1018 |
| MRR@10 | 0.8975 | 0.8819-0.9126 | 1018 |
| Recall@10 | 0.8389 | 0.8222-0.8546 | 1018 |
| Recall@20 | 0.8723 | 0.8576-0.8870 | 1018 |
| Recall@5 | 0.7785 | 0.7608-0.7972 | 1018 |
| nDCG@10 | 0.7918 | 0.7766-0.8072 | 1018 |

Latency (ms): {"p50": 26.503450000745943, "p95": 47.915280002416694}

###### source: postmortems

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.1905 | 0.0238-0.3571 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.3333 | 0.0000-0.6667 | 6 |
| nDCG@10 | 0.2659 | 0.0556-0.4763 | 6 |

Latency (ms): {"p50": 19.22674999877927, "p95": 20.03892500033544}

###### source: synthetic

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9688 | 0.9062-1.0000 | 32 |
| MRR@10 | 0.5938 | 0.4714-0.7135 | 32 |
| Recall@10 | 0.8906 | 0.7969-0.9688 | 32 |
| Recall@20 | 0.9062 | 0.8177-0.9792 | 32 |
| Recall@5 | 0.7812 | 0.6562-0.8750 | 32 |
| nDCG@10 | 0.6547 | 0.5564-0.7539 | 32 |

Latency (ms): {"p50": 21.725299997342518, "p95": 38.95982999893022}

##### sparse

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9669 | 0.9555-0.9763 | 1056 |
| MRR@10 | 0.7889 | 0.7696-0.8087 | 1056 |
| Recall@10 | 0.7612 | 0.7432-0.7773 | 1056 |
| Recall@20 | 0.8332 | 0.8180-0.8480 | 1056 |
| Recall@5 | 0.6438 | 0.6231-0.6613 | 1056 |
| nDCG@10 | 0.6672 | 0.6519-0.6817 | 1056 |

Latency (ms): {"p50": 18.753099997411482, "p95": 34.4026999991911}

retrieval_config: {"mode": "sparse", "rerank": false, "mmr": false, "top_k": 20, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9703 | 0.9574-0.9819 | 775 |
| MRR@10 | 0.8336 | 0.8114-0.8540 | 775 |
| Recall@10 | 0.7458 | 0.7265-0.7652 | 775 |
| Recall@20 | 0.8052 | 0.7865-0.8232 | 775 |
| Recall@5 | 0.6497 | 0.6290-0.6690 | 775 |
| nDCG@10 | 0.6814 | 0.6640-0.6982 | 775 |

Latency (ms): {"p50": 18.974799997522496, "p95": 34.49544999821228}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9600 | 0.9333-0.9822 | 225 |
| MRR@10 | 0.6584 | 0.6062-0.7103 | 225 |
| Recall@10 | 0.8089 | 0.7689-0.8444 | 225 |
| Recall@20 | 0.9267 | 0.9000-0.9511 | 225 |
| Recall@5 | 0.6089 | 0.5622-0.6511 | 225 |
| nDCG@10 | 0.6228 | 0.5817-0.6593 | 225 |

Latency (ms): {"p50": 18.10499999555759, "p95": 33.497739995073054}

###### category: comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 10 |
| MRR@10 | 0.7254 | 0.5040-0.9500 | 10 |
| Recall@10 | 0.9500 | 0.8500-1.0000 | 10 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@5 | 0.7000 | 0.4500-0.9012 | 10 |
| nDCG@10 | 0.7497 | 0.5976-0.8975 | 10 |

Latency (ms): {"p50": 16.14970000082394, "p95": 31.345305002469104}

###### category: contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@10 | 0.9375 | 0.8125-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 0.8750 | 0.7500-1.0000 | 8 |
| nDCG@10 | 0.8867 | 0.7961-0.9612 | 8 |

Latency (ms): {"p50": 26.57914999872446, "p95": 35.009720000380185}

###### category: injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 4 |
| MRR@10 | 0.3333 | 0.3333-0.3333 | 4 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 4 |
| nDCG@10 | 0.5000 | 0.5000-0.5000 | 4 |

Latency (ms): {"p50": 26.89269999973476, "p95": 32.54742499993881}

###### category: multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 20 |
| MRR@10 | 0.6718 | 0.5183-0.8100 | 20 |
| Recall@10 | 0.5917 | 0.5000-0.6833 | 20 |
| Recall@20 | 0.6167 | 0.5167-0.7167 | 20 |
| Recall@5 | 0.5167 | 0.4081-0.6250 | 20 |
| nDCG@10 | 0.5187 | 0.4148-0.6143 | 20 |

Latency (ms): {"p50": 15.292299998691306, "p95": 32.270459994106204}

###### category: postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.4167 | 0.0833-0.7500 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.8333 | 0.5000-1.0000 | 6 |
| Recall@5 | 0.5000 | 0.1667-0.8333 | 6 |
| nDCG@10 | 0.4385 | 0.1052-0.7729 | 6 |

Latency (ms): {"p50": 22.217950001504505, "p95": 30.88199999911012}

###### category: simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.7917 | 0.5833-0.9375 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.8452 | 0.6905-0.9539 | 8 |

Latency (ms): {"p50": 19.436799997492926, "p95": 31.18140000042331}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9686 | 0.9568-0.9784 | 1018 |
| MRR@10 | 0.7952 | 0.7748-0.8141 | 1018 |
| Recall@10 | 0.7598 | 0.7431-0.7751 | 1018 |
| Recall@20 | 0.8320 | 0.8163-0.8468 | 1018 |
| Recall@5 | 0.6415 | 0.6213-0.6616 | 1018 |
| nDCG@10 | 0.6690 | 0.6528-0.6841 | 1018 |

Latency (ms): {"p50": 18.50304999970831, "p95": 34.39667499405914}

###### source: postmortems

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.4167 | 0.0833-0.7500 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.8333 | 0.5000-1.0000 | 6 |
| Recall@5 | 0.5000 | 0.1667-0.8333 | 6 |
| nDCG@10 | 0.4385 | 0.1052-0.7729 | 6 |

Latency (ms): {"p50": 22.217950001504505, "p95": 30.88199999911012}

###### source: synthetic

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 32 |
| MRR@10 | 0.6572 | 0.5357-0.7726 | 32 |
| Recall@10 | 0.8542 | 0.7656-0.9323 | 32 |
| Recall@20 | 0.8698 | 0.7865-0.9427 | 32 |
| Recall@5 | 0.7448 | 0.6198-0.8490 | 32 |
| nDCG@10 | 0.6522 | 0.5520-0.7454 | 32 |

Latency (ms): {"p50": 23.63694999803556, "p95": 34.925539999312605}

##### hybrid

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9867 | 0.9792-0.9924 | 1056 |
| MRR@10 | 0.8701 | 0.8527-0.8852 | 1056 |
| Recall@10 | 0.8610 | 0.8474-0.8744 | 1056 |
| Recall@20 | 0.9056 | 0.8938-0.9170 | 1056 |
| Recall@5 | 0.7822 | 0.7647-0.7974 | 1056 |
| nDCG@10 | 0.7762 | 0.7622-0.7887 | 1056 |

Latency (ms): {"p50": 40.54035000081058, "p95": 62.030125000092085}

retrieval_config: {"mode": "hybrid", "rerank": false, "mmr": false, "top_k": 20, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9858 | 0.9768-0.9935 | 775 |
| MRR@10 | 0.8816 | 0.8627-0.8994 | 775 |
| Recall@10 | 0.8303 | 0.8123-0.8477 | 775 |
| Recall@20 | 0.8813 | 0.8665-0.8955 | 775 |
| Recall@5 | 0.7529 | 0.7329-0.7716 | 775 |
| nDCG@10 | 0.7622 | 0.7456-0.7784 | 775 |

Latency (ms): {"p50": 41.20549999788636, "p95": 62.64163000232656}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 225 |
| MRR@10 | 0.8746 | 0.8410-0.9055 | 225 |
| Recall@10 | 0.9756 | 0.9600-0.9889 | 225 |
| Recall@20 | 0.9911 | 0.9822-0.9978 | 225 |
| Recall@5 | 0.8911 | 0.8622-0.9178 | 225 |
| nDCG@10 | 0.8495 | 0.8239-0.8717 | 225 |

Latency (ms): {"p50": 38.61450000113109, "p95": 60.001619999820825}

###### category: comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 10 |
| MRR@10 | 0.8333 | 0.5833-1.0000 | 10 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@5 | 0.8000 | 0.5000-1.0000 | 10 |
| nDCG@10 | 0.8765 | 0.7114-0.9920 | 10 |

Latency (ms): {"p50": 35.16204999687034, "p95": 62.700309997308054}

###### category: contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.9375 | 0.8125-1.0000 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 0.8125 | 0.6250-0.9375 | 8 |
| nDCG@10 | 0.8767 | 0.7896-0.9488 | 8 |

Latency (ms): {"p50": 35.44085000248742, "p95": 53.83188000196242}

###### category: injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 4 |
| MRR@10 | 0.7500 | 0.5000-1.0000 | 4 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 4 |
| nDCG@10 | 0.8155 | 0.6309-1.0000 | 4 |

Latency (ms): {"p50": 33.66995000033057, "p95": 35.43288999935612}

###### category: multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 20 |
| MRR@10 | 0.6931 | 0.5444-0.8251 | 20 |
| Recall@10 | 0.6583 | 0.5500-0.7667 | 20 |
| Recall@20 | 0.8167 | 0.7083-0.9083 | 20 |
| Recall@5 | 0.6250 | 0.5000-0.7333 | 20 |
| nDCG@10 | 0.5721 | 0.4514-0.6820 | 20 |

Latency (ms): {"p50": 38.26034999656258, "p95": 67.23966500103415}

###### category: postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.2917 | 0.0417-0.5833 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.5000 | 0.1667-0.8333 | 6 |
| nDCG@10 | 0.3436 | 0.0718-0.6261 | 6 |

Latency (ms): {"p50": 35.96370000013849, "p95": 50.88552499910293}

###### category: simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.5417 | 0.3750-0.7292 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.6568 | 0.5307-0.7991 | 8 |

Latency (ms): {"p50": 36.62555000119028, "p95": 49.16155500395689}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9892 | 0.9823-0.9951 | 1018 |
| MRR@10 | 0.8815 | 0.8649-0.8970 | 1018 |
| Recall@10 | 0.8625 | 0.8487-0.8772 | 1018 |
| Recall@20 | 0.9052 | 0.8939-0.9170 | 1018 |
| Recall@5 | 0.7849 | 0.7672-0.8016 | 1018 |
| nDCG@10 | 0.7827 | 0.7676-0.7965 | 1018 |

Latency (ms): {"p50": 40.59119999874383, "p95": 62.006314999962335}

###### source: postmortems

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.5000 | 0.1667-0.8333 | 6 |
| MRR@10 | 0.2917 | 0.0417-0.5833 | 6 |
| Recall@10 | 0.5000 | 0.1667-0.8333 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.5000 | 0.1667-0.8333 | 6 |
| nDCG@10 | 0.3436 | 0.0718-0.6261 | 6 |

Latency (ms): {"p50": 35.96370000013849, "p95": 50.88552499910293}

###### source: synthetic

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 32 |
| MRR@10 | 0.6155 | 0.5017-0.7318 | 32 |
| Recall@10 | 0.8802 | 0.7917-0.9531 | 32 |
| Recall@20 | 0.9635 | 0.9167-1.0000 | 32 |
| Recall@5 | 0.7500 | 0.6301-0.8542 | 32 |
| nDCG@10 | 0.6499 | 0.5499-0.7467 | 32 |

Latency (ms): {"p50": 36.067050001292955, "p95": 61.0612199998286}

##### hybrid_rerank

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9915 | 0.9858-0.9962 | 1056 |
| MRR@10 | 0.9235 | 0.9088-0.9360 | 1056 |
| Recall@10 | 0.8729 | 0.8591-0.8860 | 1056 |
| Recall@20 | 0.9107 | 0.8990-0.9222 | 1056 |
| Recall@5 | 0.8100 | 0.7942-0.8253 | 1056 |
| nDCG@10 | 0.8234 | 0.8096-0.8354 | 1056 |

Latency (ms): {"p50": 806.9928500044625, "p95": 1360.6632500031992}

retrieval_config: {"mode": "hybrid", "rerank": true, "mmr": false, "top_k": 20, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9910 | 0.9832-0.9974 | 775 |
| MRR@10 | 0.9219 | 0.9055-0.9372 | 775 |
| Recall@10 | 0.8432 | 0.8271-0.8594 | 775 |
| Recall@20 | 0.8897 | 0.8748-0.9039 | 775 |
| Recall@5 | 0.7742 | 0.7561-0.7923 | 775 |
| nDCG@10 | 0.7972 | 0.7830-0.8121 | 775 |

Latency (ms): {"p50": 809.697500000766, "p95": 1319.3966500002716}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 225 |
| MRR@10 | 0.9716 | 0.9544-0.9861 | 225 |
| Recall@10 | 0.9844 | 0.9711-0.9956 | 225 |
| Recall@20 | 0.9889 | 0.9778-0.9978 | 225 |
| Recall@5 | 0.9511 | 0.9289-0.9689 | 225 |
| nDCG@10 | 0.9383 | 0.9232-0.9521 | 225 |

Latency (ms): {"p50": 770.6124999967869, "p95": 1257.0666200015694}

###### category: comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 10 |
| MRR@10 | 0.9500 | 0.8500-1.0000 | 10 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 10 |
| nDCG@10 | 0.9314 | 0.8558-0.9850 | 10 |

Latency (ms): {"p50": 887.2360999994271, "p95": 1316.7647950020182}

###### category: contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.9799 | 0.9498-1.0000 | 8 |

Latency (ms): {"p50": 1386.3674500025809, "p95": 1524.6554650024336}

###### category: injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 4 |
| MRR@10 | 0.8333 | 0.5000-1.0000 | 4 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 4 |
| nDCG@10 | 0.8750 | 0.6250-1.0000 | 4 |

Latency (ms): {"p50": 1504.6483500009344, "p95": 1506.8754650026676}

###### category: multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 20 |
| MRR@10 | 0.6810 | 0.5215-0.8297 | 20 |
| Recall@10 | 0.6417 | 0.5333-0.7419 | 20 |
| Recall@20 | 0.7833 | 0.6667-0.9000 | 20 |
| Recall@5 | 0.5167 | 0.3915-0.6419 | 20 |
| nDCG@10 | 0.5624 | 0.4299-0.6840 | 20 |

Latency (ms): {"p50": 1255.950649996521, "p95": 1499.6609800029546}

###### category: postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.6667 | 0.3333-1.0000 | 6 |
| MRR@10 | 0.2298 | 0.0394-0.5479 | 6 |
| Recall@10 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.1667 | 0.0000-0.5000 | 6 |
| nDCG@10 | 0.3250 | 0.1027-0.6122 | 6 |

Latency (ms): {"p50": 534.1730500003905, "p95": 558.9904250027757}

###### category: simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.7812 | 0.5938-1.0000 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.8366 | 0.6942-1.0000 | 8 |

Latency (ms): {"p50": 1101.3101499993354, "p95": 1484.9353399982647}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9931 | 0.9872-0.9980 | 1018 |
| MRR@10 | 0.9329 | 0.9205-0.9461 | 1018 |
| Recall@10 | 0.8743 | 0.8600-0.8880 | 1018 |
| Recall@20 | 0.9116 | 0.9008-0.9229 | 1018 |
| Recall@5 | 0.8134 | 0.7976-0.8291 | 1018 |
| nDCG@10 | 0.8286 | 0.8156-0.8409 | 1018 |

Latency (ms): {"p50": 804.0153500005545, "p95": 1308.0593549992045}

###### source: postmortems

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.6667 | 0.3333-1.0000 | 6 |
| MRR@10 | 0.2298 | 0.0394-0.5479 | 6 |
| Recall@10 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.1667 | 0.0000-0.5000 | 6 |
| nDCG@10 | 0.3250 | 0.1027-0.6122 | 6 |

Latency (ms): {"p50": 534.1730500003905, "p95": 558.9904250027757}

###### source: synthetic

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 32 |
| MRR@10 | 0.7529 | 0.6261-0.8571 | 32 |
| Recall@10 | 0.8698 | 0.7865-0.9427 | 32 |
| Recall@20 | 0.9271 | 0.8542-0.9844 | 32 |
| Recall@5 | 0.8229 | 0.7135-0.9167 | 32 |
| nDCG@10 | 0.7501 | 0.6317-0.8483 | 32 |

Latency (ms): {"p50": 1379.835349998757, "p95": 1520.5518950020632}

##### hybrid_rerank_mmr

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9924 | 0.9867-0.9972 | 1056 |
| MRR@10 | 0.9240 | 0.9096-0.9365 | 1056 |
| Recall@10 | 0.8711 | 0.8570-0.8840 | 1056 |
| Recall@20 | 0.9055 | 0.8938-0.9167 | 1056 |
| Recall@5 | 0.8086 | 0.7929-0.8239 | 1056 |
| nDCG@10 | 0.8221 | 0.8084-0.8340 | 1056 |

Latency (ms): {"p50": 836.1713999947824, "p95": 1400.1247250016604}

retrieval_config: {"mode": "hybrid", "rerank": true, "mmr": true, "top_k": 20, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9923 | 0.9845-0.9987 | 775 |
| MRR@10 | 0.9228 | 0.9065-0.9379 | 775 |
| Recall@10 | 0.8406 | 0.8245-0.8568 | 775 |
| Recall@20 | 0.8839 | 0.8690-0.8981 | 775 |
| Recall@5 | 0.7703 | 0.7529-0.7877 | 775 |
| nDCG@10 | 0.7929 | 0.7790-0.8077 | 775 |

Latency (ms): {"p50": 840.0863999995636, "p95": 1339.578080001229}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 225 |
| MRR@10 | 0.9713 | 0.9538-0.9861 | 225 |
| Recall@10 | 0.9844 | 0.9711-0.9956 | 225 |
| Recall@20 | 0.9889 | 0.9778-0.9978 | 225 |
| Recall@5 | 0.9556 | 0.9356-0.9733 | 225 |
| nDCG@10 | 0.9467 | 0.9316-0.9609 | 225 |

Latency (ms): {"p50": 806.2500000014552, "p95": 1273.3318599988704}

###### category: comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 10 |
| MRR@10 | 0.9500 | 0.8500-1.0000 | 10 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 10 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 10 |
| nDCG@10 | 0.9463 | 0.8712-0.9920 | 10 |

Latency (ms): {"p50": 891.3148499996169, "p95": 1335.1488100008282}

###### category: contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.9699 | 0.9398-1.0000 | 8 |

Latency (ms): {"p50": 1394.2872500010708, "p95": 1583.2888950008055}

###### category: injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 4 |
| MRR@10 | 0.8333 | 0.5000-1.0000 | 4 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 4 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 4 |
| nDCG@10 | 0.8750 | 0.6250-1.0000 | 4 |

Latency (ms): {"p50": 1527.3909499992442, "p95": 1539.5608150003682}

###### category: multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 20 |
| MRR@10 | 0.6788 | 0.5237-0.8217 | 20 |
| Recall@10 | 0.6417 | 0.5333-0.7419 | 20 |
| Recall@20 | 0.7333 | 0.6167-0.8500 | 20 |
| Recall@5 | 0.5417 | 0.4167-0.6585 | 20 |
| nDCG@10 | 0.5629 | 0.4310-0.6848 | 20 |

Latency (ms): {"p50": 1279.0622000029543, "p95": 1562.1369449938356}

###### category: postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.6667 | 0.3333-1.0000 | 6 |
| MRR@10 | 0.2280 | 0.0375-0.5479 | 6 |
| Recall@10 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.1667 | 0.0000-0.5000 | 6 |
| nDCG@10 | 0.3230 | 0.1008-0.6121 | 6 |

Latency (ms): {"p50": 568.065999999817, "p95": 587.4428500010254}

###### category: simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 8 |
| MRR@10 | 0.7812 | 0.5938-1.0000 | 8 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@20 | 1.0000 | 1.0000-1.0000 | 8 |
| Recall@5 | 1.0000 | 1.0000-1.0000 | 8 |
| nDCG@10 | 0.8366 | 0.6942-1.0000 | 8 |

Latency (ms): {"p50": 1114.29859999771, "p95": 1493.653794999409}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9941 | 0.9892-0.9980 | 1018 |
| MRR@10 | 0.9336 | 0.9212-0.9465 | 1018 |
| Recall@10 | 0.8723 | 0.8585-0.8870 | 1018 |
| Recall@20 | 0.9072 | 0.8954-0.9185 | 1018 |
| Recall@5 | 0.8119 | 0.7966-0.8281 | 1018 |
| nDCG@10 | 0.8274 | 0.8145-0.8395 | 1018 |

Latency (ms): {"p50": 831.8454500004009, "p95": 1325.2606950012705}

###### source: postmortems

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.6667 | 0.3333-1.0000 | 6 |
| MRR@10 | 0.2280 | 0.0375-0.5479 | 6 |
| Recall@10 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@20 | 0.6667 | 0.3333-1.0000 | 6 |
| Recall@5 | 0.1667 | 0.0000-0.5000 | 6 |
| nDCG@10 | 0.3230 | 0.1008-0.6121 | 6 |

Latency (ms): {"p50": 568.065999999817, "p95": 587.4428500010254}

###### source: synthetic

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 32 |
| MRR@10 | 0.7487 | 0.6232-0.8545 | 32 |
| Recall@10 | 0.8698 | 0.7865-0.9427 | 32 |
| Recall@20 | 0.8958 | 0.8125-0.9635 | 32 |
| Recall@5 | 0.8229 | 0.7135-0.9167 | 32 |
| nDCG@10 | 0.7462 | 0.6313-0.8412 | 32 |

Latency (ms): {"p50": 1416.7497499984165, "p95": 1580.6820899968443}

### Chunking

#### chunking

##### chunk_structure

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| MRR@10 | 0.5465 | 0.4167-0.6731 | 26 |
| Recall@10 | 0.8205 | 0.6987-0.9231 | 26 |
| context_tokens_to_first_hit | 200.6667 | 121.8036-295.4464 | 21 |
| evidence-hit@10 | 0.8077 | 0.6538-0.9615 | 26 |

Latency (ms): {"p50": 34.640800000488525, "p95": 52.336799999466166}

statistics: {"document_count": 284, "chunk_count": 469, "mean_chunk_tokens": 91.05330490405117, "chunks_per_document": 1.6514084507042253}

##### chunk_fixed

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| MRR@10 | 0.6712 | 0.5410-0.7981 | 26 |
| Recall@10 | 0.8718 | 0.7756-0.9615 | 26 |
| context_tokens_to_first_hit | 626.0909 | 441.2148-862.1250 | 22 |
| evidence-hit@10 | 0.8462 | 0.6923-0.9615 | 26 |

Latency (ms): {"p50": 33.89469999819994, "p95": 58.51062499641557}

statistics: {"document_count": 284, "chunk_count": 347, "mean_chunk_tokens": 133.95965417867436, "chunks_per_document": 1.221830985915493}

### Embeddings

#### embeddings

##### BAAI/bge-small-en-v1.5/dense

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9933 | 0.9833-1.0000 | 300 |
| MRR@10 | 0.9430 | 0.9207-0.9628 | 300 |
| Recall@10 | 0.9367 | 0.9167-0.9567 | 300 |
| nDCG@10 | 0.8754 | 0.8541-0.8958 | 300 |

Latency (ms): {"p50": 24.157849999028258, "p95": 43.39612000476336}

index_seconds: 241.22593930000585

paragraphs: 2987

retrieval_config: {"mode": "dense", "rerank": false, "mmr": false, "top_k": 10, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9917 | 0.9793-1.0000 | 242 |
| MRR@10 | 0.9315 | 0.9050-0.9569 | 242 |
| Recall@10 | 0.9215 | 0.8967-0.9443 | 242 |
| nDCG@10 | 0.8524 | 0.8295-0.8749 | 242 |

Latency (ms): {"p50": 25.152350001008017, "p95": 43.05396499476046}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 58 |
| MRR@10 | 0.9914 | 0.9741-1.0000 | 58 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 58 |
| nDCG@10 | 0.9718 | 0.9548-0.9863 | 58 |

Latency (ms): {"p50": 21.279250002407935, "p95": 43.73644000261265}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9933 | 0.9833-1.0000 | 300 |
| MRR@10 | 0.9430 | 0.9207-0.9628 | 300 |
| Recall@10 | 0.9367 | 0.9167-0.9567 | 300 |
| nDCG@10 | 0.8754 | 0.8541-0.8958 | 300 |

Latency (ms): {"p50": 24.157849999028258, "p95": 43.39612000476336}

##### BAAI/bge-small-en-v1.5/hybrid

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9933 | 0.9833-1.0000 | 300 |
| MRR@10 | 0.8976 | 0.8708-0.9226 | 300 |
| Recall@10 | 0.9550 | 0.9383-0.9717 | 300 |
| nDCG@10 | 0.8402 | 0.8186-0.8597 | 300 |

Latency (ms): {"p50": 34.72404999774881, "p95": 49.00330999626022}

index_seconds: 241.22593930000585

paragraphs: 2987

retrieval_config: {"mode": "hybrid", "rerank": false, "mmr": false, "top_k": 10, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9917 | 0.9793-1.0000 | 242 |
| MRR@10 | 0.9099 | 0.8828-0.9370 | 242 |
| Recall@10 | 0.9442 | 0.9194-0.9628 | 242 |
| nDCG@10 | 0.8391 | 0.8159-0.8601 | 242 |

Latency (ms): {"p50": 34.559099996840814, "p95": 48.95950499630998}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 58 |
| MRR@10 | 0.8463 | 0.7830-0.9124 | 58 |
| Recall@10 | 1.0000 | 1.0000-1.0000 | 58 |
| nDCG@10 | 0.8448 | 0.8053-0.8828 | 58 |

Latency (ms): {"p50": 35.425850001047365, "p95": 47.87382999966212}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9933 | 0.9833-1.0000 | 300 |
| MRR@10 | 0.8976 | 0.8708-0.9226 | 300 |
| Recall@10 | 0.9550 | 0.9383-0.9717 | 300 |
| nDCG@10 | 0.8402 | 0.8186-0.8597 | 300 |

Latency (ms): {"p50": 34.72404999774881, "p95": 49.00330999626022}

##### sentence-transformers/all-MiniLM-L6-v2/dense

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9833 | 0.9699-0.9967 | 300 |
| MRR@10 | 0.8748 | 0.8451-0.9036 | 300 |
| Recall@10 | 0.8683 | 0.8400-0.8950 | 300 |
| nDCG@10 | 0.7812 | 0.7549-0.8074 | 300 |

Latency (ms): {"p50": 19.78564999808441, "p95": 39.23293999760063}

index_seconds: 160.55014690000098

paragraphs: 2987

retrieval_config: {"mode": "dense", "rerank": false, "mmr": false, "top_k": 10, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9793 | 0.9627-0.9959 | 242 |
| MRR@10 | 0.8713 | 0.8353-0.9033 | 242 |
| Recall@10 | 0.8471 | 0.8161-0.8760 | 242 |
| nDCG@10 | 0.7602 | 0.7314-0.7867 | 242 |

Latency (ms): {"p50": 19.898350001312792, "p95": 39.66431000153533}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 58 |
| MRR@10 | 0.8894 | 0.8305-0.9440 | 58 |
| Recall@10 | 0.9569 | 0.9224-0.9914 | 58 |
| nDCG@10 | 0.8687 | 0.8187-0.9130 | 58 |

Latency (ms): {"p50": 19.197700003132923, "p95": 37.86932999464625}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9833 | 0.9699-0.9967 | 300 |
| MRR@10 | 0.8748 | 0.8451-0.9036 | 300 |
| Recall@10 | 0.8683 | 0.8400-0.8950 | 300 |
| nDCG@10 | 0.7812 | 0.7549-0.8074 | 300 |

Latency (ms): {"p50": 19.78564999808441, "p95": 39.23293999760063}

##### sentence-transformers/all-MiniLM-L6-v2/hybrid

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9900 | 0.9799-1.0000 | 300 |
| MRR@10 | 0.8496 | 0.8154-0.8802 | 300 |
| Recall@10 | 0.9050 | 0.8783-0.9284 | 300 |
| nDCG@10 | 0.7804 | 0.7529-0.8061 | 300 |

Latency (ms): {"p50": 34.197049997601425, "p95": 48.76136499624408}

index_seconds: 160.55014690000098

paragraphs: 2987

retrieval_config: {"mode": "hybrid", "rerank": false, "mmr": false, "top_k": 10, "candidate_k": 50, "weights": {"dense": 1.0, "sparse": 1.0}, "rrf_k": 60, "mmr_lambda": 0.7, "max_chunks_per_doc": 3, "rerank_top_n": 30, "entity_boost": 0.15}

###### category: bridge

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9876 | 0.9711-1.0000 | 242 |
| MRR@10 | 0.8631 | 0.8282-0.8950 | 242 |
| Recall@10 | 0.8864 | 0.8574-0.9132 | 242 |
| nDCG@10 | 0.7732 | 0.7445-0.7996 | 242 |

Latency (ms): {"p50": 34.95839999959571, "p95": 49.15638000165927}

###### category: comparison

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 1.0000 | 1.0000-1.0000 | 58 |
| MRR@10 | 0.7937 | 0.7181-0.8664 | 58 |
| Recall@10 | 0.9828 | 0.9569-1.0000 | 58 |
| nDCG@10 | 0.8101 | 0.7618-0.8573 | 58 |

Latency (ms): {"p50": 31.494849998125574, "p95": 46.13456499791937}

###### source: hotpotqa

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| Hit@10 | 0.9900 | 0.9799-1.0000 | 300 |
| MRR@10 | 0.8496 | 0.8154-0.8802 | 300 |
| Recall@10 | 0.9050 | 0.8783-0.9284 | 300 |
| nDCG@10 | 0.7804 | 0.7529-0.8061 | 300 |

Latency (ms): {"p50": 34.197049997601425, "p95": 48.76136499624408}

### End-to-end

not run yet
