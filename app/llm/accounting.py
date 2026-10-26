from app.llm.types import LLMResponse

PRICES = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "gemini-2.0-flash": (0.10, 0.40),
}


class UsageTracker:
    def __init__(self) -> None:
        self.prompt_tokens = self.completion_tokens = self.calls = self.cache_hits = 0
        self.latency_ms = self.estimated_cost = 0.0

    def record(self, response: LLMResponse) -> None:
        self.calls += 1
        self.cache_hits += int(response.cached)
        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens
        self.latency_ms += response.latency_ms
        incoming, outgoing = PRICES.get(response.model, (0, 0))
        if not response.cached:
            self.estimated_cost += (
                incoming * response.usage.prompt_tokens
                + outgoing * response.usage.completion_tokens
            ) / 1_000_000

    def snapshot(self) -> dict[str, int | float]:
        return dict(vars(self))
