"""Allowance normalization and compatibility cache for the current Codex account."""
import math
import time

from .codex_account import AppServerProvider
from .account_data import normalize_resets
from .account_polling import PollingCache
from .burn_rates import AllowanceBurnRates


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def normalize_window(value, key):
    if not isinstance(value, dict):
        return None
    used = number(value.get("usedPercent"))
    duration = number(value.get("windowDurationMins"))
    reset = number(value.get("resetsAt"))
    return {"id": key, "remaining_percent": max(0, min(100, 100 - used)) if used is not None else None,
            "window_duration_mins": duration if duration is not None and duration > 0 else None,
            "resets_at": reset if reset is not None and reset > 0 else None}


def normalize_limits(value):
    if not isinstance(value, dict):
        return []
    multiple = value.get("rateLimitsByLimitId")
    if isinstance(multiple, dict):
        buckets = multiple
    else:
        single = value.get("rateLimits")
        buckets = {single.get("limitId") or "codex": single} if isinstance(single, dict) else {}
    result = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        windows = [window for field in ("primary", "secondary")
                   if (window := normalize_window(bucket.get(field), field)) is not None]
        result.append({"id": str(key), "name": bucket.get("limitName") or ("Codex" if key == "codex" else str(key)),
                       "windows": windows})
    return sorted(result, key=lambda b: (b["id"] != "codex", b["id"]))


class UsageLimits(PollingCache):
    def __init__(self, provider=None, enabled=True, allowed=True, clock=time.time,
                 interval=60, max_backoff=300, listener=None):
        provider = provider or AppServerProvider()
        super().__init__(provider, provider.fetch,
            lambda value: {"buckets": normalize_limits(value), "reset_credits": normalize_resets(value)},
            lambda value: any(w["remaining_percent"] is not None for b in value["buckets"] for w in b["windows"])
                          or (value["reset_credits"] is not None and value["reset_credits"]["available_count"] is not None),
            {"buckets": [], "reset_credits": None}, enabled=enabled, allowed=allowed, clock=clock,
            interval=interval, max_backoff=max_backoff, listener=listener, rates=AllowanceBurnRates(interval), missing_code="no_windows",
            missing_message="This account returned no allowance windows. Refresh to retry.")
