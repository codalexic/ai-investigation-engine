# Performance benchmark

| Mode | Concurrency | p50 ms | p95 ms | p99 ms | QPS |
| --- | --- | --- | --- | --- | --- |
| dense | 1 | 22.605 | 39.120 | 45.883 | 40.004 |
| dense | 4 | 71.028 | 107.807 | 120.713 | 54.390 |
| dense | 8 | 157.150 | 196.942 | 216.476 | 50.594 |
| sparse | 1 | 19.216 | 34.177 | 35.610 | 47.342 |
| sparse | 4 | 65.750 | 95.789 | 110.465 | 58.086 |
| sparse | 8 | 125.224 | 157.905 | 168.750 | 63.695 |
| hybrid | 1 | 36.334 | 56.023 | 66.523 | 27.573 |
| hybrid | 4 | 123.500 | 164.392 | 173.345 | 31.666 |
| hybrid | 8 | 244.646 | 296.707 | 314.933 | 32.164 |
| hybrid_rerank | 1 | 853.273 | 1520.048 | 1581.822 | 1.074 |
| hybrid_rerank | 4 | 2459.901 | 4525.482 | 5646.053 | 1.438 |
| hybrid_rerank | 8 | 4924.739 | 17892.975 | 28136.338 | 1.145 |

#### Retrieval stages

| Mode | Concurrency | Stage | Mean ms | p95 ms |
| --- | --- | --- | --- | --- |
| dense | 1 | dense | 17.328 | 30.883 |
| dense | 1 | sparse | 0.001 | 0.001 |
| dense | 1 | fusion | 7.519 | 9.961 |
| dense | 1 | rerank | 0.001 | 0.001 |
| dense | 1 | mmr | 0.019 | 0.027 |
| dense | 4 | dense | 67.111 | 102.502 |
| dense | 4 | sparse | 0.001 | 0.001 |
| dense | 4 | fusion | 5.986 | 8.123 |
| dense | 4 | rerank | 0.001 | 0.001 |
| dense | 4 | mmr | 0.019 | 0.022 |
| dense | 8 | dense | 149.407 | 188.662 |
| dense | 8 | sparse | 0.001 | 0.001 |
| dense | 8 | fusion | 6.482 | 10.498 |
| dense | 8 | rerank | 0.001 | 0.002 |
| dense | 8 | mmr | 0.016 | 0.024 |
| sparse | 1 | dense | 0.000 | 0.001 |
| sparse | 1 | sparse | 15.322 | 28.422 |
| sparse | 1 | fusion | 5.671 | 7.843 |
| sparse | 1 | rerank | 0.000 | 0.001 |
| sparse | 1 | mmr | 0.015 | 0.022 |
| sparse | 4 | dense | 0.000 | 0.001 |
| sparse | 4 | sparse | 62.388 | 89.628 |
| sparse | 4 | fusion | 5.888 | 8.355 |
| sparse | 4 | rerank | 0.000 | 0.001 |
| sparse | 4 | mmr | 0.016 | 0.023 |
| sparse | 8 | dense | 0.000 | 0.001 |
| sparse | 8 | sparse | 117.581 | 151.565 |
| sparse | 8 | fusion | 5.842 | 7.916 |
| sparse | 8 | rerank | 0.001 | 0.001 |
| sparse | 8 | mmr | 0.016 | 0.022 |
| hybrid | 1 | dense | 14.816 | 28.137 |
| hybrid | 1 | sparse | 10.942 | 29.534 |
| hybrid | 1 | fusion | 10.318 | 15.280 |
| hybrid | 1 | rerank | 0.001 | 0.001 |
| hybrid | 1 | mmr | 0.029 | 0.048 |
| hybrid | 4 | dense | 56.386 | 87.201 |
| hybrid | 4 | sparse | 58.820 | 89.802 |
| hybrid | 4 | fusion | 10.398 | 15.551 |
| hybrid | 4 | rerank | 0.001 | 0.001 |
| hybrid | 4 | mmr | 0.031 | 0.046 |
| hybrid | 8 | dense | 115.412 | 166.907 |
| hybrid | 8 | sparse | 120.214 | 173.892 |
| hybrid | 8 | fusion | 10.442 | 14.937 |
| hybrid | 8 | rerank | 0.001 | 0.001 |
| hybrid | 8 | mmr | 0.039 | 0.049 |
| hybrid_rerank | 1 | dense | 17.516 | 31.846 |
| hybrid_rerank | 1 | sparse | 16.195 | 31.558 |
| hybrid_rerank | 1 | fusion | 12.998 | 16.818 |
| hybrid_rerank | 1 | rerank | 884.363 | 1475.879 |
| hybrid_rerank | 1 | mmr | 0.025 | 0.029 |
| hybrid_rerank | 4 | dense | 26.018 | 49.166 |
| hybrid_rerank | 4 | sparse | 22.875 | 43.286 |
| hybrid_rerank | 4 | fusion | 18.800 | 24.995 |
| hybrid_rerank | 4 | rerank | 2701.763 | 4414.007 |
| hybrid_rerank | 4 | mmr | 0.064 | 0.129 |
| hybrid_rerank | 8 | dense | 111.278 | 585.136 |
| hybrid_rerank | 8 | sparse | 115.630 | 364.930 |
| hybrid_rerank | 8 | fusion | 26.139 | 37.713 |
| hybrid_rerank | 8 | rerank | 6690.903 | 17253.187 |
| hybrid_rerank | 8 | mmr | 0.130 | 0.481 |

