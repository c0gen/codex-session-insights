"""Request-date prices and component accounting against hand-calculated costs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from codex_insights.providers import claude_pricing
from codex_insights.providers.pricing import catalog, estimate


def item(model="claude-opus-5-5", at="2026-10-04T12:00:00+00:00", **metadata):
    return {"model": model, "timestamp": datetime.fromisoformat(at),
            "usage": {"input_tokens": 1_500_000, "cached_input_tokens": 200_000,
                      "cache_write_input_tokens": 300_000, "output_tokens": 100_000,
                      "total_tokens": 1_600_000},
            "cache_creation": {"ephemeral_5m_input_tokens": 200_000, "ephemeral_1h_input_tokens": 100_000},
            **metadata}


@pytest.mark.parametrize("model,expected,discount", [
    ("claude-opus-5-5", 7.84, .76), ("claude-sonnet-5-5", 3.92, .38),
])
def test_mixed_cache_durations_and_five_percent_cache_read(model, expected, discount):
    price = estimate(item(model))
    assert price["usd"] == pytest.approx(expected)
    assert price["cache_discount_usd"] == pytest.approx(discount)


@pytest.mark.parametrize("model,start", [
    ("claude-opus-5-5", "2026-09-22"), ("claude-sonnet-5-5", "2026-09-28"),
    ("claude-sonnet-4-6", "2026-10-11"),
])
def test_effective_dates_are_per_model_and_use_utc(model, start):
    row = item(model, start + "T00:00:00+00:00")
    assert estimate(row) is not None
    assert estimate({**row, "timestamp": row["timestamp"] - timedelta(microseconds=1)}) is None
    assert estimate({**row, "timestamp": row["timestamp"].astimezone(timezone(timedelta(hours=-4)))}) is not None


def test_dated_rate_changes_use_end_exclusive_window(monkeypatch):
    first = deepcopy(claude_pricing.PRICE_WINDOWS["claude-opus-5-5"][0])
    first["end"] = "2026-10-05"
    second = {**first, "start": "2026-10-05", "end": None, "rates": (2, 10, .1, 2.5, 4)}
    monkeypatch.setitem(claude_pricing.PRICE_WINDOWS, "claude-opus-5-5", [first, second])
    assert estimate(item())["usd"] == pytest.approx(7.84)
    assert estimate(item(at="2026-10-05T00:00:00+00:00"))["usd"] == pytest.approx(3.92)


@pytest.mark.parametrize("metadata,multiplier", [
    ({"service_tier": "standard", "speed": "standard", "inference_geo": "global"}, 1),
    ({"inference_geo": "not_available"}, 1),
    ({"speed": "fast"}, 2), ({"inference_geo": "us"}, 1.1),
    ({"speed": "fast", "inference_geo": "us"}, 2.2),
    ({"service_tier": "batch", "inference_geo": "us"}, .55),
])
def test_modifiers_apply_to_every_token_component_and_cache_discount(metadata, multiplier):
    result = estimate(item(**metadata))
    assert result["usd"] == pytest.approx(7.84 * multiplier)
    assert result["cache_discount_usd"] == pytest.approx(.76 * multiplier)


@pytest.mark.parametrize("metadata", [
    {"speed": "unknown"}, {"service_tier": "priority"}, {"inference_geo": "unknown"},
    {"speed": "fast", "service_tier": "batch"},
])
def test_unsupported_modifiers_are_unpriced(metadata):
    assert estimate(item(**metadata)) is None
    assert estimate(item("claude-sonnet-5-5", speed="fast")) is None


@pytest.mark.parametrize("patch", [
    {"input_tokens": -1}, {"output_tokens": True}, {"cached_input_tokens": "200000"},
    {"input_tokens": 100}, {"total_tokens": 1}, {"output_tokens": None},
])
def test_invalid_or_inconsistent_counters_are_unpriced(patch):
    row = item()
    row["usage"].update(patch)
    assert estimate(row) is None


@pytest.mark.parametrize("creation", [
    None, {}, {"ephemeral_5m_input_tokens": 300_000},
    {"ephemeral_5m_input_tokens": 200_000, "ephemeral_1h_input_tokens": 99_999},
    {"ephemeral_5m_input_tokens": 300_001, "ephemeral_1h_input_tokens": -1},
    {"ephemeral_5m_input_tokens": 300_000, "ephemeral_1h_input_tokens": False},
])
def test_missing_or_invalid_cache_duration_is_not_guessed(creation):
    assert estimate({**item(), "cache_creation": creation}) is None


def test_zero_usage_and_no_cache_writes_are_priceable_without_duration():
    row = item()
    row["usage"].update(input_tokens=1_200_000, cache_write_input_tokens=0, total_tokens=1_300_000)
    row.pop("cache_creation")
    assert estimate(row)["usd"] == pytest.approx(6.04)
    row["usage"] = dict.fromkeys(row["usage"], 0)
    assert estimate(row) == {"usd": 0, "cache_discount_usd": 0}
    assert estimate({**row, "model": "<synthetic>"}) is None


def test_unknown_model_and_unverified_older_history_remain_unpriced():
    assert estimate(item("claude-future")) is None
    assert estimate(item("claude-sonnet-4-6")) is None
    assert estimate(item("claude-sonnet-4-6", "2026-10-11T12:00:00+00:00"))["usd"] == pytest.approx(5.91)


def test_catalog_discloses_dates_sources_and_provider_specific_windows():
    data = catalog()
    claude = data["models"]["claude_code"]
    assert claude["price_windows"]["claude-opus-5-5"][0]["start"] == "2026-09-22"
    assert claude["price_windows"]["claude-sonnet-5-5"][0]["source"].endswith("claude-sonnet-5-5")
    assert "Standard" in claude["assumptions"]
    assert data["models"]["antigravity"]["effective_from"] == "2026-10-11"
