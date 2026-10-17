"""Verified request-date Claude token prices, independent of subscription billing."""
from datetime import datetime, timezone

SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
REVIEWED = "2026-10-16"
# USD per million: uncached input, output, cache read, 5m write, 1h write.
RATES = {
    "claude-sonnet-4-20250514": (3, 15, .3, 3.75, 6),
    "claude-sonnet-4-5-20250929": (3, 15, .3, 3.75, 6),
    "claude-sonnet-4-6": (3, 15, .3, 3.75, 6),
    "claude-opus-4-1-20250805": (15, 75, 1.5, 18.75, 30),
    "claude-opus-4-5-20251101": (5, 25, .5, 6.25, 10),
    "claude-opus-4-6": (5, 25, .5, 6.25, 10),
    "claude-haiku-4-5-20251001": (1, 5, .1, 1.25, 2),
    "claude-opus-5-5": (4, 20, .2, 5, 8),
    "claude-sonnet-5-5": (2, 10, .1, 2.5, 4),
}
# Existing models retain their original verified window. A model's build-date
# suffix is not evidence for when its public prices took effect.
PRICE_WINDOWS = {model: [{"start": "2026-10-11", "end": None, "rates": rates,
                          "source": SOURCE}] for model, rates in RATES.items()}
for _model, _start, _source in (
    ("claude-opus-5-5", "2026-09-22", "https://www.anthropic.com/claude-opus-5-5"),
    ("claude-sonnet-5-5", "2026-09-28", "https://www.anthropic.com/claude-sonnet-5-5"),
):
    PRICE_WINDOWS[_model] = [{"start": _start, "end": None, "rates": RATES[_model], "source": _source}]

METADATA_VALUES = {
    "service_tier": frozenset({"standard", "batch", "priority", "unknown"}),
    "speed": frozenset({"standard", "fast", "unknown"}),
    "inference_geo": frozenset({"global", "us", "not_available", "unknown"}),
}
CACHE_KEYS = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")


def pricing_metadata(usage):
    """Keep only bounded enums; unexpected values must not become default prices."""
    result = {}
    for key, allowed in METADATA_VALUES.items():
        value = usage.get(key)
        if value is not None:
            result[key] = value if isinstance(value, str) and value in allowed else "unknown"
    return result


def catalog():
    return {"source": SOURCE, "reviewed_at": REVIEWED, "rates": RATES,
            "price_windows": PRICE_WINDOWS,
            "rate_order": ["input", "output", "cache_read", "cache_write_5m", "cache_write_1h"],
            "assumptions": "Standard speed/tier and global inference where unlogged or geography unavailable; token charges only."}


def estimate(item):
    model, usage, at = item.get("model"), item.get("usage"), item.get("timestamp")
    if not isinstance(usage, dict) or not isinstance(at, datetime) or at.utcoffset() is None:
        return None
    day = at.astimezone(timezone.utc).date().isoformat()
    record = next((r for r in PRICE_WINDOWS.get(model, ())
                   if r["start"] <= day and (r["end"] is None or day < r["end"])), None)
    if record is None:
        return None
    keys = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "total_tokens")
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
        return None
    inputs, reads, writes, outputs, total = (usage[k] for k in keys)
    if inputs < reads + writes or total != inputs + outputs:
        return None
    creation = item.get("cache_creation")
    if creation is not None:
        if (not isinstance(creation, dict) or set(creation) != set(CACHE_KEYS)
                or any(type(v) is not int or v < 0 for v in creation.values())
                or sum(creation.values()) != writes):
            return None
    elif writes:
        return None

    tier, speed, geo = (item.get(k) for k in ("service_tier", "speed", "inference_geo"))
    if tier not in (None, "standard", "batch") or speed not in (None, "standard", "fast"):
        return None
    if geo not in (None, "global", "not_available", "us"):
        return None
    multiplier = .5 if tier == "batch" else 1
    if speed == "fast":
        if model != "claude-opus-5-5" or tier == "batch":
            return None
        multiplier *= 2
    if geo == "us":
        if model not in {"claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-5-5", "claude-sonnet-5-5"}:
            return None
        multiplier *= 1.1
    base, output, cache, short, long = (rate * multiplier for rate in record["rates"])
    creation = creation or dict.fromkeys(CACHE_KEYS, 0)
    cost = ((inputs - reads - writes) * base + reads * cache + outputs * output
            + creation[CACHE_KEYS[0]] * short + creation[CACHE_KEYS[1]] * long) / 1e6
    return {"usd": cost, "cache_discount_usd": reads * (base - cache) / 1e6}
