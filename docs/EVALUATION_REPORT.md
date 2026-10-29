# Evaluation Report

This report covers how I tested the engine, which metrics I used, what came out, and what the results say about where
the system works and where it breaks. All numbers come from files in `eval/results/`. A full generated dump, with
per-category tables, stage timings and individual failure cases, is in
[`eval/results/REPORT.md`](../eval/results/REPORT.md).

## 1. What I evaluated

The evaluation answers four questions:

1. **Does hybrid retrieval actually beat dense or keyword search alone,** and is the reranker worth its cost?
2. **Which chunking strategy and which embedding model** should be the default?
3. **Does the agent (planner + tool loop) answer better** than plain single-shot RAG, and when?
4. **Is the engine honest:** does it cite correctly, flag contradictions, refuse unanswerable questions and ignore
   injected instructions?

## 2. Test data

**Investigation set: 66 hand-checked questions** in seven categories:

| Category | Count | What it tests |
|---|---|---|
| simple | 8 | One fact from one document (e.g. "What did CHG-1051 change?") |
| multi_hop | 20 | The answer needs a second document that the question never names |
| comparison / multi_doc | 10 | Facts from several documents combined |
| contradiction | 8 | Sources disagree; the answer must say so |
| unanswerable | 10 | The answer isn't in the corpus; the engine must abstain |
| postmortem | 6 | Questions about real public incident write-ups |
| injection | 4 | A retrieved document contains instructions trying to hijack the answer |

The synthetic questions are built from a ground-truth file (`eval/data/synthetic_ground_truth.json`) that records the
planted facts, contradictions and gaps. The HotpotQA questions use the dataset's gold supporting paragraphs. Every gold
document id is validated against the corpus, so a typo can't silently make a question unanswerable.

**Retrieval benchmark: 1,018 HotpotQA questions.** These are a fixed random sample of 1,000 questions (seed 42) plus the
HotpotQA questions from the investigation set, run against the full 66.8k-document index. Each has two gold paragraphs.
This set needs no LLM, so it is large enough for confidence intervals.

**End-to-end runs use a fixed 54-question subset** of the investigation set that keeps all seven categories (8 simple,
16 multi-hop, 8 multi-doc, 6 contradiction, 8 unanswerable, 5 postmortem, 3 injection).

## 3. Metrics

**Retrieval.** Results are de-duplicated by document before scoring.
- **Recall@K:** share of gold documents in the top K.
- **MRR@10:** 1 / rank of the first relevant document.
- **nDCG@10:** rewards relevant documents near the top.
- **Latency p50/p95.**
- 95% confidence intervals use bootstrap resampling (1,000 samples).

**Answers.**
- **Correctness:** an LLM judge scores each answer 0 / 0.5 / 1 against the reference answer. The judge
  (gemini-3.8-flash) comes from a different provider than the main generator, so a model never grades its own output.
  I also report SQuAD token F1 on HotpotQA (see section 6 for why it is low).
- **Citation precision / recall:** of the documents cited, how many are gold; of the gold documents, how many are cited.
- **Faithfulness:** share of answer claims the verifier found supported by the cited text.
- **Abstention accuracy, false-abstention rate** (refused although the answer existed) and **false-answer rate**
  (answered an unanswerable question).
- **Contradiction detection:** the answer reports the conflict *and* cites a gold source for it.
- **Injection resistance:** the judge checks the answer didn't follow the injected instruction, including paraphrases.
- **Cost and latency:** tokens and estimated cost per question.

## 4. Results

### 4.1 Retrieval (HotpotQA, n = 1,018)

| Config | Recall@5 | Recall@10 | Recall@20 | MRR@10 | nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| dense | 0.778 | 0.839 | 0.872 | 0.898 | 0.792 | 27 |
| BM25 | 0.641 | 0.760 | 0.832 | 0.795 | 0.669 | 19 |
| hybrid (weighted RRF) | 0.785 | 0.862 | 0.905 | 0.881 | 0.783 | 41 |
| hybrid + rerank | **0.813** | **0.874** | **0.912** | 0.933 | **0.829** | 804 |
| hybrid + rerank + MMR | 0.812 | 0.872 | 0.907 | **0.934** | 0.827 | 832 |

Recall@10 intervals: dense 0.822–0.855, hybrid 0.849–0.877, hybrid + rerank 0.860–0.888.

On the investigation set, broken down by category (Recall@10 / MRR@10, hybrid + rerank): simple 1.00 / 0.78,
multi-doc 1.00 / 0.95, contradiction 1.00 / 1.00, multi-hop **0.64** / 0.68, postmortem 0.67 / 0.23.

### 4.2 Chunking (284 long documents: synthetic + post-mortems)

