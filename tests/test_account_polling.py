"""Request budgets and identity feedback regressions without network access."""
from collections import Counter
from contextlib import contextmanager
import threading
import time

import pytest

from codex_insights.account_monitor import AccountMonitor
from codex_insights.codex_account import AppServerProvider, AllowanceError
from codex_insights.service import Engine


class SyntheticRPCProvider(AppServerProvider):
    def __init__(self, fail_history_identity=False):
        super().__init__()
        self.fail_history_identity = fail_history_identity
        self.calls = Counter()
        self.runaway = threading.Event()

    @contextmanager
    def session(self):
        with self.operation:
            self.history_request = False
            yield self

    def request(self, method, params=None):
        self.calls[method] += 1
        if self.calls["account/usage/read"] >= 10:
            self.runaway.set()
        if method == "account/read":
            return {"account": {"type": "chatgpt", "email": "synthetic@example.invalid"}}
        if method == "account/usage/read":
            self.history_request = True
            return {"summary": {"lifetimeTokens": 1000}}
        if method == "account/rateLimits/read":
            if self.history_request and self.fail_history_identity:
                raise AllowanceError("connection", "Synthetic identity check failure")
            return {"accountId": "synthetic-workspace",
                    "rateLimits": {"primary": {"usedPercent": 20}}}
        raise AssertionError(method)


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    pytest.fail("Account workers did not settle")


class VirtualWake:
    """Advance the worker's clock instead of waiting through polling intervals."""
    def __init__(self, cache, clock, end):
        self.cache, self.clock, self.end = cache, clock, end
        self.signaled = False

    def set(self):
        self.signaled = True

    def clear(self):
        self.signaled = False

    def wait(self, delay):
        if not self.signaled:
            self.clock[0] = min(self.end, self.clock[0] + delay)
            if self.clock[0] >= self.end:
                self.cache.stop.set()
        return self.signaled


def simulate(cache, clock, seconds):
    cache.wake = VirtualWake(cache, clock, clock[0] + seconds)
    cache._run()


def test_history_identity_failure_cannot_trigger_allowance_history_feedback_loop():
    provider = SyntheticRPCProvider(fail_history_identity=True)
    monitor = AccountMonitor(provider, clock=lambda: 1000.)
    try:
        monitor.limits.start()
        wait_for(lambda: monitor.limits.read()["next_refresh_at"] == 1060)
        monitor.history.start()
        wait_for(lambda: monitor.history.read()["next_refresh_at"] == 1300)
        assert not provider.runaway.wait(.2), "Identity changes caused repeated remote reads"
        assert provider.calls == {"account/read": 2, "account/rateLimits/read": 2,
                                  "account/usage/read": 1}
        # Clear the now-unverified account's data immediately, but keep the
        # existing deadline. History is still useful without identity proof.
        assert monitor.limits.read()["buckets"] == []
        assert monitor.limits.read()["next_refresh_at"] == 1060
        assert monitor.history.read()["summary"]["lifetime_tokens"] == 1000
        assert monitor.history.account.confirmed is None
    finally:
        monitor.close()


@pytest.mark.parametrize("section,expected_polls", [("limits", 60), ("history", 12)])
def test_automatic_request_budget_over_one_simulated_hour(section, expected_polls):
    clock, provider = [1000.], SyntheticRPCProvider()
    monitor = AccountMonitor(provider, clock=lambda: clock[0])
    try:
        simulate(getattr(monitor, section), clock, 3600)
        assert provider.calls["account/read"] == expected_polls
        assert provider.calls["account/rateLimits/read"] == expected_polls
        assert provider.calls["account/usage/read"] == (12 if section == "history" else 0)
    finally:
        monitor.close()


@pytest.mark.parametrize("section", ["limits", "history"])
def test_identity_changes_do_not_reset_exponential_failure_backoff(section):
    clock, attempts = [1000.], []
    monitor = AccountMonitor(SyntheticRPCProvider(), clock=lambda: clock[0])
    cache = getattr(monitor, section)

    def failing(changed):
        attempts.append(clock[0])
        changed(f"identity-{len(attempts)}")
        raise AllowanceError("connection", "Synthetic failure")

    cache.fetch = failing
    try:
        simulate(cache, clock, 1200)
        assert attempts == [1000, 1060, 1180, 1420, 1720, 2020]
        assert cache.read()["next_refresh_at"] == 2320
    finally:
        monitor.close()


def test_dashboard_widget_and_account_reads_only_use_cache(tmp_path):
    provider = SyntheticRPCProvider()
    engine = Engine(tmp_path, allowance_provider=provider)
    try:
        engine.accounts.start()
        monitor = engine.accounts.monitors["current"]
        wait_for(lambda: all(cache.read()["last_success_at"] is not None
                             and not cache.read()["refreshing"]
                             for cache in (monitor.limits, monitor.history)))
        calls = provider.calls.copy()
        for _ in range(25):
            for action in ("usage_limits", "accounts", "dashboard", "widget_summary", "status"):
                engine.call(action)
        assert provider.calls == calls
    finally:
        engine.close()
