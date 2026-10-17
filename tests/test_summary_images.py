import base64
from contextlib import contextmanager
from datetime import datetime, date, timezone
import json
import struct
import sys
import threading
from types import SimpleNamespace
import zlib

import pytest

from codex_insights.date_ranges import date_window
from codex_insights.queries import dashboard, filter_clause
from codex_insights import queries
from codex_insights.summary_image_clipboard import (
    ClipboardBusy, SummaryImageBridge, copy_to_clipboard, dispatch_image, png_payload,
    MAX_PNG_BYTES, PNG_SIGNATURE,
)
from codex_insights.summary_image_preferences import SummaryImagePreferences
from codex_insights.service import Engine
from codex_insights.ingestion import refresh
from conftest import log, token
from zoneinfo import ZoneInfo


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)


@pytest.fixture
def png():
    header = struct.pack(">IIBBBBB", 1200, 720, 8, 6, 0, 0, 0)
    pixels = (b"\0" + bytes((16, 23, 28, 255)) * 1200) * 720
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def args(png, **extra):
    return {"png_base64": base64.b64encode(png).decode(), **extra}


class Adapter:
    def __init__(self, failures=0, error=None):
        self.failures, self.error = failures, error
        self.prepared = self.closed = self.writes = 0

    @contextmanager
    def prepare(self, png):
        self.prepared += 1
        try:
            yield png
        finally:
            self.closed += 1

    def write(self, packet):
        self.writes += 1
        if self.error:
            raise self.error
        if self.writes <= self.failures:
            raise ClipboardBusy()


def bridge(tmp_path, adapter=None, stopped=lambda: False, **options):
    return SummaryImageBridge(lambda: object(), stopped,
                              SummaryImagePreferences(tmp_path / "image-preference.json"),
                              adapter or Adapter(), dispatch=lambda _window, operation, _stopped: operation(), **options)


def test_png_validation_and_limits(png):
    assert png_payload(args(png)) == png
    for payload in ({}, {"png_base64": 1}, {"png_base64": "%%%"}, args(b"not png"), args(png[:-1]), args(png + b"extra"), args(png[:42] + b"damage" + png[48:])):
        with pytest.raises(ValueError):
            png_payload(payload)
    wrong_size = PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 12000, 7200, 8, 6, 0, 0, 0)) + chunk(b"IDAT", b"x") + chunk(b"IEND", b"")
    with pytest.raises(ValueError):
        png_payload(args(wrong_size))
    with pytest.raises(ValueError, match="2 MiB"):
        png_payload(args(b"x" * (MAX_PNG_BYTES + 1)))


def test_clipboard_bounded_retries_and_disposal(png):
    adapter, pauses = Adapter(failures=4), []
    copy_to_clipboard(adapter, png, lambda: False, pauses.append)
    assert adapter.writes == 5 and adapter.prepared == adapter.closed == 1
    assert pauses == [.05] * 4
    adapter = Adapter(failures=20)
    with pytest.raises(RuntimeError, match="clipboard is busy"):
        copy_to_clipboard(adapter, png, lambda: False, pauses.append)
    assert adapter.writes == 5 and adapter.closed == 1
    adapter = Adapter(error=ValueError("decoder failed"))
    with pytest.raises(ValueError):
        copy_to_clipboard(adapter, png, lambda: False)
    assert adapter.writes == adapter.closed == 1


def test_shutdown_during_retry_disposes(png):
    stopped, adapter = threading.Event(), Adapter(failures=5)
    with pytest.raises(RuntimeError, match="closing"):
        copy_to_clipboard(adapter, png, stopped.is_set, lambda _seconds: stopped.set())
    assert adapter.writes == adapter.closed == 1


def test_native_bridge_copy_save_cancel_and_preferences(tmp_path, png):
    adapter = Adapter()
    destination = tmp_path / "summary.png"
    destination.write_bytes(b"old")
    images = bridge(tmp_path, adapter, choose=lambda _window, _filename: [str(destination)])
    assert images.call("copy_summary_image", args(png)) == {"status": "copied"}
    assert adapter.writes == adapter.closed == 1
    assert images.call("save_summary_image", args(png, filename="codex-summary-2026-10-08.png")) == {"status": "saved"}
    assert destination.read_bytes() == png
    assert len(list(tmp_path.glob("tmp*"))) == 0
    images.choose = lambda _window, _filename: None
    assert images.call("save_summary_image", args(png)) == {"status": "cancelled"}
    with pytest.raises(ValueError):
        images.call("save_summary_image", args(png, filename="../elsewhere.png"))
    assert images.call("summary_image_preferences") == {"include_project_names": False}
    images.call("summary_image_preferences", {"include_project_names": True})
    assert bridge(tmp_path).call("summary_image_preferences") == {"include_project_names": True}
    with pytest.raises(ValueError):
        images.call("summary_image_preferences", {"include_project_names": "true"})


