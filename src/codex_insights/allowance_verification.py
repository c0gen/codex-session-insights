"""Opt-in packaged live-read smoke check; no indexing or account identifiers."""
import json
from pathlib import Path

from .codex_account import AppServerProvider, AllowanceError
from .usage_limits import normalize_limits


def verify_allowance(destination):
    provider = AppServerProvider()
    try:
        buckets = normalize_limits(provider.fetch(lambda _: None))
        ok = any(w['remaining_percent'] is not None for b in buckets for w in b['windows'])
        result = {"ok": ok, "buckets": buckets, "error": None if ok else "No allowance windows returned"}
    except AllowanceError as exc:
        result = {"ok": False, "error": str(exc), "error_code": exc.code}
    finally:
        provider.close()
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
