"""Explicit catalog updates, preserving the tested per-request pricing evaluator."""
import json
from datetime import date
from pathlib import Path

from .accounting import pricing


def catalog():
    return {"version": 1, "verified_at": "2026-10-08", "source": "https://developers.openai.com/api/docs/pricing",
            "models": json.loads(json.dumps(pricing.MODEL_RATE_RECORDS, default=lambda x:x.isoformat()))}


def apply_catalog(value):
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("models"), dict):
        raise ValueError("Unsupported pricing catalog")
    result = {}
    for model, records in value["models"].items():
        if not isinstance(model, str) or not isinstance(records, list):
            raise ValueError("Invalid model price records")
        parsed = []
        for item in records:
            item = dict(item)
            for field in ("start", "end"):
                item[field] = date.fromisoformat(item[field]) if item.get(field) else None
            rates = item.get("rates")
            if not isinstance(rates, dict) or not all(k in rates for k in ("input", "cached_input", "output", "pricing_model")):
                raise ValueError("Incomplete price record")
            def check_rates(r):
                for key, v in r.items():
                    if isinstance(v, dict):
                        check_rates(v)
                    elif key in {"input", "cached_input", "output", "cache_write"}:
                        if type(v) not in (int,float) or v < 0 or v != v or v == float("inf"):
                            raise ValueError("Invalid token price")
            check_rates(rates)
            parsed.append(item)
        result[model] = parsed
    pricing.MODEL_RATE_RECORDS.clear()
    pricing.MODEL_RATE_RECORDS.update(result)


def import_catalog(store, path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_catalog(value)
    store.set_setting("pricing_catalog", value)
    return {"models": len(value["models"]), "verified_at": value.get("verified_at")}