def test_preference_write_failure_and_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "preference.json"
    path.write_text("not json")
    preferences = SummaryImagePreferences(path)
    assert preferences.read()["include_project_names"] is False
    def fail(*_args):
        raise OSError("injected write failure")
    monkeypatch.setattr("codex_insights.summary_image_preferences.os.replace", fail)
    with pytest.raises(OSError):
        preferences.update(True)
    assert preferences.read()["include_project_names"] is False
    assert list(tmp_path.iterdir()) == [path]


def test_duplicate_operations_and_shutdown(tmp_path, png):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    images = bridge(tmp_path, stopped=stopped.is_set)
    def slow(_window, operation, _stopped):
        entered.set()
        assert release.wait(2)
        return operation()
    images.dispatch = slow
    result = []
    worker = threading.Thread(target=lambda: result.append(images.call("copy_summary_image", args(png))))
    worker.start()
    assert entered.wait(2)
    with pytest.raises(RuntimeError, match="already running"):
        images.call("copy_summary_image", args(png))
    release.set(); worker.join(2)
    assert result == [{"status": "copied"}]
    stopped.set()
    with pytest.raises(RuntimeError, match="closing"):
        images.call("copy_summary_image", args(png))


def test_gui_timeout_cancels_late_callback(monkeypatch):
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(Action=lambda callback: callback))
    callbacks, writes = [], []
    form = SimpleNamespace(IsDisposed=False, BeginInvoke=callbacks.append)
    with pytest.raises(RuntimeError, match="did not respond"):
        dispatch_image(SimpleNamespace(native=form), lambda: writes.append(True), lambda: False, timeout=.01)
    callbacks[0]()
    assert writes == []
    form.BeginInvoke = lambda callback: callback()
    assert dispatch_image(SimpleNamespace(native=form), lambda: "copied", lambda: False) == "copied"
    form.IsDisposed = True
    with pytest.raises(RuntimeError, match="closing"):
        dispatch_image(SimpleNamespace(native=form), lambda: writes.append(True), lambda: False)


@pytest.mark.parametrize("today,expected_hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_date_window_dst_and_inclusive_bounds(today, expected_hours):
    zone = ZoneInfo("America/New_York")
    _where, params, end = filter_clause({"range": "today"}, zone, today)
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(params[1])).total_seconds() == expected_hours * 3600
    assert date_window({"range": "7"}, date(2027, 1, 3)) == (date(2026, 12, 28), date(2027, 1, 4))
    with pytest.raises(ValueError):
        date_window({"range": "custom", "start": "2026-10-09", "end": "2026-10-08"}, today)


def test_dashboard_bounds_match_one_query_clock_and_filters(indexed, monkeypatch):
    store, root, source = indexed
    (root / "chat.jsonl").write_bytes(log() + token(100))
    refresh(store)
    calls = []
    class Clock(datetime):
        @classmethod
        def now(cls, zone=None):
            calls.append(True)
            return datetime(2026, 10, 9, 3, 59, 59, tzinfo=timezone.utc).astimezone(zone)
    monkeypatch.setattr(queries, "datetime", Clock)
    result = dashboard(store, {"range": "7", "model": "gpt-5.3-codex", "source_id": source})
    assert result["date_bounds"] == {"start": "2026-10-02", "end": "2026-10-08"}
    assert result["summary"]["total_tokens"] == 0 and len(calls) == 1
    result = dashboard(store)
    assert result["date_bounds"] == {"start": "2026-10-01", "end": "2026-10-08"}
    result = dashboard(store, {"range": "custom", "start": "2026-09-01", "end": "2026-10-02"})
    assert result["date_bounds"] == {"start": "2026-09-01", "end": "2026-10-02"}
    assert result["summary"]["total_tokens"] == 110


def test_image_actions_are_native_only_and_do_not_change_index(tmp_path):
    engine = Engine(tmp_path, demo=True)
    try:
        before = dashboard(engine.store)
        for action in ("copy_summary_image", "save_summary_image", "summary_image_preferences"):
            with pytest.raises(ValueError, match="Unknown app action"):
                engine.call(action, {})
        after = dashboard(engine.store)
        assert before["summary"] == after["summary"] and before["revision"] == after["revision"]
        assert not (tmp_path / "summary-image-preferences.json").exists()
    finally:
        engine.close()
