import threading
import time
from datetime import datetime, timezone

import pytest

from codex_insights.account_monitor import AccountMonitor
from codex_insights.account_rpc import AllowanceError
from codex_insights.service import Engine


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    pytest.fail("Account rate cache did not reach expected state")


class Provider:
    def __init__(self):
        self.identity, self.used, self.tokens = "A", 20, 1000
        self.limits_error = self.history_error = None
        self.calls = {"limits": 0, "history": 0}
        self.block = False
        self.entered, self.release = threading.Event(), threading.Event()

    def fetch(self, changed):
        self.calls["limits"] += 1
        changed(self.identity)
        if self.block:
            self.entered.set()
            self.release.wait(3)
        if self.limits_error:
            raise self.limits_error
        return {"rateLimits": {"primary": {"usedPercent": self.used,
                "windowDurationMins": 300, "resetsAt": 10000}}}

    def fetch_history(self, changed):
        self.calls["history"] += 1
        changed(self.identity)
        if self.history_error:
            raise self.history_error
        return {"summary": {"lifetimeTokens": self.tokens}}

    def close(self):
        self.release.set()


def refreshed(monitor, at):
    monitor.refresh()
    wait_for(lambda: all(cache.read()["last_success_at"] == at and not cache.read()["refreshing"]
                         for cache in (monitor.limits, monitor.history)))


def values(monitor):
    allowance = monitor.read()["allowance"]
    assert "token_burn_rate" not in allowance
    return [allowance["buckets"][0]["windows"][0]["burn_rate"]]


@pytest.fixture
def account():
    provider, clock = Provider(), [1000.]
    monitor = AccountMonitor(provider, clock=lambda: clock[0])
    try:
        yield monitor, provider, clock
    finally:
        monitor.close()


def seed_rates(monitor, provider, clock):
    refreshed(monitor, clock[0])
    provider.used, provider.tokens = 21, 1600
    clock[0] += 60
    refreshed(monitor, clock[0])
    assert [rate["value"] for rate in values(monitor)] == [60]