## Embedding cache

```json
{
  "supported": true,
  "count": 50,
  "first_seconds": 0.24844969999685418,
  "second_seconds": 4.9100002797786146e-05,
  "speedup": 5060.075068021309,
  "hits": [
    0,
    50
  ],
  "cache_size": 1024
}
```

## Machine and index

```json
{
  "kind": "benchmark",
  "machine": {
    "cpu_count": 12,
    "platform": "Windows-10-10.0.26300-SP0",
    "python_version": "3.11.15"
  },
  "collection": "documents",
  "point_count": 67224,
  "models": {
    "embedding": "BAAI/bge-small-en-v1.5",
    "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2"
  },
  "seed": 3,
  "question_ids": [
    "5ae331fb55429928c4239670",
    "5ab875bd55429916710eb062",
    "5ae5ffbb5542996de7b71ad4",
    "5a80735b554299485f5985f3",
    "5ab484415542990594ba9c44",
    "5a76f5b155429972597f1400",
    "5a7380e855429905862fe041",
    "5ae765185542995703ce8c0f",
    "5abab18d55429901930fa89e",
    "5a72b8de5542994cef4bc3df",
    "5abbd58d554299660624172f",
    "5abefbc15542990832d3a117",
    "5abb342055429966062416e8",
    "5abd8bf95542996e802b47ba",
    "5ac519a95542994611c8b38b",
    "5ac4a5de5542995c82c4ad6e",
    "5addf05a5542997dc79070cd",
    "5a72d3525542991f9a20c5ab",
    "5abcf51c554299700f9d7949",
    "5a793d335542994bb9456fca",
    "5ab7bfe955429928e1fe38c2",
    "5a78ce5d55429974737f78ac",
    "5ac1846d55429964131be20b",
    "5a8a7d2b55429930ff3c0dfc",
    "5ae713af554299572ea546bb",
    "5adf6b405542992d7e9f9341",
    "5a7c78c955429935c91b51d2",
    "5ae50eff55429908b6326500",
    "5a8078e95542992bc0c4a72c",
    "5ab29bdc554299545a2cf9d1",
    "5a82accd55429966c78a6a78",
    "5ac4d314554299076e296e02",
    "5ae7ea695542994a481bbe17",
    "5adfd0d655429942ec259b4e",
    "5ae27f22554299495565da8d",
    "5a88696b554299206df2b25b",
    "5a7542425542996c70cfaecc",
    "5a7ae2f2554299042af8f6aa",
    "5abe87cb5542993f32c2a156",
    "5ae1892f5542997b2ef7d1f3",
    "5ab392ec55429969a97a817d",
    "5a8db788554299653c1aa145",
    "5a778b345542992a6e59decf",
    "5ab3f8c25542992ade7c6f02",
    "5ac2f1d1554299218029dba4",
    "5ab259b25542993be8fa98de",
    "5a8303c255429954d2e2ec01",
    "5a865bbf5542991e77181615",
    "5ab1e984554299340b525428",
    "5ab1e75f554299340b525422",
    "5ae6dd745542996d980e7ca0",
    "5a834ed95542990548d0b1ca",
    "5a79c9395542994bb94570a2",
    "5ae4cb2f55429960a22e01e8",
    "5a8315c055429966c78a6b2d",
    "5a78b209554299148911f93e",
    "5a81418455429903bc27b95f",
    "5a7574e25542996c70cfaf01",
    "5ade25ed5542997c77aded70",
    "5a81dacc55429926c1cdada0",
    "5ade0e115542995b365fabf3",
    "5ae544035542992663a4f1af",
    "5ae1384355429920d5234329",
    "5a75a76b5542992db9473697",
    "5ae1fc24554299492dc91bbd",
    "5aba9e545542994dbf019986",
    "5a88d7fc5542993b751ca879",
    "5ae0e183554299422ee9953f",
    "5a8ed10b5542995085b374a0",
    "5ac536485542996feb3fea2e",
    "5ae2d59755429928c42394ec",
    "5ac3d7f8554299076e296cb0",
    "5a7438ec55429979e28828b8",
    "5ae1389655429901ffe4ae05",
    "5a7f9cb55542995d8a8ddec1",
    "5abda4dd55429965af743d95",
    "5a88f7bf5542997e5c09a6dd",
    "5addfc425542997dc7907101",
    "5adc99cf554299438c868e0d",
    "5a7b192855429927d897bf39",
    "5a8b45765542995d1e6f1333",
    "5abce43855429959677d6b18",
    "5a71674f5542994082a3e819",
    "5ab2f4c95542991669774155",
    "5abafb6d5542992ccd8e7e92",
    "5a8b6a5155429949d91db5a3",
    "5adfe37c554299025d62a377",
    "5ac4f8705542995c82c4ad8d",
    "5a85ecf25542991dd0999ec6",
    "5a8210f355429926c1cdae24",
    "5a8a09565542992d82986e66",
    "5ae3f1bb5542995ad6573cbe",
    "5a836a765542996488c2e446",
    "5ae80d25554299540e5a5709",
    "5add3fe05542992c1e3a2580",
    "5ae610e55542995703ce8ae1",
    "5a7633ff5542994ccc918712",
    "5abea9a35542990832d3a07e",
    "5a721bbc55429971e9dc9279",
    "5a820f2c55429926c1cdae17",
    "5a791a97554299148911f9f2",
    "5ae2994d554299492dc91c31",
    "5add84a15542997545bbbd5e",
    "5ae5e1985542996de7b71a54",
    "5adfb60655429942ec259b08",
    "5ae33a6e5542992f92d8224d",
    "5ab5d4eb5542992aa134a3aa",
    "5ac298805542990b17b15429",
    "5a7f3f7c55429934daa2fd45",
    "5a8dce155542994ba4e3dd24",
    "5ac04a265542997d642959f1",
    "5ab2b7405542991669774069",
    "5a80d6be55429938b6142206",
    "5ab5f9a0554299488d4d9a6d",
    "5ab4428c5542990594ba9bda",
    "5a7602d8554299109176e5fb",
    "5a733caa5542992359bc32a3",
    "5a7a3d435542996a35c17154",
    "5a8b04df55429950cd6afc49",
    "5ab29caa554299545a2cf9d3",
    "5a7c35025542996dd594b8d7",
    "5adca0845542994d58a2f684",
    "5a85e2775542994775f60680",
    "5a77c74155429967ab105291",
    "5a90b1a15542990a984936ab",
    "5a8739a05542994775f607ab",
    "5ae76d185542997ec2727641",
    "5ab51dbd5542996a3a96a023",
    "5a80c79155429938b61421da",
    "5ab6cebd55429954757d3378",
    "5adccd795542990d50227d2c",
    "5ac2ada255429967731025f9",
    "5a739323554299623ed4abff",
    "5ae4c39f5542995dadf243fb",
    "5a85e24a5542994775f6067f",
    "5a790e69554299148911f9d7",
    "5a8e3f2d5542995a26add48f",
    "5adf75e35542993344016c98",
    "5a7c68575542996dd594b91c",
    "5ade26db5542997c77aded77",
    "5a8f541e5542992414482a53",
    "5ae5ff635542996de7b71ace",
    "5a7ef6b35542994959419a94",
    "5ae0fe8855429945ae959495",
    "5a71419f5542994082a3e70d",
    "5ab29842554299194fa93420",
    "5adef1b35542993a75d263af",
    "5a88a1bb5542997e5c09a64c",
    "5ab2b666554299194fa934ca",
    "5a7b443c5542992d025e67ce",
    "5a7624b85542992db947372c",
    "5a831af855429954d2e2ec1e",
    "5a848a685542997b5ce3feae",
    "5a8b987f5542997f31a41d7a",
    "5a80e5f5554299260e20a1ae",
    "5ade61fd554299728e26c704",
    "5ac195455542991316484b40",
    "5a85ebe75542996432c5712a",
    "5ab2f85b55429929539468dc",
    "5a8d51355542994ba4e3dc6b",
    "5a80d2c6554299260e20a17c",
    "5ac279345542990b17b153b0",
    "5aba6f3e55429955dce3ee21",
    "5ab3cecd5542992ade7c6eae",
    "5ab58ee6554299488d4d99d6",
    "5a8f68795542992414482ab5",
    "5a8f18d555429918e830d189",
    "5a8f9cdb554299458435d69c",
    "5ac46a8b5542991943173980",
    "5a87c7dc5542996e4f30891b",
    "5ab2a32f554299706120967b",
    "5ac5275755429924173fb617",
    "5ab862b35542990e739ec8db",
    "5adc7f4a5542994650320d28",
    "5ae1f3df554299234fd04364",
    "5adf27775542993344016c00",
    "5ac056385542997d64295a08",
    "5adda7585542997dc790700c",
    "5abccda855429965836004a4",
    "5a75da6d5542992db94736fa",
    "5a8f1adc554299458435d577",
    "5a762cf0554299109176e6a4",
    "5a7bb16f554299294a54aa9f",
    "5add016e5542992c1e3a250b",
    "5adfc06d55429906c02daa2a",
    "5add2dae5542992c1e3a2558",
    "5adfd0d455429942ec259b4d",
    "5ac02c4a5542992a796decbd",
    "5a7a5cc955429941d65f25d6",
    "5ab5eed65542997d4ad1f25c",
    "5a7dc7895542995ed0d16673",
    "5a8b7dab5542997f31a41d4c",
    "5adf53dc5542995534e8c791",
    "5a8f0986554299458435d535",
    "5a8126265542995ce29dcbc9",
    "5ae5fb55554299546bf82ff6",
    "5a73090455429901807daf6e",
    "5ae09b7055429906c02daae4",
    "5ae7f56e5542993210983fd1",
    "5a85f4425542994775f606c4",
    "postmortem-pm-cloudflare-9f3dcc31",
    "multi-causal-dependencies",
    "simple-INC-2040",
    "conflict-duration-1",
    "conflict-cause-0",
    "injection-0-1",
    "gap-3",
    "hp-5a7f669a5542994857a76729",
    "multi-risk-upstream-pool",
    "simple-CHG-1051",
    "hp-5a8230af554299676cceb227",
    "gap-5",
    "comparison-syn-0",
    "hp-5a7a33205542996a35c1712f",
    "simple-INC-2044",
    "gap-6",
    "hp-5a776bc855429966f1a36d3a",
    "hp-5a762cf0554299109176e6a4",
    "hp-5abeb0da5542997ec76fd34b",
    "simple-CHG-1055",
    "injection-1-1",
    "multi-change-effect",
    "hp-5ab84de95542990e739ec8b4",
    "hp-5ab5820e554299488d4d99c3",
    "gap-8",
    "hp-5ae3d67f5542992f92d8238f",
    "gap-4",
    "gap-2",
    "postmortem-pm-allegro-8e9398f0",
    "hp-5adc7b855542994650320d1e",
    "injection-1-0",
    "hp-5a738225554299623ed4abc3",
    "postmortem-pm-amazon-900cd6f9",
    "hp-5a75e3845542994ccc91864e",
    "conflict-pool-0",
    "conflict-pool-1",
    "postmortem-pm-circleci-032086ae",
    "hp-5a7528e955429929fddd850e",
    "multi-reporting-upstream-change",
    "simple-INC-2031",
    "postmortem-pm-circleci-2effb479",
    "multi-causal-change-date",
    "simple-CHG-1042",
    "conflict-duration-0",
    "conflict-impact-1",
    "gap-7",
    "hp-5adf68ac5542993344016c79",
    "simple-CHG-1047",
    "hp-5a90b6985542990a984936c2",
    "gap-1",
    "multi-current-pool",
    "hp-5ab680d15542995eadef0011",
    "simple-INC-2020",
    "multi-causal-service",
    "multi-change-author",
    "gap-0",
    "injection-0-0",
    "postmortem-pm-cloudflare-d8fe2fc0",
    "gap-9",
    "multi-causal-owner",
    "conflict-impact-0",
    "multi-preliminary-effect",
    "conflict-cause-1",
    "hp-5a77ba6c55429967ab10524c",
    "comparison-syn-1",
    "hp-5ab7fa4f5542993667794080"
  ],
  "warmup_queries": 10
}
```

Latency measures each search; QPS uses batch wall time including scheduling. Ten warm-up searches per mode/concurrency are excluded. The process-local query cache remains enabled across retrieval runs. Cache speed-up times embeddings only, with model loading excluded and the cache cleared before the first pass.
