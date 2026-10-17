import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from codex_insights.account_data import normalize_history, normalize_resets
from codex_insights.account_monitor import AccountMonitor
from codex_insights.account_storage import AccountRegistry
from codex_insights.accounts import Accounts
from codex_insights.codex_account import AppServerProvider, AllowanceError
from codex_insights.desktop_preferences import DesktopPreferences
from codex_insights.storage import Store
from codex_insights.service import Engine


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail("Account operation did not reach expected state")


def limits(used=20, credits=None):
    return {"rateLimits": {"primary": {"usedPercent": used, "windowDurationMins": 300}},
            "rateLimitResetCredits": credits}


class State:
    def __init__(self):
        self.identity = "A"
        self.limits = limits()
        self.history = {"summary": {"lifetimeTokens": 0}, "dailyUsageBuckets": [{"startDate": "2026-10-08", "tokens": 0}]}
        self.calls = {"limits": 0, "history": 0, "logout": 0}
        self.entered, self.release, self.login_done = threading.Event(), threading.Event(), threading.Event()
        self.block_limits = False
        self.error = None


class Provider:
    def __init__(self, state, home=None):
        self.state, self.home = state, home
        self.plan = "pro"
        self.closed = False

    def fetch(self, changed):
        state = self.state
        state.calls["limits"] += 1
        changed(state.identity)
        if state.block_limits:
            state.entered.set()
            state.release.wait(4)
        if state.error:
            raise state.error
        return state.limits

    def fetch_history(self, changed):
        self.state.calls["history"] += 1
        changed(self.state.identity)
        return self.state.history

    def login(self, opened, cancel, timeout):
        opened("https://auth.openai.com/authorize?state=synthetic")
        deadline = time.monotonic() + timeout
        while not cancel.is_set() and time.monotonic() < deadline:
            if self.state.login_done.wait(.01):
                self.home.joinpath("auth.json").write_text('{"synthetic":true}')
                return
        raise AllowanceError("cancelled" if cancel.is_set() else "login_timeout", "Synthetic sign-in ended.")

    def logout(self):
        assert self.home is not None
        self.state.calls["logout"] += 1

    def close(self):
        self.closed = True
        self.state.release.set()


def manager(tmp_path, **kwargs):
    states = {}
    def factory(home=None):
        key = home.name if home else "current"
        return Provider(states.setdefault(key, State()), home)
    value = Accounts(tmp_path, provider_factory=factory, opener=lambda _: True, **kwargs)
    return value, states


def connect(value, states, label="Work"):
    result = value.connect(label)
    identifier = result["account_id"]
    states[identifier].login_done.set()
    wait_for(lambda: value.login.read()["status"] == "completed")
    return identifier


def test_history_nullable_zero_dates_and_repeated_buckets():
    value = normalize_history({"summary": {"lifetimeTokens": 0, "peakDailyTokens": True},
        "dailyUsageBuckets": [{"startDate": "2026-02-30", "tokens": 2},
                             {"startDate": "2026-10-08", "tokens": 8},
                             {"startDate": "2026-10-08", "tokens": 9},
                             {"startDate": "2026-10-07", "tokens": 0},
                             {"startDate": "2026-10-06", "tokens": -1}]})
    assert value["summary"]["lifetime_tokens"] == 0
    assert value["summary"]["peak_daily_tokens"] is None
    assert value["daily"] == [{"day": "2026-10-07", "tokens": 0}, {"day": "2026-10-08", "tokens": 9}]
    assert normalize_history({})["daily"] is None
    assert normalize_history({"dailyUsageBuckets": []})["daily"] == []