| | Structure-aware | Fixed 400-token windows |
|---|---|---|
| Recall@10 | 0.821 | 0.872 |
| MRR@10 | 0.546 | 0.671 |
| Evidence hit@10 | 0.808 | 0.846 |
| Context tokens to first evidence | **201** | 626 |
| Mean chunk size (tokens) | 91 | 134 |

### 4.3 Embedding models (300-question subset, 2,987 paragraphs)

| Model | Dense Recall@10 | MRR@10 | Index time | Query p50 |
|---|---|---|---|---|
| bge-small-en-v1.5 | **0.937** (0.917–0.957) | **0.943** | 241 s | 24 ms |
| all-MiniLM-L6-v2 | 0.868 (0.840–0.895) | 0.875 | 161 s | 20 ms |

### 4.4 End to end (54 questions)

Three configurations:
- **agent:** planner + tool loop on gemini-3.5-flash-lite;
- **single-shot (flash-lite):** the same pipeline without the tool loop, on the same model;
- **single-shot (gpt-oss-120b):** the same single-shot pipeline on a larger model.

| | Agent | Single-shot (flash-lite) | Single-shot (gpt-oss-120b) |
|---|---|---|---|
| Correctness | **0.81** | 0.66 | 0.63 |
| Citation precision | 0.68 | 0.62 | 0.67 |
| Citation recall | **0.85** | 0.78 | 0.79 |
| Faithfulness | **0.82** | 0.78 | 0.59 |
| Abstention accuracy | **0.76** | 0.63 | 0.50 |
| False-abstention rate | **0.28** | 0.43 | 0.59 |
| False-answer rate | 0.00 | 0.00 | 0.00 |
| Contradiction detection (n = 6) | 0.50 | 0.50 | **0.83** |
| Injection resistance (n = 3) | 1.00 | 1.00 | 1.00 |
| Tokens / question | 7.9k | 1.9k | 1.8k |
| Latency p50 | 38 s | 10 s | 3 s |

Correctness by category:

| Category | Agent | Single-shot (flash-lite) | Single-shot (gpt-oss-120b) |
|---|---|---|---|
| simple | 1.00 | 0.88 | 1.00 |
| multi_hop | **0.86** | 0.33 | 0.31 |
| comparison / multi_doc | 0.81 | 0.88 | 0.56 |
| contradiction | 0.80 | 0.60 | 0.50 |
| unanswerable | 1.00 | 1.00 | 1.00 |
| postmortem | 0.25 | 0.62 | 0.50 |

### 4.5 Performance at full scale (67k-point index, laptop CPU)

Without reranking, retrieval is cheap: hybrid search takes 36 ms p50 at about 28 QPS, and p95 stays under 300 ms up to
8 concurrent requests. The Qdrant query itself is 15–17 ms, and fusion, boosts and MMR add under 10 ms. The
cross-encoder dominates everything else: about 0.85 s p50 and about 1 QPS, because ONNX already uses every core and
concurrency only adds queueing. Indexing ran at 12.3 records/s (66,795 records in about 90 minutes). That is a one-off
cost: the index is built locally and migrated, never rebuilt in the cloud.

## 5. What the results say

**Hybrid search is worth it.** Fusion lifts Recall@10 from 0.839 (dense) to 0.862 and Recall@20 to 0.905, so the two
retrievers miss *different* documents. Fusion alone slightly lowers MRR, because a lexical match can outvote a strong
dense first hit; the reranker fixes that and gives the best result on every metric (MRR 0.933). The price is roughly
20× the latency, which is why the reranker can be switched off; the free-tier demo runs without it.

**BM25 earns its place on identifiers.** On simple questions BM25 has MRR 0.79 against 0.44 for dense: a question like
"What did CHG-1051 change?" depends on an exact id that the embedding barely separates from CHG-1052. In one traced
case the change-log chunk was dense rank 25 and BM25 rank 2, and hybrid ranked it first. This is the reason the
tokenizer keeps `CHG-1051` and `payment-gateway` whole.

**MMR doesn't help here.** It is within noise on HotpotQA and slightly hurts multi-hop recall at depth, because the
second gold document often looks like the first one and diversification pushes it down. I left it available but off
by default.

**Chunking: same recall, a third of the context.** Fixed windows score a bit higher on rank metrics, but with only 26
questions the intervals overlap heavily, so the difference isn't significant. Structure-aware chunks reach the evidence
with 201 tokens of context instead of 626, which matters for cost, the context budget and the NLI verifier's
512-token window. I kept structure-aware as the default.

**bge-small beats MiniLM, and the gap is real.** The confidence intervals don't overlap. MiniLM indexes about 33%
faster, but indexing happens once while retrieval quality counts on every question.

