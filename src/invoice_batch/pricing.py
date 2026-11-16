"""Token prices and cost estimates (standard vs. batch)."""

# Standard (non-batch) prices in USD per million tokens, from the Pricing page.
# cache_write is the 1-hour TTL rate (2x input); cache_read is the cache-hit rate.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.20, "cache_read": 0.01},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 4.00, "cache_read": 0.10},
}
BATCH_DISCOUNT = 0.5  # Batch API: 50% off every token type, stacks with caching


def cost_usd(usage: dict, model: str, batch: bool = True) -> float:
    """Dollar cost of one response from its usage dict, at batch price unless batch=False."""
    p = PRICES.get(model)
    if p is None:
        raise ValueError(f"No price for model {model!r}; add it to PRICES in pricing.py")
    dollars = (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + (usage.get("cache_creation_input_tokens") or 0) * p["cache_write"]
        + (usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
    ) / 1_000_000
    return dollars * (BATCH_DISCOUNT if batch else 1.0)
