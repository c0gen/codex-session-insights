"""Claude plan limits through the unmodified Claude Code `/usage` command."""
import io
import json
import subprocess
import threading
import time
from datetime import datetime, timezone

import pytest

from codex_insights.account_rpc import AllowanceError
from codex_insights.claude_usage import (ARGUMENTS, ClaudeUsage, ClaudeUsageProvider, find_report,
                                         normalize_report)
from codex_insights.providers.allowances import read
from codex_insights.providers.bridge import receive
from codex_insights.providers.bridge_io import MAX_INPUT
from codex_insights.report import export_html
from codex_insights.service import Engine

NOW = datetime(2026, 10, 14, 18, tzinfo=timezone.utc)
FIVE_HOUR_RESET = "2026-10-14T21:00:00Z"
WEEKLY_RESET = "2026-10-16T19:00:00+00:00"


def report(**overrides):
    value = {
        "session": {"total_cost_usd": 0, "total_lines_added": 0, "model_usage": {"PRIVATE_MODEL": {}}},
        "rate_limits": {"limits": [
            {"kind": "session", "group": "session", "percent": 23.5, "resets_at": FIVE_HOUR_RESET,
             "severity": "normal", "is_active": True},
            {"kind": "weekly_all", "group": "weekly", "percent": 41.2, "resets_at": WEEKLY_RESET,
             "severity": "normal", "is_active": False},
            {"kind": "weekly_scoped", "group": "weekly", "percent": 120, "resets_at": WEEKLY_RESET,
             "scope": {"model": {"display_name": "Opus"}}, "severity": "critical", "is_active": False},
        ], "extra_usage": {"is_enabled": True, "used_credits": 999}},
    }
    value.update(overrides)
    return value


def stream(usage_report=None, nested=False):
    assistant = {"type": "assistant", "session_id": "s", "message": {"content": [{"type": "text", "text": "PRIVATE_TEXT"}]}}
    if usage_report is not None:
        if nested:
            assistant["message"]["usage_report"] = usage_report
        else:
            assistant["usage_report"] = usage_report
    lines = [{"type": "system", "subtype": "init", "session_id": "s"}, "not json", assistant,
             {"type": "result", "subtype": "success", "total_cost_usd": 0, "result": "PRIVATE_TEXT"}]
    return "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines).encode()


class FakeProcess:
    def __init__(self, output, block=False):
        self.pid = 4242
        self.killed = False
        self.released = threading.Event()
        self.stdout = self
        self.output, self.block = output, block

    def read(self, size):
        if self.block:
            self.released.wait(5)
            return b""
        return self.output[:size]

    def poll(self):
        return 0 if not self.block or self.killed else None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self.released.set()


class FakePopen:
    def __init__(self, *outputs, block=False):
        self.outputs, self.block = list(outputs), block
        self.calls, self.processes = [], []

    def __call__(self, arguments, **options):
        self.calls.append((arguments, options))
        process = FakeProcess(self.outputs.pop(0) if self.outputs else b"", self.block)
        self.processes.append(process)
        return process


def provider(tmp_path, popen, executable="C:/tools/claude.exe", timeout=5):
    return ClaudeUsageProvider(tmp_path / "workspace", executable=executable, timeout=timeout,
                               discover=lambda: None, popen=popen)


def test_report_is_allowlisted_and_classified_by_kind():
    buckets = normalize_report(report())["buckets"]
    assert [b["id"] for b in buckets] == ["session", "weekly_all", "weekly_scoped:Opus"]
    assert [b["remaining_percent"] for b in buckets] == [76.5, pytest.approx(58.8), 0]
    assert buckets[0]["resets_at"] == datetime(2026, 10, 14, 21, tzinfo=timezone.utc).timestamp()
    assert buckets[2]["scope_label"] == "Opus" and buckets[2]["severity"] == "critical"
    assert all(b["unit"] == "percent" and b["used"] is None for b in buckets)
    text = json.dumps(buckets)
    assert "PRIVATE" not in text and "extra_usage" not in text and "cost" not in text


def test_report_rejects_missing_limits_and_skips_bad_rows():
    with pytest.raises(AllowanceError) as missing:
        normalize_report(report(rate_limits=None))
    assert missing.value.code == "no_limits"
    with pytest.raises(AllowanceError) as absent:
        normalize_report(None)
    assert absent.value.code == "no_report"
    rows = [None, {"kind": "", "percent": 1}, {"kind": "session", "percent": "50"},
            {"kind": "session", "percent": float("nan")}, {"kind": "session", "percent": -1},
            {"kind": "session", "percent": 10, "resets_at": "garbage"}, {"kind": "session", "percent": 90}]
    buckets = normalize_report({"rate_limits": {"limits": rows}})["buckets"]
    assert len(buckets) == 1 and buckets[0]["remaining_percent"] == 90 and buckets[0]["resets_at"] is None
    assert normalize_report({"rate_limits": {"limits": []}}) == {"buckets": []}


def test_report_found_at_documented_or_nested_location():
    assert find_report(stream(report()))["rate_limits"]
    assert find_report(stream(report(), nested=True))["rate_limits"]
    assert find_report(stream()) is None
    assert find_report(b"\xff\xfe\n{}") is None


