"""Existing indexes must recover from raw facts without touching their inputs."""
import json
import threading

import pytest

from codex_insights import cli, projection
from codex_insights.buckets import update_segment
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.service import Engine
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import event, log, token


def seed_family(store, root):
    (root / "parent.jsonl").write_bytes(log("parent") + token(100))
    (root / "child.jsonl").write_bytes(
        event("session_meta", {"id": "child", "source": "cli", "forked_from_id": "parent"}, 5)
        + event("turn_context", {"model": "gpt-5.3-codex"}, 5) + token(100, 6))
    refresh(store)
    assert dashboard(store)["summary"]["total_tokens"] == 220


def stale_projection(store):
    with store.connect() as db:
        child = db.execute("SELECT segment_id FROM canonical WHERE session_id='child'").fetchone()[0]
        db.execute("DELETE FROM records WHERE session_id='child' AND kind='usage'")
        update_segment(db, child)
        db.execute("UPDATE canonical SET diagnostic=? WHERE session_id='child'",
                   (json.dumps({"accounting": "exact_parent_prefix", "replay_tokens": 110}),))
        db.execute("DELETE FROM settings WHERE key='projection_version'")
    assert dashboard(store)["summary"]["total_tokens"] == 110


def raw_facts(store):
    with store.connect() as db:
        return [tuple(row) for row in db.execute("SELECT source_id,segment_id,fact FROM candidates ORDER BY source_id,segment_id")]


def test_offline_refresh_upgrades_once_and_keeps_raw_inputs(indexed):
    store, root, sid = indexed
    seed_family(store, root)
    originals = {p.name: p.read_bytes() for p in root.glob("*.jsonl")}
    facts = raw_facts(store)
    stale_projection(store)
    before = store.setting("data_revision")
    offline = root.with_name("offline-sessions")
    root.rename(offline)
    assert refresh(Store(store.directory))["bytes_read"] == 0
    assert dashboard(store)["summary"]["total_tokens"] == 220
    assert store.setting("projection_version") == projection.PROJECTION_VERSION
    assert store.setting("data_revision") == before + 1
    assert store.sources()[0]["status"] == "Offline"
    assert raw_facts(store) == facts
    assert not projection.ensure_projection(Store(store.directory))
    assert store.setting("data_revision") == before + 1
    assert {p.name: p.read_bytes() for p in offline.glob("*.jsonl")} == originals
    with store.connect() as db:
        assert json.loads(db.execute("SELECT diagnostic FROM canonical WHERE session_id='child'").fetchone()[0])["replay_tokens"] == 0
        db.execute("UPDATE sources SET enabled=0 WHERE id=?", (sid,))
    projection.rebuild_projection(store)
    assert dashboard(store)["summary"]["total_tokens"] == 0
    with store.connect() as db:
        db.execute("UPDATE sources SET enabled=1 WHERE id=?", (sid,))
    projection.rebuild_projection(store)
    assert dashboard(store)["summary"]["total_tokens"] == 220
    store.forget_source(sid)
    projection.rebuild_projection(store)
    assert dashboard(store)["summary"]["total_tokens"] == 0


def test_imported_facts_upgrade_even_when_snapshot_revision_is_unchanged(indexed, tmp_path):
    store, root, _ = indexed
    seed_family(store, root)
    snapshot = tmp_path / "portable.codex-insights"
    export_snapshot(store, snapshot)
    original_snapshot = snapshot.read_bytes()
    target = Store(tmp_path / "imported")
    import_snapshot(target, snapshot)
    facts = raw_facts(target)
    stale_projection(target)
    assert import_snapshot(Store(target.directory), snapshot)["status"] == "unchanged"
    assert dashboard(target)["summary"]["total_tokens"] == 220
    assert raw_facts(target) == facts
    assert snapshot.read_bytes() == original_snapshot
    assert next((target.directory / "imports").iterdir()).read_bytes() == original_snapshot


def test_upgrade_failure_rolls_back_records_diagnostics_version_and_revision(indexed, monkeypatch):
    store, root, _ = indexed
    seed_family(store, root)
    stale_projection(store)
    before = store.setting("data_revision")
    original = projection.project_segments

    def interrupted(store, db, segments):
        original(store, db, segments[:1])
        raise RuntimeError("Synthetic interrupted upgrade")

    with monkeypatch.context() as patch:
        patch.setattr(projection, "project_segments", interrupted)
        with pytest.raises(RuntimeError, match="interrupted upgrade"):
            projection.ensure_projection(store)
    assert store.setting("projection_version") is None
    assert store.setting("data_revision") == before
    assert dashboard(store)["summary"]["total_tokens"] == 110
    assert projection.ensure_projection(Store(store.directory))
    assert dashboard(store)["summary"]["total_tokens"] == 220
    assert store.setting("data_revision") == before + 1


class NoLiveProvider:
    def fetch(self, *_):
        raise AssertionError("No account request is permitted")

    def close(self):
        pass


def test_engine_upgrades_before_first_dashboard_response(indexed):
    store, root, _ = indexed
    seed_family(store, root)
    stale_projection(store)
    store.set_setting("live_usage_enabled", False)
    engine = Engine(store.directory, allowance_provider=NoLiveProvider())
    try:
        assert engine.call("dashboard")["summary"]["total_tokens"] == 220
        assert engine.call("widget_summary")["all_time"]["total_tokens"] == 220
    finally:
        engine.close()


def test_cli_report_upgrades_without_a_scan(indexed, tmp_path, monkeypatch):
    store, root, _ = indexed
    seed_family(store, root)
    stale_projection(store)
    store.set_setting("live_usage_enabled", False)
    captured = []
    monkeypatch.setattr(cli, "export_html", lambda data, *_: captured.append(data["summary"]["total_tokens"]))
    assert cli.main(["--data-dir", str(store.directory), "report", "--output", str(tmp_path / "report.html")]) == 0
    assert captured == [220]
    assert store.setting("projection_version") == projection.PROJECTION_VERSION


def test_deferred_gui_upgrade_keeps_dashboard_available_and_reports_progress(indexed, monkeypatch):
    from codex_insights import service
    store, root, _ = indexed
    seed_family(store, root)
    stale_projection(store)
    store.set_setting("live_usage_enabled", False)
    started, release = threading.Event(), threading.Event()
    original = service.ensure_projection

    def slow_upgrade(store, progress=None):
        started.set()
        assert release.wait(5)
        return original(store, progress)

    monkeypatch.setattr(service, "ensure_projection", slow_upgrade)
    engine = Engine(store.directory, allowance_provider=NoLiveProvider(), defer_projection=True)
    monkeypatch.setattr(engine, "configure_watchers", lambda: None)
    try:
        # CLI creates the native window before calling Engine.start on load.
        assert not started.is_set()
        assert store.setting("projection_version") is None
        engine.start()
        assert started.wait(2)
        initial = engine.call("dashboard")
        assert initial["summary"]["total_tokens"] == 110
        assert initial["job"]["running"]
        assert initial["job"]["message"] == "Updating usage index"
        release.set()
        engine.executor.submit(lambda: None).result(timeout=5)
        assert engine.call("dashboard")["summary"]["total_tokens"] == 220
        assert store.setting("projection_version") == projection.PROJECTION_VERSION
        assert any(item["state"] == "completed" for item in engine.jobs.snapshot()["completed"])
    finally:
        release.set()
        engine.close()