**The agent's gain is almost entirely multi-hop.** Same model, same retrieval, same verifier: the only difference is the
tool loop, and correctness goes from 0.66 to 0.81. Per question, the agent wins 14 and loses 4. On multi-hop questions
it goes from 0.33 to 0.86. A typical case is *"What does the service whose change caused INC-2031 depend on?"*.
Single-shot retrieval finds only INC-2031 documents and the model correctly abstains. The agent reads the review,
picks up CHG-1042, follows it to payment-gateway and answers "auth-service and ledger-service" with three citations.
Most of the single-shot abstentions are this pattern: honest, but avoidable.

**A bigger model doesn't replace the agent.** gpt-oss-120b in single-shot mode lands at 0.63, about the same as
flash-lite. It is faster and abstains even more. It does catch more contradictions (0.83 vs 0.50): it tends to report a
disagreement it sees in the evidence, while flash-lite tends to state the newer value and drop the older one. Model size
changes *how* the system fails; the agent changes *which questions* it can answer.

**Honesty holds up.** No configuration answered any of the unanswerable questions, and none followed an injected
instruction.

## 6. Where it fails and why

1. **Second-hop documents are invisible to a single search.** Multi-hop is the weakest retrieval category (Recall@10
   0.64). Take *"Which team owns the service whose change caused INC-2040?"*. A single search finds every INC-2040
   document but never the change log or the operations page, because the bridge entities (CHG-1051, then
   ledger-service) aren't in the question. HotpotQA bridge questions fail the same way. This is exactly what the tool
   loop fixes.
2. **Vague questions get several right answers.** "What went wrong at Cloudflare?" has one gold incident, but the corpus
   holds several Cloudflare post-mortems. The agent makes this *worse* (0.62 → 0.25): the more it searches, the more
   valid incidents it finds, and the further the answer drifts from the one the grader expects. This is mostly a flaw in
   how the question is written, not in retrieval.
3. **Near-duplicates take up space.** The duplicated INC-2031 export is flagged at ingestion, but it still takes a second
   slot in the top 5, because the per-document cap works on document id rather than on duplicate groups.
4. **CSV files chunk poorly.** The change log is chunked as blocks of rows, so one chunk mixes a dozen unrelated changes
   and its embedding becomes a blur. Id queries only survive because of BM25.
5. **Contradiction detection is only 0.50 with flash-lite.** The verifier flags conflicts it can see. When the model
   quietly picks the newer value and doesn't mention the older one, there is nothing for the verifier to flag.
6. **Token F1 is low (0.06–0.09), and that's expected.** It compares answers word by word with HotpotQA's short reference
   answers ("Pleiospilos"). The engine answers in full sentences with citations, so word overlap stays low even when
   the answer is right. Judge correctness is the metric I rely on; F1 is reported for comparability only.

**Cost of the agent.** It uses 4.2× the tokens and about 3.8× the latency. On simple questions it gains nothing (1.00
vs 0.88), so routing would pay off: answer directly when the first search already covers every entity in the plan, and
only enter the tool loop when one is missing.

## 7. Limitations of this evaluation

- **The abstention thresholds were tuned by hand on this same question set.** That makes the end-to-end numbers somewhat
  optimistic. Only a couple of values were tuned, and the retrieval benchmark is unaffected, but a proper held-out
  split would be the right fix.
- **Some categories are small** (6 contradiction, 3 injection), so their numbers carry wide uncertainty.
- **The judge is itself an LLM.** It uses a strict rubric and a different provider than the generator, but it is not
  a human grader.
- **Three questions per Gemini run failed** with a provider transport error. I counted them as failed answers rather
  than dropping them, so the Gemini numbers are slight underestimates.
- **The synthetic company is template-generated,** so real archives would be messier.

## 8. What I would improve next

- **Cheap query expansion for single-shot mode:** add `CHG-`/`INC-` ids found in the top-3 chunks to a second query.
  This is the deterministic version of what the agent does.
- **Collapse duplicate groups at query time**, using `duplicate_of` as the cap key.
- **Row-level chunking for CSV and JSON records**, repeating the header in each chunk.
- **Rewrite the post-mortem questions** so each names one incident.
- **Route between single-shot and agent** based on whether the plan's entities are already covered.
- **Reranker latency:** rerank only when the fused ranking is uncertain, cache scores per (query, chunk), or use a
  quantised model.
- **A held-out test split** for threshold tuning.

## 9. Reproducing the results

```bash
make data              # corpora + evaluation set (deterministic)
make index             # main index
make index-chunking    # one collection per chunking strategy
make eval-retrieval    # HotpotQA + investigation set, all retrieval configs
make eval-chunking
make eval-embeddings
make eval-e2e          # resumable: answers are cached under eval/cache/
make benchmark
make report            # regenerates eval/results/REPORT.md
```

End-to-end runs cache every answer, so if a free-tier quota runs out, rerunning the same command continues where it
stopped.
