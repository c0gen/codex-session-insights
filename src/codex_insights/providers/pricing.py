"""Dated API-equivalent prices. Exact verified IDs only; no model-name guessing."""
from datetime import datetime, timezone
from .claude_pricing import RATES as CLAUDE, catalog as claude_catalog, estimate as estimate_claude

# USD per million: uncached input, output, cache read, 5m write, 1h write.
REVIEWED = "2026-10-11"
# Text rates only. Cache storage/tool charges cannot be inferred from transcripts.
GEMINI = {"gemini-3.6-flash": (.75, 3.75, .075), "gemini-2.5-flash": (.3, 2.5, .03),
          "gemini-2.5-flash-lite": (.1, .4, .01)}


def catalog():
    from .legacy.pricing import RATES
    return {"reviewed_at": claude_catalog()["reviewed_at"], "effective_from": "2026-09-22", "models": {
        "claude_code": claude_catalog(),
        "antigravity": {"source": "https://ai.google.dev/gemini-api/docs/pricing", "effective_from": REVIEWED, "rates": GEMINI}},
        'legacy_base_rates': RATES,
        "units": "USD per million tokens", "estimate": "API-equivalent estimate"}


def estimate(item):
    model, usage, at = item.get("model"), item["usage"], item["timestamp"]
    if model in CLAUDE:
        return estimate_claude(item)
    if any(usage.get(k) is None for k in ('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','total_tokens')):
        return None
    if at < datetime(2026, 10, 11, tzinfo=timezone.utc):
        # Reviewed catalog is not evidence for historical pricing.
        return None
    inputs, reads, writes = usage["input_tokens"], usage["cached_input_tokens"], usage.get("cache_write_input_tokens", 0)
    if model in GEMINI and not writes:
        if model == "gemini-3.6-flash" and at >= datetime(2027, 1, 1, tzinfo=timezone.utc):
            return None
        base, output, cache = GEMINI[model]
        cost = ((inputs - reads) * base + reads * cache + usage["output_tokens"] * output) / 1e6
    else:
        return None
    return {"usd": cost, "cache_discount_usd": reads * (base - cache) / 1e6}