def test_reset_count_partial_details_and_expiration_semantics():
    assert normalize_resets({}) is None
    assert normalize_resets({"rateLimitResetCredits": {"availableCount": 4}}) == {
        "available_count": 4, "credits": None, "details_complete": False}
    value = normalize_resets({"rateLimitResetCredits": {"availableCount": 7, "credits": [
        {"id": "no-expiry", "status": "available", "expiresAt": None},
        {"id": "unknown", "status": "available"},
        {"id": "dated", "status": "available", "expiresAt": 1000},
        {"id": "bad-date", "expiresAt": float("nan")}]}})
    assert value["available_count"] == 7 and not value["details_complete"]
    assert value["credits"][0]["id"] == "dated"
    kinds = {c["id"]: c["expiration"] for c in value["credits"]}
    assert kinds == {"dated": "dated", "no-expiry": "none", "unknown": "unknown", "bad-date": "unknown"}
    extreme = normalize_resets({"rateLimitResetCredits": {"availableCount": 2, "credits": [
        {"id": "epoch", "expiresAt": 0}, {"id": "overflow", "expiresAt": 1e100}]}})
    assert extreme["credits"][0]["expires_at"] == 0
    assert extreme["credits"][0]["expiration"] == "dated"
    assert extreme["credits"][1]["expiration"] == "unknown"


def test_pausing_current_does_not_disable_global_refresh(tmp_path):
    engine = Engine(tmp_path, allowance_provider=Provider(State()))
    try:
        engine.call("account_settings", {"id": "current", "enabled": False})
        data = engine.call("dashboard")
        assert not data["usage_limits"]["enabled"]
        assert data["settings"]["live_usage_enabled"]
        assert engine.call("accounts")["enabled"]
    finally:
        engine.close()


def test_account_workers_and_sections_are_independent(tmp_path):
    value, states = manager(tmp_path)
    first = connect(value, states)
    states["current"].block_limits = True
    value.start()
    try:
        assert states["current"].entered.wait(1)
        wait_for(lambda: value.monitors[first].limits.read()["status"] == "available")
        wait_for(lambda: value.monitors["current"].history.read()["status"] == "available")
        assert not value.monitors["current"].limits.read()["last_success_at"]
        assert value.monitors[first].history.read()["summary"]["lifetime_tokens"] == 0
    finally:
        value.close()


def test_identity_change_discards_inflight_old_data_from_both_sections():
    state = State()
    state.block_limits = True
    monitor = AccountMonitor(Provider(state))
    monitor.limits.refresh()
    try:
        assert state.entered.wait(1)
        state.identity = "B"
        monitor.history.refresh()
        wait_for(lambda: monitor.history.read()["status"] == "available")
        state.release.set()
        wait_for(lambda: not monitor.limits.read()["refreshing"])
        assert monitor.limits.read()["last_success_at"] is None
        state.block_limits = False
        state.limits = limits(77)
        monitor.limits.refresh()
        wait_for(lambda: monitor.limits.read()["status"] == "available")
        assert monitor.limits.read()["buckets"][0]["windows"][0]["remaining_percent"] == 23
    finally:
        monitor.close()


def test_browser_connections_persist_and_never_touch_current_home(tmp_path, monkeypatch):
    current = tmp_path / "main-codex"
    current.mkdir()
    auth = current / "auth.json"
    auth.write_text("synthetic-main-sign-in")
    monkeypatch.setenv("CODEX_HOME", str(current))
    value, states = manager(tmp_path)
    try:
        identifier = connect(value, states)
        profile = value.registry.home(identifier)
        assert profile != current
        assert auth.read_text() == "synthetic-main-sign-in"
        assert os.environ["CODEX_HOME"] == str(current)
        value.update(identifier, {"label": "Research", "enabled": False})
        assert json.loads(value.registry.path.read_text())[1] == {"id": identifier, "label": "Research", "enabled": False}
        assert "synthetic" not in json.dumps(value.read())
        with pytest.raises(ValueError):
            value.remove("current")
    finally:
        value.close()
    restored, _ = manager(tmp_path)
    try:
        assert restored.entries[identifier]["label"] == "Research"
        assert not restored.monitors[identifier].limits.read()["enabled"]
    finally:
        restored.close()


@pytest.mark.parametrize("finish", ["completed", "cancelled"])
def test_sign_in_link_available_only_while_waiting(tmp_path, finish):
    value, states = manager(tmp_path)
    value.login.opener = lambda _: False
    try:
        assert "url" not in value.login.read()
        identifier = value.connect("Other browser")["account_id"]
        wait_for(lambda: bool(value.login.read().get("error")))
        assert value.read()["login"]["url"] == "https://auth.openai.com/authorize?state=synthetic"
        if finish == "completed":
            states[identifier].login_done.set()
        else:
            assert "url" not in value.login.cancel()
        wait_for(lambda: value.login.read()["status"] == finish)
        assert "url" not in value.read()["login"]
    finally:
        value.close()


