"""Allowlisted status-line snapshots, independent of usage records and exports."""
import math
from datetime import datetime, timezone

from ..codec import timestamp
from .bridge_io import MAX_INPUT
from . import LABELS


def number(value, low=0, high=float("inf")):
    return value if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None


def reset(value):
    if number(value) is not None:
        return value
    parsed = timestamp(value)
    return parsed.timestamp() if parsed else None


def normalize(provider, payload, now):
    buckets = []
    if provider == "claude_code":
        values = payload.get("rate_limits")
        values = values if isinstance(values, dict) else {}
        for key in ("five_hour", "seven_day", "spend_limit"):
            value = values.get(key)
            if not isinstance(value, dict):
                continue
            used = number(value.get("used_percentage"), high=100)
            used_usd, limit_usd = number(value.get("used_usd")), number(value.get("limit_usd"))
            if used is None and used_usd is None:
                continue
            buckets.append({"id": key, "unit": "usd" if used_usd is not None else "percent",
                "remaining_percent": 100 - used if used is not None else None,
                "used": used_usd, "limit": limit_usd, "resets_at": reset(value.get("resets_at"))})
    elif provider == "antigravity":
        values = payload.get("quota")
        values = values if isinstance(values, dict) else {}
        for key, value in list(values.items())[:32]:
            if not isinstance(key, str) or len(key) > 100 or not isinstance(value, dict):
                continue
            remaining = number(value.get("remaining_fraction"), high=1)
            if remaining is None:
                continue
            buckets.append({"id": key, "unit": "percent", "remaining_percent": remaining * 100,
                "used": None, "limit": None, "resets_at": reset(value.get("reset_time"))})
    return {"schema": 1, "provider": provider, "profile": "local", "identity_verified": False,
            "source": "Claude Code status line" if provider == "claude_code" else "Antigravity CLI status line",
            "received_at": now, "buckets": buckets}


CHECK_FIELDS = ("enabled", "allowed", "status", "refreshing", "error", "error_code", "last_success_at", "next_refresh_at")


def merge_check(snapshot, check, now):
    """Prefer the newer of the status-line file and the in-memory /usage check."""
    snapshot["check"] = {key: check.get(key) for key in CHECK_FIELDS}
    received = check.get("last_success_at")
    buckets = check.get("buckets")
    if number(received) is None or not isinstance(buckets, list) or not buckets:
        return
    if snapshot["received_at"] is not None and snapshot["received_at"] > received:
        return
    stale = check.get("stale") is True
    snapshot.update(received_at=received, source="Claude Code /usage" if snapshot['provider'] == 'claude_code' else 'Antigravity CLI /usage', buckets=[
        {**bucket, "stale": stale or (bucket.get("resets_at") is not None and now >= bucket["resets_at"])}
        for bucket in buckets if isinstance(bucket, dict)])
    snapshot["status"] = "stale" if any(b["stale"] for b in snapshot["buckets"]) else "available"


def read(directory, now=None, live=None):
    import json
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    live = live or {}
    profiles = []
    for provider in ("claude_code", "antigravity"):
        path = directory / "bridge" / (provider + "-allowance.json")
        snapshot = {"provider": provider, "profile": "local", "label": LABELS[provider] + " · local profile",
                    "identity_verified": False, "received_at": None, "buckets": [], "status": "unavailable"}
        try:
            if path.stat().st_size > MAX_INPUT:
                raise ValueError()
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema") != 1 or value.get("provider") != provider:
                raise ValueError()
            if number(value.get("received_at")) is None or not isinstance(value.get("buckets"), list):
                raise ValueError()
            if len(value["buckets"]) > 32 or any(not isinstance(b, dict) or not isinstance(b.get("id"), str) for b in value["buckets"]):
                raise ValueError()
            for b in value["buckets"]:
                if b.get("unit") not in {"percent", "usd"}:
                    raise ValueError()
                if any(b.get(k) is not None and number(b[k], high=100 if k == "remaining_percent" else float("inf")) is None
                       for k in ("remaining_percent", "used", "limit", "resets_at")):
                    raise ValueError()
            snapshot.update(value)
            stale = now - value["received_at"] >= 300 or now < value["received_at"]
            for bucket in snapshot["buckets"]:
                bucket["stale"] = stale or (bucket.get("resets_at") is not None and now >= bucket["resets_at"])
            snapshot["status"] = ("stale" if any(b["stale"] for b in snapshot["buckets"]) else "available") if snapshot["buckets"] else "unavailable"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if isinstance(live.get(provider), dict):
            merge_check(snapshot, live[provider], now)
        profiles.append(snapshot)
    return profiles
