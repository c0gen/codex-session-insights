import json
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from codex_insights.codex_account import AppServerProvider, AllowanceError
from codex_insights.usage_limits import UsageLimits, normalize_limits
from codex_insights.service import Engine
from codex_insights.report import export_html
from codex_insights.transfers import export_snapshot
from codex_insights.ingestion import refresh
from conftest import log, token


def raw(used=20, reset=1000):
    return {"rateLimits": {"primary": {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": reset}}}


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail("Allowance worker did not reach expected state")


class FakeProvider:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = 0
        self.closed = False
        self.release = threading.Event()
    def fetch(self, account_changed):
        self.calls += 1
        identity, value = next(self.steps)
        account_changed(identity)
        if callable(value):
            value = value(self.release)
        if isinstance(value, Exception):
            raise value
        return value
    def close(self):
        self.closed = True
        self.release.set()


@pytest.mark.parametrize("used,expected", [(-3, 100), (0, 100), (25.5, 74.5), (130, 0), (None, None), (True, None), ("20", None), (float("nan"), None), (float("inf"), None)])
def test_normalization_clamps_and_never_invents_values(used, expected):
    window = normalize_limits(raw(used))[0]["windows"][0]
    assert window["remaining_percent"] == expected
    assert window["window_duration_mins"] == 10080


def test_multi_bucket_precedence_missing_windows_and_fields():
    value = {**raw(90), "rateLimitsByLimitId": {
        "other": {"limitName": "Other bucket", "secondary": {"usedPercent": 12}, "primary": None},
        "codex": {"primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": 2000}, "secondary": {"usedPercent": 3, "windowDurationMins": 10080}},
        "empty": {}, "bad": None}}
    buckets = normalize_limits(value)
    assert [b["id"] for b in buckets] == ["codex", "empty", "other"]
    assert [w["remaining_percent"] for w in buckets[0]["windows"]] == [58, 97]
    assert buckets[1]["windows"] == []
    assert buckets[2]["windows"] == [{"id": "secondary", "remaining_percent": 88, "window_duration_mins": None, "resets_at": None}]
    assert normalize_limits({"rateLimitsByLimitId": {}, **raw()}) == []
    assert normalize_limits({}) == []


def test_stale_reset_does_not_refill_backoff_and_account_change():
    clock = [100.]
    failure = AllowanceError("timeout", "Read timed out")
    provider = FakeProvider([("A", raw(60, 120)), ("A", failure), ("A", failure), ("B", failure), ("B", raw(90, 400)), (None, AllowanceError("sign_in", "Sign in"))])
    cache = UsageLimits(provider, clock=lambda: clock[0])
    try:
        cache.refresh()
        wait_for(lambda: cache.read()["last_success_at"] == 100)
        assert cache.read()["next_refresh_at"] == 160
        clock[0] = 125  # Reset passed; preserve the observed 40% remaining.
        cache.refresh()
        wait_for(lambda: cache.read()["status"] == "stale")
        assert cache.read()["buckets"][0]["windows"][0]["remaining_percent"] == 40
        assert cache.read()["next_refresh_at"] == 185
        cache.refresh()
        wait_for(lambda: provider.calls == 3 and not cache.read()["refreshing"])
        assert cache.read()["next_refresh_at"] == 245
        cache.refresh()
        wait_for(lambda: provider.calls == 4 and not cache.read()["refreshing"])
        assert cache.read()["buckets"] == [] and cache.read()["last_success_at"] is None
        cache.refresh()
        wait_for(lambda: cache.read()["status"] == "available")
        assert cache.read()["buckets"][0]["windows"][0]["remaining_percent"] == 10
        # A caller cannot mutate the shared cache through its returned response.
        cache.read()["buckets"].clear()
        assert cache.read()["buckets"]
        cache.refresh()
        wait_for(lambda: cache.read()["error_code"] == "sign_in")
        assert cache.read()["buckets"] == []
    finally:
        cache.close()
    assert provider.closed


def test_missing_data_replaces_previous_windows_as_unavailable():
    provider = FakeProvider([("A", raw()), ("A", {})])
    cache = UsageLimits(provider)
    try:
        cache.refresh()
        wait_for(lambda: cache.read()["status"] == "available")
        cache.refresh()
        wait_for(lambda: cache.read()["error_code"] == "no_windows")
        assert cache.read()["status"] == "unavailable"
        assert cache.read()["buckets"] == [] and not cache.read()["stale"]
    finally:
        cache.close()


def test_refresh_coalescing_disable_and_shutdown_during_fetch():
    entered = threading.Event()
    def blocked(release):
        entered.set()
        release.wait(3)
        return raw()
    provider = FakeProvider([("A", blocked)])
    cache = UsageLimits(provider)
    cache.refresh()
    assert entered.wait(1)
    for _ in range(50):
        assert cache.refresh()["status"] == "refreshing"
    assert provider.calls == 1
    started = time.monotonic()
    cache.configure(False)
    cache.close()
    assert time.monotonic() - started < 1
    assert cache.read()["buckets"] == []
    assert cache.read()["status"] == "disabled"


def test_periodic_refresh_retries_without_manual_requests_and_disable_is_persistent(tmp_path):
    provider = FakeProvider([("A", AllowanceError("connection", "Disconnected")), ("A", raw(30)), ("A", raw(31))])
    cache = UsageLimits(provider, interval=.03)
    try:
        cache.start()
        wait_for(lambda: provider.calls >= 3)
        assert cache.read()["last_success_at"] is not None
        cache.configure(False)
        calls = provider.calls
        time.sleep(.08)
        assert provider.calls == calls
    finally:
        cache.close()
    engine = Engine(tmp_path, exporter=True)
    try:
        response = engine.call("usage_limits_settings", {"enabled": False})
        wait_for(lambda: any(c["id"] == response["job_id"] for c in engine.call("status")["completed"]))
    finally:
        engine.close()
    provider = FakeProvider([])
    engine = Engine(tmp_path, allowance_provider=provider)
    try:
        engine.usage_limits.start()
        assert engine.call("usage_limits")["status"] == "disabled" and provider.calls == 0
    finally:
        engine.close()


def fake_rpc(script):
    return lambda _command, **kwargs: subprocess.Popen([sys.executable, "-u", "-c", script], **kwargs)


RPC = '''
import json, sys, time
methods=[]
for line in sys.stdin:
    request=json.loads(line); methods.append(request['method'])
    method=request['method']
    if 'id' not in request: continue
    if method=='initialize': result={}
    elif method=='account/read': result={'account':{'type':'chatgpt','email':'fake@example.invalid'}}
    else: result={'rateLimits': {'primary': {'usedPercent': 40, 'windowDurationMins':10080}}, 'methods':methods}
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
'''


def test_app_server_protocol_account_only_and_owned_process_cleanup():
    provider = AppServerProvider(executable=sys.executable, popen=fake_rpc(RPC), timeout=2)
    identities = []
    result = provider.fetch(identities.append)
    assert result["methods"] == ["initialize", "initialized", "account/read", "account/rateLimits/read"]
    assert len(identities) == 1 and "@" not in identities[0]
    assert provider.process is None
    provider.close()


def test_missing_executable_timeout_and_process_shutdown():
    with pytest.raises(AllowanceError) as missing:
        AppServerProvider(discover=lambda: None).fetch(lambda _: None)
    assert missing.value.code == "missing_codex"
    provider = AppServerProvider(executable=sys.executable, popen=fake_rpc("import time; time.sleep(30)"), timeout=.15)
    started = time.monotonic()
    with pytest.raises(AllowanceError) as timeout:
        provider.fetch(lambda _: None)
    assert timeout.value.code == "timeout" and time.monotonic() - started < 2
    assert provider.process is None
    provider = AppServerProvider(executable=sys.executable, popen=fake_rpc("import time; time.sleep(30)"), timeout=10)
    failures = []
    def read():
        try: provider.fetch(lambda _: None)
        except AllowanceError as exc: failures.append(exc.code)
    thread = threading.Thread(target=read)
    thread.start()
    wait_for(lambda: provider.process is not None)
    provider.close()
    thread.join(timeout=2)
    assert not thread.is_alive() and provider.process is None and failures


def test_allowance_is_independent_of_indexing_queue_and_cached_for_both_views(indexed):
    provider = FakeProvider([("A", raw(35))])
    engine = Engine(indexed[0].directory, allowance_provider=provider)
    entered, release = threading.Event(), threading.Event()
    def writer():
        with engine.store.lock, engine.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            entered.set()
            release.wait(3)
    try:
        engine.submit("Long index", writer)
        assert entered.wait(1)
        started = time.monotonic()
        engine.call("refresh_usage_limits")
        wait_for(lambda: engine.call("usage_limits")["status"] == "available")
        assert time.monotonic() - started < 1
        assert engine.call("dashboard")["usage_limits"] == engine.call("widget_summary")["usage_limits"]
        assert provider.calls == 1
    finally:
        release.set()
        engine.close()


@pytest.mark.parametrize("options", [{"demo": True}, {"exporter": True}])
def test_demo_and_exporter_never_start_provider(tmp_path, options):
    provider = FakeProvider([])
    engine = Engine(tmp_path, allowance_provider=provider, **options)
    try:
        engine.start()
        assert engine.call("refresh_usage_limits")["status"] == "disabled"
        engine.call("usage_limits_settings", {"enabled": True})
        assert not engine.call("usage_limits")["allowed"]
        assert provider.calls == 0
    finally:
        engine.close()


def test_report_and_transfer_exclude_allowance(indexed, tmp_path):
    store, root, _ = indexed
    (root / "chat.jsonl").write_bytes(log() + token(100))
    refresh(store)
    (store.directory / "account-connections.json").write_text('{"marker":"PRIVATE_CONNECTION_MARKER"}')
    profiles = store.directory / "account-profiles"
    profiles.mkdir()
    (profiles / "auth.json").write_text('{"marker":"PRIVATE_CREDENTIAL_MARKER"}')
    snapshot = tmp_path / "usage.codex-insights"
    export_snapshot(store, snapshot)
    with zipfile.ZipFile(snapshot) as bundle:
        assert all(b"usage_limits" not in bundle.read(name) for name in bundle.namelist())
        assert all(b"PRIVATE_" not in bundle.read(name) for name in bundle.namelist())
    engine = Engine(store.directory, exporter=True)
    try:
        data = engine.call("dashboard")
        data["usage_limits"] = {"sensitive_marker": "PRIVATE_ALLOWANCE_MARKER",
                                "token_burn_rate": {"value": "PRIVATE_TOKEN_RATE_MARKER"},
                                "buckets": [{"windows": [{"burn_rate": {"value": "PRIVATE_WINDOW_RATE_MARKER"}}]}]}
        data["accounts"] = {"sensitive_marker": "PRIVATE_ACCOUNT_MARKER"}
        data["desktop"] = {"preferences": {"widget_account_ids": ["PRIVATE_CONNECTION_MARKER"]}}
        output = tmp_path / "report.html"
        # Frontend build is a prerequisite for the existing offline reports.
        export_html(data, output)
        assert "PRIVATE_" not in output.read_text(encoding="utf-8")
    finally:
        engine.close()