def test_cancel_timeout_and_only_one_login(tmp_path):
    value, states = manager(tmp_path, login_timeout=.1)
    try:
        result = value.connect("First")
        with pytest.raises(ValueError):
            value.connect("Second")
        value.login.cancel()
        wait_for(lambda: value.login.read()["status"] == "cancelled")
        assert result["account_id"] not in value.entries
        value.connect("Timeout")
        wait_for(lambda: value.login.read()["status"] == "failed")
        assert set(value.entries) == {"current"}
        identifier = connect(value, states)
        states[identifier].login_done.clear()
        value.connect(identifier=identifier)
        value.login.cancel()
        wait_for(lambda: value.login.read()["status"] == "cancelled")
        assert not value.monitors[identifier].limits.stop.is_set()
    finally:
        value.close()


def test_remove_during_refresh_stops_readers_and_removes_only_own_credentials(tmp_path):
    value, states = manager(tmp_path)
    first = connect(value, states)
    second = connect(value, states, "Personal")
    states[first].block_limits = True
    states[first].release.clear()
    value.start()
    try:
        assert states[first].entered.wait(1)
        monitor = value.monitors[first]
        value.remove(first)
        assert first not in [a["id"] for a in value.read()["accounts"]]
        wait_for(lambda: states[first].calls["logout"] == 1 and not value.registry.home(first).joinpath("auth.json").exists())
        assert value.registry.home(second).joinpath("auth.json").exists()
        assert states[second].calls["logout"] == 0 and states["current"].calls["logout"] == 0
        assert monitor.limits.read()["last_success_at"] is None
    finally:
        value.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_reconnect_preserves_preferences_edited_during_login(tmp_path, cancel):
    value, states = manager(tmp_path)
    try:
        identifier = connect(value, states)
        states[identifier].login_done.clear()
        value.connect(identifier=identifier)
        value.update(identifier, {"label": "New label", "enabled": False})
        if cancel:
            value.login.cancel()
        else:
            states[identifier].login_done.set()
        wait_for(lambda: value.login.read()["status"] in {"completed", "cancelled"})
        assert value.entries[identifier]["label"] == "New label"
        assert not value.entries[identifier]["enabled"]
        assert not value.monitors[identifier].limits.enabled
    finally:
        value.close()


def test_unavailable_history_does_not_hide_allowance_or_zero(tmp_path):
    value, states = manager(tmp_path)
    states["current"].history = {}
    value.start()
    try:
        wait_for(lambda: value.current.read()["status"] == "available")
        wait_for(lambda: value.monitors["current"].history.read()["last_success_at"] is not None)
        assert value.monitors["current"].history.read()["status"] == "unavailable"
        states["current"].error = AllowanceError("timeout", "Synthetic timeout")
        value.refresh("current")
        wait_for(lambda: value.current.read()["stale"])
        assert value.current.read()["buckets"][0]["windows"][0]["remaining_percent"] == 80
    finally:
        value.close()


def test_expiry_triggers_one_refresh_without_decrementing_count():
    state = State()
    expiry = time.time() + .2
    state.limits = limits(80, {"availableCount": 5, "credits": [
        {"id": "expiring", "status": "available", "expiresAt": expiry}]})
    monitor = AccountMonitor(Provider(state))
    try:
        monitor.start()
        wait_for(lambda: state.calls["limits"] >= 2)
        observed = state.calls["limits"]
        time.sleep(.15)
        assert state.calls["limits"] == observed
        assert monitor.limits.read()["reset_credits"]["available_count"] == 5
        assert monitor.limits.read()["buckets"][0]["windows"][0]["remaining_percent"] == 20
    finally:
        monitor.close()


