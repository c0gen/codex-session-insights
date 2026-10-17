"""Allowlisted account history and reset-credit data; never retain raw responses."""
from datetime import date
import math


def nonnegative(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def normalize_resets(value):
    summary = value.get("rateLimitResetCredits") if isinstance(value, dict) else None
    if not isinstance(summary, dict):
        return None
    count = summary.get("availableCount")
    count = count if type(count) is int and count >= 0 else None
    credits = None
    if isinstance(summary.get("credits"), list):
        credits, seen = [], set()
        for raw in summary["credits"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or raw["id"] in seen:
                continue
            seen.add(raw["id"])
            expiry = nonnegative(raw.get("expiresAt"))
            if expiry is not None and expiry > 253402300799:
                expiry = None
            expiration = "dated" if expiry is not None else "none" if "expiresAt" in raw and raw["expiresAt"] is None else "unknown"
            credits.append({"id": raw["id"], "status": raw.get("status") if raw.get("status") in
                            {"available", "redeeming", "redeemed"} else "unknown",
                            "title": raw.get("title") if isinstance(raw.get("title"), str) else "Banked reset",
                            "granted_at": nonnegative(raw.get("grantedAt")),
                            "expires_at": expiry if expiration == "dated" else None,
                            "expiration": expiration})
        credits.sort(key=lambda credit: (credit["expires_at"] is None, credit["expires_at"] or 0, credit["id"]))
    return {"available_count": count, "credits": credits,
            "details_complete": credits is not None and count is not None and
            sum(c["status"] == "available" for c in credits) >= count}


SUMMARY_FIELDS = {"lifetime_tokens": "lifetimeTokens", "peak_daily_tokens": "peakDailyTokens",
                  "longest_running_turn_sec": "longestRunningTurnSec",
                  "current_streak_days": "currentStreakDays", "longest_streak_days": "longestStreakDays"}


def normalize_history(value):
    raw = value.get("summary") if isinstance(value, dict) else None
    summary = {key: nonnegative(raw.get(field)) if isinstance(raw, dict) else None
               for key, field in SUMMARY_FIELDS.items()}
    daily = None
    if isinstance(value, dict) and isinstance(value.get("dailyUsageBuckets"), list):
        buckets = {}
        for row in value["dailyUsageBuckets"]:
            if not isinstance(row, dict):
                continue
            day, tokens = row.get("startDate"), nonnegative(row.get("tokens"))
            if not isinstance(day, str) or len(day) != 10 or tokens is None:
                continue
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            buckets[day] = tokens
        daily = [{"day": day, "tokens": tokens} for day, tokens in sorted(buckets.items())]
    return {"summary": summary, "daily": daily}
