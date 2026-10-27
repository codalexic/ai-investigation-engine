from threading import Lock
from time import monotonic

from prometheus_client import CollectorRegistry, Counter, Histogram


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "http_requests_total", "HTTP requests", ["route", "status"], registry=self.registry
        )
        self.http_latency = Histogram(
            "http_request_duration_seconds",
            "HTTP latency",
            ["route", "status"],
            registry=self.registry,
        )
        self.investigations = Histogram(
            "investigation_duration_seconds", "Investigation latency", registry=self.registry
        )
        self.tokens = Counter(
            "llm_tokens_total", "LLM tokens", ["provider", "model", "kind"], registry=self.registry
        )
        self.cost = Counter(
            "llm_cost_total", "Estimated LLM cost", ["provider", "model"], registry=self.registry
        )
        self.calls = Counter(
            "llm_calls_total", "LLM calls", ["provider", "model"], registry=self.registry
        )
        self.cache_hits = Counter(
            "cache_hits_total", "Cache hits", ["cache"], registry=self.registry
        )
        self.retrieval = Histogram(
            "retrieval_stage_duration_seconds",
            "Retrieval latency",
            ["stage"],
            registry=self.registry,
        )
        self.abstentions = Counter("abstentions_total", "Abstentions", registry=self.registry)


class RateLimiter:
    def __init__(self) -> None:
        self.buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self.lock = Lock()

    def check(self, ip: str, group: str, capacity: int) -> int:
        now = monotonic()
        with self.lock:
            for key in [k for k, (_, at) in self.buckets.items() if now - at > 120]:
                del self.buckets[key]
            key = (ip, group)
            tokens, last = self.buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * capacity / 60)
            allowed = tokens >= 1
            self.buckets[key] = (tokens - 1 if allowed else tokens, now)
            return 0 if allowed else max(1, int((1 - tokens) * 60 / capacity) + 1)
