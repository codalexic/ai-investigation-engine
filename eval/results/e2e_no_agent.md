| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.5000 | 0.3519-0.6296 | 54 |
| citation_precision | 0.6710 | 0.5619-0.7730 | 46 |
| citation_recall | 0.7935 | 0.6993-0.8805 | 46 |
| contradiction_detection_rate | 0.8333 | 0.5000-1.0000 | 6 |
| estimated_cost | 0.0004 | 0.0003-0.0004 | 54 |
| exact_match | 0.0000 | 0.0000-0.0000 | 16 |
| faithfulness | 0.5865 | 0.4919-0.6723 | 52 |
| false_abstain_rate | 0.5870 | 0.4565-0.7391 | 46 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 0.6296 | 0.5275-0.7315 | 54 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 54 |
| judge_tokens | 388.7222 | 361.1056-422.6898 | 54 |
| token_f1 | 0.0661 | 0.0285-0.1088 | 16 |
| tokens | 1797.6481 | 1731.9227-1860.9843 | 54 |

Latency (ms): {"p50": 3282.166050000342, "p95": 10460.848530001922}

### comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.3750 | 0.1250-0.7500 | 8 |
| citation_precision | 0.9250 | 0.7750-1.0000 | 8 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0004 | 0.0004-0.0004 | 8 |
| exact_match | 0.0000 | 0.0000-0.0000 | 7 |
| faithfulness | 0.6094 | 0.4594-0.7969 | 8 |
| false_abstain_rate | 0.6250 | 0.2500-0.8750 | 8 |
| judge_correctness | 0.5625 | 0.3750-0.7500 | 8 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 8 |
| judge_tokens | 370.3750 | 342.1250-404.5125 | 8 |
| token_f1 | 0.0735 | 0.0220-0.1295 | 7 |
| tokens | 1908.8750 | 1770.7625-2038.2500 | 8 |

Latency (ms): {"p50": 2904.5973500005857, "p95": 8538.278825000449}

### contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.3333 | 0.0000-0.6667 | 6 |
| citation_precision | 0.7222 | 0.5556-0.8889 | 6 |
| citation_recall | 0.9167 | 0.7500-1.0000 | 6 |
| contradiction_detection_rate | 0.8333 | 0.5000-1.0000 | 6 |
| estimated_cost | 0.0004 | 0.0003-0.0004 | 6 |
| faithfulness | 0.6556 | 0.4608-0.8667 | 6 |
| false_abstain_rate | 0.6667 | 0.3333-1.0000 | 6 |
| judge_correctness | 0.5000 | 0.2500-0.7500 | 6 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 6 |
| judge_tokens | 435.0000 | 392.9917-468.1667 | 6 |
| tokens | 1722.1667 | 1671.1625-1768.6708 | 6 |

Latency (ms): {"p50": 3779.9338499999067, "p95": 4410.796299998765}

### injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 1.0000 | 1.0000-1.0000 | 3 |
| citation_precision | 0.1944 | 0.0000-0.3333 | 3 |
| citation_recall | 0.6667 | 0.0000-1.0000 | 3 |
| estimated_cost | 0.0004 | 0.0003-0.0004 | 3 |
| faithfulness | 1.0000 | 1.0000-1.0000 | 3 |
| false_abstain_rate | 0.0000 | 0.0000-0.0000 | 3 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 3 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 3 |
| judge_tokens | 378.0000 | 308.0000-427.0000 | 3 |
| tokens | 1791.0000 | 1593.0000-1933.0000 | 3 |

Latency (ms): {"p50": 4094.1184000002977, "p95": 4378.907379999691}

### multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.0625 | 0.0000-0.1875 | 16 |
| citation_precision | 0.7417 | 0.5563-0.9187 | 16 |
| citation_recall | 0.5625 | 0.4271-0.7083 | 16 |
| estimated_cost | 0.0004 | 0.0003-0.0004 | 16 |
| exact_match | 0.0000 | 0.0000-0.0000 | 9 |
| faithfulness | 0.4556 | 0.3011-0.6267 | 15 |
| false_abstain_rate | 0.9375 | 0.8125-1.0000 | 16 |
| judge_correctness | 0.3125 | 0.1562-0.4688 | 16 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 16 |
| judge_tokens | 370.1875 | 340.7359-403.4500 | 16 |
| token_f1 | 0.0603 | 0.0117-0.1198 | 9 |
| tokens | 1829.3750 | 1690.5516-1952.2328 | 16 |

Latency (ms): {"p50": 2986.522750000404, "p95": 13974.286099998608}

### postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.6000 | 0.2000-1.0000 | 5 |
| citation_precision | 0.1700 | 0.0450-0.3450 | 5 |
| citation_recall | 0.8000 | 0.4000-1.0000 | 5 |
| estimated_cost | 0.0004 | 0.0002-0.0005 | 5 |
| faithfulness | 0.6516 | 0.4713-0.8045 | 5 |
| false_abstain_rate | 0.4000 | 0.0000-0.8000 | 5 |
| judge_correctness | 0.5000 | 0.2000-0.8000 | 5 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 5 |
| judge_tokens | 659.4000 | 500.0000-768.8800 | 5 |
| tokens | 1927.2000 | 1697.4000-2157.0000 | 5 |

Latency (ms): {"p50": 8465.652200000477, "p95": 13988.34485999978}

### simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.8750 | 0.6250-1.0000 | 8 |
| citation_precision | 0.7292 | 0.5411-0.9375 | 8 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0003 | 0.0003-0.0004 | 8 |
| faithfulness | 0.9292 | 0.8292-1.0000 | 8 |
| false_abstain_rate | 0.1250 | 0.0000-0.3750 | 8 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 8 |
| judge_estimated_cost | 0.0000 | 0.0000-0.0001 | 8 |
| judge_tokens | 331.2500 | 295.7500-366.7500 | 8 |
| tokens | 1648.1250 | 1563.0656-1719.6281 | 8 |

Latency (ms): {"p50": 2434.2830999994476, "p95": 6009.745074999772}

### unanswerable

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0003 | 0.0003-0.0004 | 8 |
| faithfulness | 0.1667 | 0.0000-0.3810 | 7 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 8 |
| judge_estimated_cost | 0.0000 | 0.0000-0.0000 | 8 |
| judge_tokens | 301.7500 | 267.5000-338.6250 | 8 |
| tokens | 1750.6250 | 1578.4813-1930.7469 | 8 |

Latency (ms): {"p50": 3394.6203999994395, "p95": 5478.350890001365}
