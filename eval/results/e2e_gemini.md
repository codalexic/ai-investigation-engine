| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.7593 | 0.6481-0.8704 | 54 |
| citation_precision | 0.6769 | 0.5710-0.7784 | 46 |
| citation_recall | 0.8478 | 0.7500-0.9348 | 46 |
| contradiction_detection_rate | 0.5000 | 0.1667-0.8333 | 6 |
| estimated_cost | 0.0009 | 0.0008-0.0010 | 54 |
| exact_match | 0.0000 | 0.0000-0.0000 | 16 |
| faithfulness | 0.8241 | 0.7401-0.8986 | 47 |
| false_abstain_rate | 0.2826 | 0.1739-0.4130 | 46 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 0.8100 | 0.7100-0.9000 | 50 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 50 |
| judge_tokens | 385.9200 | 351.3100-430.9225 | 50 |
| token_f1 | 0.0892 | 0.0625-0.1165 | 16 |
| tokens | 7864.3333 | 6758.4574-8985.6495 | 54 |

Latency (ms): {"p50": 37685.87475000095, "p95": 103222.15388000054}

### comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.8750 | 0.6250-1.0000 | 8 |
| citation_precision | 0.9583 | 0.8750-1.0000 | 8 |
| citation_recall | 0.9375 | 0.8125-1.0000 | 8 |
| estimated_cost | 0.0010 | 0.0008-0.0012 | 8 |
| exact_match | 0.0000 | 0.0000-0.0000 | 7 |
| faithfulness | 0.9018 | 0.7766-1.0000 | 8 |
| false_abstain_rate | 0.1250 | 0.0000-0.3750 | 8 |
| judge_correctness | 0.8125 | 0.5625-1.0000 | 8 |
| judge_estimated_cost | 0.0000 | 0.0000-0.0001 | 8 |
| judge_tokens | 330.1250 | 311.2281-354.1281 | 8 |
| token_f1 | 0.1041 | 0.0636-0.1458 | 7 |
| tokens | 8947.7500 | 7033.6750-11290.7219 | 8 |

Latency (ms): {"p50": 24559.52774999969, "p95": 118203.18815999938}

### contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.8333 | 0.5000-1.0000 | 6 |
| citation_precision | 0.5667 | 0.2996-0.8333 | 6 |
| citation_recall | 0.7500 | 0.4167-1.0000 | 6 |
| contradiction_detection_rate | 0.5000 | 0.1667-0.8333 | 6 |
| estimated_cost | 0.0008 | 0.0005-0.0011 | 6 |
| faithfulness | 0.9714 | 0.9143-1.0000 | 5 |
| false_abstain_rate | 0.1667 | 0.0000-0.5000 | 6 |
| judge_correctness | 0.8000 | 0.6000-1.0000 | 5 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 5 |
| judge_tokens | 411.4000 | 392.0000-430.8000 | 5 |
| tokens | 7165.5000 | 3822.4167-10120.5833 | 6 |

Latency (ms): {"p50": 37565.26655000198, "p95": 90845.50030000083}

### injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.3333 | 0.0000-1.0000 | 3 |
| citation_precision | 0.7778 | 0.3333-1.0000 | 3 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 3 |
| estimated_cost | 0.0009 | 0.0005-0.0010 | 3 |
| faithfulness | 0.6667 | 0.5000-1.0000 | 3 |
| false_abstain_rate | 0.6667 | 0.0000-1.0000 | 3 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 0.3333 | 0.0000-1.0000 | 3 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 3 |
| judge_tokens | 397.0000 | 329.0000-491.0000 | 3 |
| tokens | 7504.6667 | 4135.0000-9453.0000 | 3 |

Latency (ms): {"p50": 40032.6023000016, "p95": 48351.24776000084}

### multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.7500 | 0.5000-0.9375 | 16 |
| citation_precision | 0.8292 | 0.6833-0.9542 | 16 |
| citation_recall | 0.8750 | 0.7188-1.0000 | 16 |
| estimated_cost | 0.0010 | 0.0008-0.0011 | 16 |
| exact_match | 0.0000 | 0.0000-0.0000 | 9 |
| faithfulness | 0.8500 | 0.7000-0.9556 | 15 |
| false_abstain_rate | 0.2500 | 0.0625-0.5000 | 16 |
| judge_correctness | 0.8571 | 0.6786-1.0000 | 14 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 14 |
| judge_tokens | 371.2857 | 343.8500-405.8643 | 14 |
| token_f1 | 0.0776 | 0.0486-0.1054 | 9 |
| tokens | 8612.4375 | 6942.7859-10065.2422 | 16 |

Latency (ms): {"p50": 55387.12569999916, "p95": 98320.140275001}

### postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.2000 | 0.0000-0.6000 | 5 |
| citation_precision | 0.0444 | 0.0000-0.0889 | 5 |
| citation_recall | 0.4000 | 0.0000-0.8000 | 5 |
| estimated_cost | 0.0005 | 0.0002-0.0009 | 5 |
| faithfulness | 0.7486 | 0.6196-0.8421 | 4 |
| false_abstain_rate | 0.8000 | 0.4000-1.0000 | 5 |
| judge_correctness | 0.2500 | 0.0000-0.5000 | 4 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 4 |
| judge_tokens | 780.5000 | 582.5000-978.5000 | 4 |
| tokens | 4251.4000 | 2173.0000-5664.6000 | 5 |

Latency (ms): {"p50": 24251.08309999996, "p95": 42725.59285999814}

### simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.8750 | 0.6250-1.0000 | 8 |
| citation_precision | 0.5312 | 0.3542-0.7292 | 8 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0005 | 0.0004-0.0006 | 8 |
| faithfulness | 0.9583 | 0.8750-1.0000 | 8 |
| false_abstain_rate | 0.1250 | 0.0000-0.3750 | 8 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 8 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 8 |
| judge_tokens | 368.8750 | 331.5000-423.1250 | 8 |
| tokens | 3943.3750 | 3536.8125-4436.5281 | 8 |

Latency (ms): {"p50": 25413.175800000317, "p95": 71358.1692950003}

### unanswerable

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0013 | 0.0009-0.0015 | 8 |
| faithfulness | 0.3125 | 0.0000-0.7500 | 4 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 8 |
| judge_estimated_cost | 0.0000 | 0.0000-0.0000 | 8 |
| judge_tokens | 267.0000 | 254.7500-282.2500 | 8 |
| tokens | 12122.7500 | 9488.4750-14510.1625 | 8 |

Latency (ms): {"p50": 67723.83294999963, "p95": 136347.1200200005}
