| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.6296 | 0.4995-0.7407 | 54 |
| citation_precision | 0.6229 | 0.5103-0.7311 | 46 |
| citation_recall | 0.7790 | 0.6812-0.8696 | 46 |
| contradiction_detection_rate | 0.5000 | 0.1667-0.8333 | 6 |
| estimated_cost | 0.0002 | 0.0002-0.0003 | 54 |
| exact_match | 0.0000 | 0.0000-0.0000 | 16 |
| faithfulness | 0.7817 | 0.6945-0.8629 | 46 |
| false_abstain_rate | 0.4348 | 0.3043-0.5870 | 46 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 0.6569 | 0.5490-0.7647 | 51 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 51 |
| judge_tokens | 376.3333 | 354.1564-400.8451 | 51 |
| token_f1 | 0.0635 | 0.0327-0.0976 | 16 |
| tokens | 1890.0556 | 1695.8579-2100.8162 | 54 |

Latency (ms): {"p50": 9829.884349999702, "p95": 35726.7240899976}

### comparison/multi_doc

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.7500 | 0.5000-1.0000 | 8 |
| citation_precision | 0.9062 | 0.7188-1.0000 | 8 |
| citation_recall | 0.9375 | 0.8125-1.0000 | 8 |
| estimated_cost | 0.0002 | 0.0002-0.0003 | 8 |
| exact_match | 0.0000 | 0.0000-0.0000 | 7 |
| faithfulness | 0.8266 | 0.7106-0.9308 | 8 |
| false_abstain_rate | 0.2500 | 0.0000-0.5000 | 8 |
| judge_correctness | 0.8750 | 0.7500-1.0000 | 8 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 8 |
| judge_tokens | 349.1250 | 319.6094-381.3781 | 8 |
| token_f1 | 0.0881 | 0.0407-0.1400 | 7 |
| tokens | 1925.1250 | 1770.4906-2074.7500 | 8 |

Latency (ms): {"p50": 8700.256000000081, "p95": 60960.189675000904}

### contradiction

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.6667 | 0.3333-1.0000 | 6 |
| citation_precision | 0.6111 | 0.3333-0.8611 | 6 |
| citation_recall | 0.7500 | 0.4167-1.0000 | 6 |
| contradiction_detection_rate | 0.5000 | 0.1667-0.8333 | 6 |
| estimated_cost | 0.0002 | 0.0001-0.0003 | 6 |
| faithfulness | 0.8933 | 0.8200-0.9667 | 5 |
| false_abstain_rate | 0.3333 | 0.0000-0.6667 | 6 |
| judge_correctness | 0.6000 | 0.3000-0.9000 | 5 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 5 |
| judge_tokens | 436.6000 | 391.9100-488.6000 | 5 |
| tokens | 1516.1667 | 885.1500-1879.1833 | 6 |

Latency (ms): {"p50": 8486.060350000116, "p95": 23374.318899999707}

### injection

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.6667 | 0.0000-1.0000 | 3 |
| citation_precision | 0.7778 | 0.3333-1.0000 | 3 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 3 |
| estimated_cost | 0.0003 | 0.0002-0.0003 | 3 |
| faithfulness | 0.9524 | 0.8571-1.0000 | 3 |
| false_abstain_rate | 0.3333 | 0.0000-1.0000 | 3 |
| injection_resistance | 1.0000 | 1.0000-1.0000 | 3 |
| judge_correctness | 0.3333 | 0.0000-1.0000 | 3 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 3 |
| judge_tokens | 417.3333 | 343.0000-519.0000 | 3 |
| tokens | 2021.0000 | 1828.0000-2162.0000 | 3 |

Latency (ms): {"p50": 11720.995800002129, "p95": 12779.299229999742}

### multi_hop

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.2500 | 0.0625-0.4391 | 16 |
| citation_precision | 0.6094 | 0.4115-0.7917 | 16 |
| citation_recall | 0.5521 | 0.3958-0.7188 | 16 |
| estimated_cost | 0.0002 | 0.0002-0.0003 | 16 |
| exact_match | 0.0000 | 0.0000-0.0000 | 9 |
| faithfulness | 0.7196 | 0.5439-0.8850 | 13 |
| false_abstain_rate | 0.7500 | 0.5609-0.9375 | 16 |
| judge_correctness | 0.3333 | 0.1333-0.5667 | 15 |
| judge_estimated_cost | 0.0001 | 0.0000-0.0001 | 15 |
| judge_tokens | 361.6667 | 332.9950-389.9583 | 15 |
| token_f1 | 0.0444 | 0.0122-0.0822 | 9 |
| tokens | 1798.3125 | 1525.3594-2007.5750 | 16 |

Latency (ms): {"p50": 8605.968149999171, "p95": 18222.653349999746}

### postmortem

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.8000 | 0.4000-1.0000 | 5 |
| citation_precision | 0.1644 | 0.0422-0.3422 | 5 |
| citation_recall | 0.8000 | 0.4000-1.0000 | 5 |
| estimated_cost | 0.0003 | 0.0000-0.0005 | 5 |
| faithfulness | 0.8625 | 0.8000-0.9500 | 4 |
| false_abstain_rate | 0.2000 | 0.0000-0.6000 | 5 |
| judge_correctness | 0.6250 | 0.5000-0.8750 | 4 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 4 |
| judge_tokens | 561.5000 | 459.5000-630.5000 | 4 |
| tokens | 2629.4000 | 1081.8000-4177.0000 | 5 |

Latency (ms): {"p50": 15098.786999998993, "p95": 42912.27971999906}

### simple

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 0.7500 | 0.3750-1.0000 | 8 |
| citation_precision | 0.6042 | 0.3854-0.8128 | 8 |
| citation_recall | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0003 | 0.0002-0.0003 | 8 |
| faithfulness | 0.9018 | 0.7679-1.0000 | 8 |
| false_abstain_rate | 0.2500 | 0.0000-0.6250 | 8 |
| judge_correctness | 0.8750 | 0.6875-1.0000 | 8 |
| judge_estimated_cost | 0.0001 | 0.0001-0.0001 | 8 |
| judge_tokens | 367.7500 | 350.5000-385.0000 | 8 |
| tokens | 1839.1250 | 1722.7406-1947.5250 | 8 |

Latency (ms): {"p50": 8075.269149998348, "p95": 44101.408554999914}

### unanswerable

| Metric | Mean | 95% CI | N |
|---|---:|---|---:|
| abstention_accuracy | 1.0000 | 1.0000-1.0000 | 8 |
| estimated_cost | 0.0002 | 0.0002-0.0002 | 8 |
| faithfulness | 0.4000 | 0.0000-0.8000 | 5 |
| false_answer_rate | 0.0000 | 0.0000-0.0000 | 8 |
| judge_correctness | 1.0000 | 1.0000-1.0000 | 8 |
| judge_estimated_cost | 0.0000 | 0.0000-0.0000 | 8 |
| judge_tokens | 294.0000 | 270.2500-321.0063 | 8 |
| tokens | 1858.6250 | 1692.4500-2045.5187 | 8 |

Latency (ms): {"p50": 9932.550600000468, "p95": 17938.812994999716}
