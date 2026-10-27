from app.llm.types import LLMResponse

PRICES = {
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-3.8-flash": (0.30, 2.50),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "gemini-2.5-flash": (0.30, 2.50),
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
