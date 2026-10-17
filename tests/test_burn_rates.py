import pytest

from codex_insights.burn_rates import AllowanceBurnRates, RollingRate


def test_units_warmup_and_idle_time():
    tokens = RollingRate(interval=300, unit_seconds=60)
    tokens.observe(1_000_000, 1000)
    assert tokens.read() == {"value": None, "status": "collecting", "observed_seconds": 0, "updated_at": 1000}
    tokens.observe(1_012_400, 1030)
    assert tokens.read()["status"] == "collecting"
    tokens.observe(1_062_000, 1300)
    assert tokens.read() == {"value": 12_400, "status": "available", "observed_seconds": 300, "updated_at": 1300}
    tokens.observe(1_062_000, 1600)
    assert tokens.read()["value"] == 0

    allowance = RollingRate(interval=60, unit_seconds=3600)
    allowance.observe(20, 1000)
    allowance.observe(20.04, 1060)
    assert allowance.read()["value"] == pytest.approx(2.4)
    assert allowance.read()["observed_seconds"] == 60


def test_irregular_intervals_retain_reading_before_cutoff_and_use_actual_time():
    rate = RollingRate(interval=60, unit_seconds=60)
    for at in (0, 70, 130, 235, 310, 365):
        rate.observe(at * 2, at)
    assert rate.read()["observed_seconds"] == 365
    assert rate.read()["value"] == 120
    rate.observe(760, 380)
    assert rate.read()["observed_seconds"] == 310
    assert rate.read()["value"] == 120


def test_old_burst_ages_out_at_exact_cutoff():
    rate = RollingRate(interval=60, unit_seconds=60)
    rate.observe(0, 0)
    for at in (60, 120, 180, 240, 300):
        rate.observe(60, at)
    assert rate.read()["value"] == 12
    rate.observe(60, 360)
    assert rate.read()["value"] == 0
    assert rate.read()["observed_seconds"] == 300


@pytest.mark.parametrize("missing", [None, True, "100", -1, float("nan"), float("inf")])
def test_missing_or_invalid_counter_is_unavailable_and_breaks_series(missing):
    rate = RollingRate(interval=60, unit_seconds=60)
    rate.observe(0, 0)
    rate.observe(100, 60)
    rate.observe(missing, 120)
    assert rate.read() == {"value": None, "status": "unavailable", "observed_seconds": 0, "updated_at": 120}
    rate.observe(200, 180)
    assert rate.read()["status"] == "collecting"


@pytest.mark.parametrize("at,value,key", [(121, 200, "A"), (60, 99, "A"), (-1, 200, "A"), (60, 200, "B")])
def test_gap_counter_correction_clock_reversal_and_series_change_restart(at, value, key):
    rate = RollingRate(interval=60, unit_seconds=60)
    rate.observe(100, 0, "A")
    rate.observe(value, at, key)
    assert rate.read()["status"] == "collecting"
    assert rate.read()["observed_seconds"] == 0


def test_duplicate_timestamp_does_not_add_elapsed_time_or_divide_by_zero():
    rate = RollingRate(interval=60, unit_seconds=60)
    rate.observe(0, 0)
    rate.observe(60, 60)
    rate.observe(70, 60)
    assert rate.read()["value"] == 70
    assert rate.read()["observed_seconds"] == 60


def test_read_stale_disabled_and_reset_never_add_samples():
    rate = RollingRate(interval=60, unit_seconds=60)
    rate.observe(0, 0)
    rate.observe(100, 60)
    expected = rate.read()
    for _ in range(10):
        assert rate.read() == expected
        assert rate.read(stale=True) == {**expected, "status": "stale"}
    assert rate.read(enabled=False)["value"] is None
    rate.reset()
    assert rate.read() == {"value": None, "status": "unavailable", "observed_seconds": 0, "updated_at": None}


def allowance(remaining=80, reset=10000, duration=300):
    return {"id": "primary", "remaining_percent": remaining,
            "resets_at": reset, "window_duration_mins": duration}


def snapshot(buckets):
    return {"buckets": buckets, "enabled": True, "stale": False}


def test_allowance_bucket_window_isolation_disappearance_and_missing_values():
    rates = AllowanceBurnRates()
    first = snapshot([{"id": "codex", "windows": [allowance(), {**allowance(), "id": "secondary"}]},
                      {"id": "other", "windows": [allowance()]}])
    rates.observe(first, 0)
    second = snapshot([{"id": "codex", "windows": [allowance(79), {**allowance(79.5), "id": "secondary"}]},
                       {"id": "other", "windows": [allowance(None)]}])
    rates.observe(second, 60)
    rates.decorate(second)
    assert [w["burn_rate"]["value"] for w in second["buckets"][0]["windows"]] == [60, 30]
    assert second["buckets"][1]["windows"][0]["burn_rate"]["status"] == "unavailable"
    rates.observe(snapshot([]), 120)
    rates.observe(first, 180)
    rates.decorate(first)
    assert all(w["burn_rate"]["status"] == "collecting" for b in first["buckets"] for w in b["windows"])


@pytest.mark.parametrize("window", [allowance(85), allowance(79, reset=20000), allowance(79, duration=10080)])
def test_allowance_refill_reset_or_duration_change_restarts(window):
    rates = AllowanceBurnRates()
    rates.observe(snapshot([{"id": "codex", "windows": [allowance()]}]), 0)
    changed = snapshot([{"id": "codex", "windows": [window]}])
    rates.observe(changed, 60)
    rates.decorate(changed)
    assert window["burn_rate"]["status"] == "collecting"