def test_cache_reads_do_not_sample_and_freshness_is_independent(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    initial = values(monitor)
    calls = dict(provider.calls)
    for _ in range(20):
        assert values(monitor) == initial
    assert provider.calls == calls
    provider.history_error = AllowanceError("timeout", "Synthetic history timeout")
    monitor.history.refresh()
    wait_for(lambda: monitor.history.read()["stale"])
    assert values(monitor) == initial

    provider.history_error = None
    provider.limits_error = AllowanceError("timeout", "Synthetic allowance timeout")
    monitor.refresh()
    wait_for(lambda: monitor.limits.read()["stale"] and not monitor.history.read()["stale"])
    assert values(monitor) == [{**initial[0], "status": "stale"}]


def test_identity_change_clears_allowance_rate_series(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    provider.identity = "B"
    clock[0] += 60
    refreshed(monitor, clock[0])
    assert all(rate["status"] == "collecting" for rate in values(monitor))


def test_pause_resume_discards_rates_and_keeps_explicit_zero(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    monitor.configure(False)
    assert all(rate["value"] is None for rate in values(monitor))
    clock[0] += 60
    monitor.configure(True)
    refreshed(monitor, clock[0])
    assert all(rate["status"] == "collecting" for rate in values(monitor))
    clock[0] += 60
    refreshed(monitor, clock[0])
    assert all(rate["value"] == 0 for rate in values(monitor))


def test_missing_history_counter_does_not_hide_allowance(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    provider.tokens = None
    clock[0] += 60
    refreshed(monitor, clock[0])
    assert values(monitor)[0]["status"] == "available"


def test_inflight_old_account_read_cannot_populate_new_rate(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    provider.block = True
    monitor.limits.refresh()
    assert provider.entered.wait(1)
    provider.identity = "B"
    monitor.history.refresh()
    wait_for(lambda: monitor.history.account == "B" and not monitor.history.read()["refreshing"])
    provider.release.set()
    wait_for(lambda: not monitor.limits.read()["refreshing"])
    result = monitor.read()["allowance"]
    assert result["buckets"] == []
    assert "token_burn_rate" not in result


def test_failed_long_gap_restarts_estimate_on_recovery(account):
    monitor, provider, clock = account
    seed_rates(monitor, provider, clock)
    provider.limits_error = provider.history_error = AllowanceError("timeout", "Synthetic timeout")
    clock[0] += 601
    monitor.refresh()
    wait_for(lambda: monitor.limits.read()["error_code"] and monitor.history.read()["error_code"])
    assert all(rate["status"] == "stale" for rate in values(monitor))
    provider.limits_error = provider.history_error = None
    refreshed(monitor, clock[0])
    assert all(rate["status"] == "collecting" for rate in values(monitor))


def test_dashboard_accounts_share_local_rate_independently_of_account_state(indexed, monkeypatch):
    store, _, source = indexed
    provider, clock = Provider(), [1000.]
    engine = Engine(store.directory, allowance_provider=provider)
    refreshes = []
    monkeypatch.setattr(engine, "refresh", lambda: refreshes.append(True))
    engine.local_token_burn.clock = lambda: clock[0]
    stamp = lambda at: datetime.fromtimestamp(at, timezone.utc).isoformat()
    with store.connect() as db:
        db.execute("UPDATE sources SET updated=?", (stamp(1000),))
        db.execute("INSERT INTO records(event_id,source_id,kind,ts,total,cost,priced) VALUES('local',?,'usage',?,3000,0.25,1)",
                   (source, stamp(990)))
    monitor = engine.accounts.monitors["current"]
    monitor.limits.clock = monitor.history.clock = lambda: clock[0]
    try:
        assert engine.call("refresh_usage_limits")["status"] == "started"
        wait_for(lambda: all(provider.calls.values()) and all(cache.read()["last_success_at"] == 1000
                          for cache in (monitor.limits, monitor.history)))
        provider.used, provider.tokens = 21, 999999999
        clock[0] = 1060
        engine.call("refresh_usage_limits")
        wait_for(lambda: all(cache.read()["last_success_at"] == 1060 for cache in (monitor.limits, monitor.history)))
        expected = engine.call("usage_limits")
        assert expected["token_burn_rate"]["value"] == 600
        assert expected["token_burn_rate"] == engine.call("accounts")["token_burn_rate"]
        assert expected["cost_burn_rate"]["value"] == .05
        assert expected["cost_burn_rate"] == engine.call("accounts")["cost_burn_rate"]
        assert "token_burn_rate" not in engine.call("accounts")["accounts"][0]["allowance"]
        assert "cost_burn_rate" not in engine.call("accounts")["accounts"][0]["allowance"]
        assert expected == engine.call("dashboard")["usage_limits"]
        assert expected == engine.call("widget_summary")["usage_limits"]
        assert engine.call("dashboard", {"range": "today", "project_id": "missing", "model": "missing"})["usage_limits"] == expected
        provider.history_error = provider.limits_error = AllowanceError("timeout", "Synthetic timeout")
        monitor.refresh()
        wait_for(lambda: monitor.history.read()["stale"] and monitor.limits.read()["stale"])
        assert engine.call("accounts")["token_burn_rate"] == expected["token_burn_rate"]
        assert engine.call("accounts")["cost_burn_rate"] == expected["cost_burn_rate"]
        engine.call("account_settings", {"id": "current", "enabled": False})
        assert engine.call("accounts")["token_burn_rate"] == expected["token_burn_rate"]
        assert engine.call("accounts")["cost_burn_rate"] == expected["cost_burn_rate"]
        provider.identity = "B"
        provider.history_error = provider.limits_error = None
        engine.call("account_settings", {"id": "current", "enabled": True})
        refreshed(monitor, clock[0])
        assert engine.call("usage_limits")["token_burn_rate"] == expected["token_burn_rate"]
        assert refreshes
    finally:
        engine.close()


def test_refresh_coalesces_local_index_and_account_requests_but_widget_does_not_scan(indexed, monkeypatch):
    store, _, _ = indexed
    provider = Provider()
    engine = Engine(store.directory, allowance_provider=provider)
    entered, release = threading.Event(), threading.Event()
    scans = []
    def scan(*args):
        scans.append(True)
        entered.set()
        release.wait(3)
    monkeypatch.setattr("codex_insights.service.refresh", scan)
    try:
        # The compact widget's existing action still only refreshes account data.
        engine.call("account_refresh", {"id": "current"})
        assert not scans
        # A blocked allowance fetch coalesces repeated refreshes without blocking history.
        wait_for(lambda: not engine.accounts.current.read()["refreshing"])
        provider.block = True
        engine.call("refresh_usage_limits")
        assert provider.entered.wait(1)
        assert entered.wait(1)
        before = provider.calls["limits"]
        for _ in range(10):
            assert engine.call("refresh_usage_limits")["status"] == "refreshing"
            engine.call("account_refresh", {"refresh_local": True})
        assert provider.calls["limits"] == before
        assert len(scans) == 1 and not engine.jobs.snapshot()["queued"]
    finally:
        release.set()
        engine.close()