def test_fetch_runs_unmodified_claude_without_credentials_or_transcripts(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.setenv(name, "PRIVATE_SECRET")
    popen = FakePopen(stream(report()))
    result = provider(tmp_path, popen).fetch(lambda identity: None)
    assert result["rate_limits"]["limits"][0]["kind"] == "session"
    arguments, options = popen.calls[0]
    assert arguments == ["C:/tools/claude.exe", *ARGUMENTS]
    assert {"-p", "/usage", "--no-session-persistence", "--safe-mode"} <= set(arguments)
    assert options["stdin"] is subprocess.DEVNULL
    assert options["cwd"] == str(tmp_path / "workspace") and (tmp_path / "workspace").is_dir()
    assert "PRIVATE_SECRET" not in json.dumps(options["env"])


def test_fetch_reports_outdated_or_missing_claude(tmp_path):
    popen = FakePopen(stream(), b"2.1.39 (Claude Code)\n")
    with pytest.raises(AllowanceError) as outdated:
        provider(tmp_path, popen).fetch()
    assert outdated.value.code == "no_report" and "2.1.39 (Claude Code)" in str(outdated.value)
    assert popen.calls[1][0] == ["C:/tools/claude.exe", "--version"]
    with pytest.raises(AllowanceError) as missing:
        provider(tmp_path, FakePopen(), executable=None).fetch()
    assert missing.value.code == "missing_claude"

    def unavailable(*args, **kwargs):
        raise OSError("not found")
    with pytest.raises(AllowanceError) as broken:
        provider(tmp_path, unavailable).fetch()
    assert broken.value.code == "missing_claude"


def test_fetch_bounds_output_and_time(tmp_path):
    with pytest.raises(AllowanceError) as large:
        provider(tmp_path, FakePopen(b"x" * (MAX_INPUT + 2))).fetch()
    assert large.value.code == "invalid_report"
    popen = FakePopen(block=True)
    started = time.monotonic()
    with pytest.raises(AllowanceError) as slow:
        provider(tmp_path, popen, timeout=.2).fetch()
    assert slow.value.code == "timeout" and popen.processes[0].killed
    assert time.monotonic() - started < 4


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail("Claude usage check did not reach the expected state")


class FakeProvider:
    def __init__(self, *values):
        self.values, self.calls, self.closed = list(values), 0, False

    def fetch(self, changed):
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


def test_check_is_opt_in_and_memory_only(tmp_path):
    fake = FakeProvider(report(), AllowanceError("timeout", "Claude Code did not answer in time."))
    check = ClaudeUsage(tmp_path, provider=fake, interval=300)
    check.start()
    time.sleep(.05)
    assert fake.calls == 0 and check.read()["status"] == "disabled"
    assert check.refresh() == {"status": "disabled"}
    check.configure(True)
    wait_for(lambda: check.read()["last_success_at"] is not None)
    snapshot = check.read()
    assert snapshot["status"] == "available" and len(snapshot["buckets"]) == 3
    check.refresh()
    wait_for(lambda: check.read()["error_code"] == "timeout")
    assert check.read()["stale"] is True and len(check.read()["buckets"]) == 3
    check.close()
    assert fake.closed and not list(tmp_path.iterdir())


def test_newer_source_wins_and_check_state_is_reported(tmp_path):
    received = NOW.timestamp()
    receive(tmp_path, "claude_code", "status", {"rate_limits": {"five_hour": {"used_percentage": 10}}}, now=NOW)
    buckets = normalize_report(report())["buckets"]
    check = {"enabled": True, "allowed": True, "status": "available", "refreshing": False, "error": None,
             "error_code": None, "last_success_at": received + 60, "next_refresh_at": None, "stale": False,
             "buckets": buckets}
    newer = read(tmp_path, received + 61, live={"claude_code": check})[0]
    assert newer["source"] == "Claude Code /usage" and newer["received_at"] == received + 60
    assert [b["id"] for b in newer["buckets"]] == ["session", "weekly_all", "weekly_scoped:Opus"]
    assert newer["check"]["enabled"] is True and "buckets" not in newer["check"]
    older = read(tmp_path, received + 61, live={"claude_code": {**check, "last_success_at": received - 60}})[0]
    assert older["source"] == "Claude Code status line" and older["buckets"][0]["id"] == "five_hour"
    failing = read(tmp_path, received + 61, live={"claude_code": {**check, "stale": True}})[0]
    assert failing["status"] == "stale" and all(b["stale"] for b in failing["buckets"])
    after_reset = read(tmp_path, buckets[0]["resets_at"], live={"claude_code": check})[0]
    assert after_reset["buckets"][0]["stale"] is True and after_reset["buckets"][1]["stale"] is False
    unchecked = read(tmp_path, received + 61, live={"claude_code": {**check, "last_success_at": None}})[0]
    assert unchecked["source"] == "Claude Code status line" and unchecked["check"]["last_success_at"] is None


def test_demo_never_checks_and_reports_exclude_limits(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("demo mode must not start Claude Code")
    monkeypatch.setattr("codex_insights.claude_usage.find_claude", forbidden)
    monkeypatch.setattr(ClaudeUsageProvider, "_spawn", forbidden)
    engine = Engine(tmp_path, demo=True)
    try:
        assert engine.claude_usage.allowed is False
        with pytest.raises(ValueError, match="demo"):
            engine.call("claude_usage_settings", {"enabled": True})
        assert engine.call("refresh_claude_usage") == {"status": "disabled"}
        data = engine.call("dashboard")
        assert data["settings"]["claude_usage_enabled"] is False
        assert data["provider_allowances"][0]["check"]["allowed"] is False
        data["provider_allowances"][0]["buckets"] = [{"id": "PRIVATE_LIMIT_ROW"}]
        export_html(data, tmp_path / "report.html")
        assert "PRIVATE_LIMIT_ROW" not in (tmp_path / "report.html").read_text(encoding="utf-8")
    finally:
        engine.close()
