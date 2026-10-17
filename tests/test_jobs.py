import threading
import time

from codex_insights import service
from codex_insights.jobs import Jobs
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from conftest import log, token


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Worker did not reach the expected state")


def test_foreground_yields_automatic_work_and_runs_in_order():
    clock = [100.0]
    jobs = Jobs(clock=lambda: clock[0])
    entered, checkpoint, release, first_entered, finish_first = [threading.Event() for _ in range(5)]
    calls = []

    def scan():
        calls.append("scan")
        entered.set()
        assert jobs.cancel.wait(3)
        checkpoint.set()
        assert release.wait(3)
        calls.append("checkpoint")
        return {"cancelled": True}

    def first():
        assert not jobs.cancel.is_set()
        first_entered.set()
        assert finish_first.wait(3)
        calls.append("settings")

    try:
        auto = jobs.submit("Live scan", scan, origin="automatic", key="automatic-refresh", cancelable=True)
        assert entered.wait(3)
        clock[0] = 200  # A scan longer than the entire fallback interval.
        one = jobs.submit("Settings", first)
        two = jobs.submit("Sources", lambda: calls.append("sources"))
        assert one["status"] == two["status"] == "queued"
        assert checkpoint.wait(3) and jobs.dirty.is_set()
        for _ in range(50):
            assert jobs.submit("Live scan", scan, origin="automatic")["status"] == "deferred"
        assert len(jobs.snapshot()["queued"]) == 2
        release.set()
        assert first_entered.wait(3)
        assert jobs.snapshot()["id"] == one["job_id"]
        assert not jobs.automatic_ready(True)
        finish_first.set()
        wait_for(lambda: len(jobs.snapshot()["completed"]) == 3)
        assert calls == ["scan", "checkpoint", "settings", "sources"]
        assert jobs.snapshot()["completed"][0]["id"] == auto["job_id"]
        assert jobs.snapshot()["completed"][0]["state"] == "cancelled"
        assert all(item["state"] == "completed" for item in jobs.snapshot()["completed"][1:])
        clock[0] = 204.9
        assert not jobs.automatic_ready(True)
        clock[0] = 205
        assert jobs.automatic_ready(True)
        clock[0] = 229.9
        assert not jobs.automatic_ready(False)
        clock[0] = 230
        assert jobs.automatic_ready(False)
    finally:
        release.set(); finish_first.set()
        jobs.close()
    assert jobs.submit("Late work", lambda: None) == {"status": "stopping"}


def test_duplicate_refreshes_share_one_queued_and_running_request():
    jobs = Jobs()
    entered, release, manual_entered, manual_release = [threading.Event() for _ in range(4)]

    def automatic():
        entered.set()
        assert release.wait(3)

    def manual():
        manual_entered.set()
        assert manual_release.wait(3)

    try:
        jobs.submit("Live scan", automatic, origin="automatic", cancelable=True)
        assert entered.wait(3)
        original = jobs.submit("Refresh", manual, key="refresh", cancelable=True)
        for _ in range(20):
            assert jobs.submit("Refresh", manual, key="refresh")["job_id"] == original["job_id"]
        assert len(jobs.snapshot()["queued"]) == 1
        release.set()
        assert manual_entered.wait(3)
        joined = jobs.submit("Refresh", manual, key="refresh")
        assert joined["status"] == "started" and joined["job_id"] == original["job_id"]
    finally:
        release.set(); manual_release.set()
        jobs.close()


def test_failures_remain_observable_after_the_next_job_and_cancel_is_scoped():
    jobs = Jobs()
    entered, release = threading.Event(), threading.Event()

    def failed():
        entered.set()
        assert release.wait(3)
        raise ValueError("")

    try:
        jobs.submit("Settings", failed)
        assert entered.wait(3)
        assert jobs.cancel_current() == {"status": "unchanged"}
        next_job = jobs.submit("Next settings", lambda: {"saved": True})
        release.set()
        wait_for(lambda: len(jobs.snapshot()["completed"]) == 2)
        completed = jobs.snapshot()["completed"]
        assert completed[0]["state"] == "failed"
        assert completed[1]["id"] == next_job["job_id"]
        assert completed[1]["state"] == "completed"
    finally:
        release.set()
        jobs.close()


def test_engine_settings_sources_and_add_folder_apply_while_live_scan_yields(tmp_path, monkeypatch):
    engine = service.Engine(tmp_path / "data")
    for source in engine.store.sources():
        engine.store.forget_source(source["id"])
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "chat.jsonl").write_bytes(log() + token(100))
    sid = engine.store.add_source(root)
    refresh(engine.store)
    entered, release = threading.Event(), threading.Event()

    def live_scan(store, progress, cancel, rebuild, automatic):
        assert automatic
        entered.set()
        assert cancel.wait(3)
        assert release.wait(3)
        return {"cancelled": True}

    monkeypatch.setattr(service, "refresh", live_scan)
    monkeypatch.setattr(engine, "configure_watchers", lambda: None)
    new_root = tmp_path / "new-sessions"
    new_root.mkdir()
    monkeypatch.setattr(engine, "choose", lambda *args: str(new_root))
    try:
        engine.refresh(automatic=True)
        assert entered.wait(3)
        settings = engine.call("settings", {"timezone": "UTC", "assumed_fast_percent": 25, "device_label": "Saved label"})
        sources = engine.call("source_enabled", {"id": sid, "enabled": False})
        added = engine.call("add_source")
        assert {settings["status"], sources["status"], added["status"]} == {"queued"}
        release.set()
        wait_for(lambda: len(engine.call("status")["completed"]) == 4)
        assert engine.store.setting("timezone") == "UTC"
        assert engine.store.setting("device_label") == "Saved label"
        assert engine.store.setting("assumed_fast_percent") == 25
        assert dashboard(engine.store)["summary"]["total_tokens"] == 0
        assert any(source["root"] == str(new_root.resolve()) for source in engine.store.sources())
        assert engine.dirty.is_set()
        assert all(item["state"] == "completed" for item in engine.call("status")["completed"][1:])
    finally:
        release.set()
        engine.close()