def test_disabled_modes_and_widget_order_validation(tmp_path):
    value, states = manager(tmp_path, allowed=False)
    try:
        value.start()
        with pytest.raises(ValueError):
            value.connect("No network")
        assert not any(sum(state.calls.values()) for state in states.values())
    finally:
        value.close()
    store = Store(tmp_path)
    prefs = DesktopPreferences(store)
    second = "a" * 32
    prefs.update({"widget_account_ids": [second, "current"], "widget_account_buckets": {second: "codex"}})
    assert DesktopPreferences(store).read()["widget_account_ids"] == [second, "current"]
    snapshot = prefs.read()
    snapshot["widget_account_ids"].clear()
    assert prefs.read()["widget_account_ids"]
    with pytest.raises(ValueError):
        prefs.update({"widget_account_ids": ["current", "current"]})
    with pytest.raises(ValueError):
        AccountRegistry(tmp_path).home("../main-codex")


def test_rpc_isolates_home_and_buffers_early_login_notifications(tmp_path):
    recorded = []
    script = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    method = request['method']
    result = {}
    if method == 'account/login/start':
        print(json.dumps({'method':'account/login/completed','params':{'loginId':'test','success':True}}), flush=True)
        result = {'loginId':'test','authUrl':'https://auth.openai.com/example','type':'chatgpt'}
    print(json.dumps({'id':request['id'],'result':result}), flush=True)
"""
    def popen(command, **options):
        recorded.append((command, options))
        return subprocess.Popen([sys.executable, "-u", "-c", script], **options)
    provider = AppServerProvider(executable=sys.executable, popen=popen, home=tmp_path, timeout=1)
    urls = []
    try:
        provider.login(urls.append, threading.Event(), timeout=1)
        assert urls == ["https://auth.openai.com/example"]
        command, options = recorded[0]
        assert options["env"]["CODEX_HOME"] == str(tmp_path)
        assert options["cwd"] == str(tmp_path)
        assert 'cli_auth_credentials_store="file"' in command
        assert provider.process is None
    finally:
        provider.close()


def test_rpc_unsupported_history_is_safe_and_main_cannot_login(tmp_path):
    script = """
import json,sys
for line in sys.stdin:
    r=json.loads(line)
    if 'id' not in r: continue
    m=r['method']
    if m=='account/usage/read':
        print(json.dumps({'id':r['id'],'error':{'code':-32601,'message':'SECRET SERVER MESSAGE'}}),flush=True)
        continue
    v={'account':{'type':'chatgpt','email':None}} if m=='account/read' else {}
    print(json.dumps({'id':r['id'],'result':v}),flush=True)
"""
    provider = AppServerProvider(executable=sys.executable, timeout=1,
        popen=lambda command, **options: subprocess.Popen([sys.executable, "-u", "-c", script], **options))
    try:
        with pytest.raises(AllowanceError) as failure:
            provider.fetch_history(lambda _: None)
        assert failure.value.code == "unsupported" and "SECRET" not in str(failure.value)
        with pytest.raises(AllowanceError):
            provider.login(lambda _: None, threading.Event())
    finally:
        provider.close()


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_history_endpoint_still_refreshes_when_allowance_fails(failure):
    script = """
import json,sys,time
for line in sys.stdin:
    r=json.loads(line)
    if 'id' not in r: continue
    m=r['method']
    if m=='account/rateLimits/read':
        if FAILURE=='timeout': time.sleep(10)
        print(json.dumps({'id':r['id'],'error':{'code':-32000,'message':'SECRET ERROR'}}),flush=True)
        continue
    if m=='account/read': v={'account':{'type':'chatgpt','email':'synthetic@example.invalid'}}
    elif m=='account/usage/read': v={'summary':{'lifetimeTokens':0},'dailyUsageBuckets':[]}
    else: v={}
    print(json.dumps({'id':r['id'],'result':v}),flush=True)
""".replace("FAILURE", repr(failure))
    provider = AppServerProvider(executable=sys.executable, timeout=.2,
        popen=lambda command, **options: subprocess.Popen([sys.executable, "-u", "-c", script], **options))
    try:
        with pytest.raises(AllowanceError):
            provider.fetch(lambda _: None)
        assert provider.fetch_history(lambda _: None)["summary"]["lifetimeTokens"] == 0
        assert provider.process is None
    finally:
        provider.close()
