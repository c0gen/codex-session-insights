import json
import threading
import time

import pytest

from codex_insights import project_groups as groups
from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.service import Engine
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import log, token


def add_chat(root, name, sid, n=100):
    (root / (sid + ".jsonl")).write_bytes(log(sid).replace(b"C:/private/work/project", ("C:/work/" + name).encode()) + token(n))


def projects(store):
    return {p["name"]: p["id"] for p in dashboard(store)["options"]["projects"]}


def metric_rows(store):
    with store.connect() as db:
        return {table: [tuple(r) for r in db.execute("SELECT * FROM " + table + " ORDER BY segment_id,ts")]
                for table in ("records", "metric_buckets")}


@pytest.fixture
def grouped(indexed):
    store, root, _ = indexed
    for i, name in enumerate(("alpha", "beta", "gamma", "delta")):
        add_chat(root, name, name, (i + 1) * 100)
    refresh(store)
    return store, root, projects(store)


def test_bulk_selected_destination_totals_and_no_metric_writes(grouped, monkeypatch):
    store, _, ids = grouped
    before = dashboard(store)
    records = metric_rows(store)
    # Merge cannot depend on fact decoding, logs or any projection machinery.
    monkeypatch.setattr(groups, "unpack", lambda _: pytest.fail("Merge decoded a fact"))
    result = groups.merge_projects(store, [ids["alpha"], ids["beta"], ids["gamma"]], ids["beta"])
    after = dashboard(store)
    assert result["sessions"] == 2 and result["identities"] == 2
    assert result["target"]["name"] == "beta" and len(result["sources"]) == 2
    assert after["summary"] == before["summary"]
    assert len(after["projects"]) == 2
    assert metric_rows(store) == records
    assert dashboard(store, {"project_id": ids["alpha"]})["summary"]["total_tokens"] == 660
    assert dashboard(store, {"project_id": ids["beta"], "model": "gpt-5.3-codex"})["summary"]["chats"] == 3


def test_chained_groups_one_level_undo_and_restart_after_new_activity(grouped):
    store, root, ids = grouped
    first = groups.merge_projects(store, [ids["alpha"]], ids["beta"])
    second = groups.merge_projects(store, [ids["beta"]], ids["gamma"])
    add_chat(root, "alpha", "new-alpha", 500)
    add_chat(root, "beta", "new-beta", 600)
    add_chat(root, "gamma", "new-target", 700)
    refresh(store)
    records = metric_rows(store)
    store = Store(store.directory)
    with pytest.raises(ValueError, match="latest"):
        groups.undo_project_merge(store, first["operation_id"])
    groups.undo_project_merge(store, second["operation_id"])
    assert metric_rows(store) == records
    assert dashboard(store, {"project_id": ids["beta"]})["summary"]["total_tokens"] == 1540
    assert dashboard(store, {"project_id": ids["gamma"]})["summary"]["total_tokens"] == 1100
    assert projects(store) == {k: v for k, v in ids.items() if k != "alpha"}
    assert store.setting("last_project_merge") is None
    with pytest.raises(ValueError, match="latest"):
        groups.undo_project_merge(store, second["operation_id"])


def test_atomic_rollback_invalid_destination_and_cycles(grouped, monkeypatch):
    store, _, ids = grouped
    before = projects(store), metric_rows(store), store.setting("project_aliases", {})
    with pytest.raises(ValueError, match="Destination"):
        groups.merge_projects(store, [ids["alpha"]], "gone")
    with pytest.raises(ValueError, match="source"):
        groups.merge_projects(store, ["gone"], ids["beta"])
    monkeypatch.setattr(groups, "sync_aliases", lambda _: (_ for _ in ()).throw(RuntimeError("simulated write failure")))
    with pytest.raises(RuntimeError):
        groups.merge_projects(store, [ids["alpha"], ids["gamma"]], ids["beta"])
    assert (projects(store), metric_rows(store), store.setting("project_aliases", {})) == before
    assert store.setting("last_project_merge") is None
    store.set_setting("project_aliases", {ids["alpha"]: {"id": ids["beta"], "name": "beta"}, ids["beta"]: {"id": ids["alpha"], "name": "alpha"}})
    with pytest.raises(ValueError, match="cycle"):
        groups.merge_projects(store, [ids["alpha"]], ids["gamma"])


def test_legacy_migration_restart_never_changes_metrics_or_reads_logs(grouped):
    store, root, ids = grouped
    # Emulate the previous alias implementation, including aliased metric IDs.
    store.set_setting("project_aliases", {ids["alpha"]: {"id": ids["beta"], "name": "beta"}})
    with store.connect() as db:
        for table in ("canonical", "records", "metric_buckets"):
            db.execute(f"UPDATE {table} SET project_id=? WHERE project_id=?", (ids["beta"], ids["alpha"]))
        db.execute("UPDATE canonical SET project_label='beta' WHERE project_id=?", (ids["beta"],))
        db.execute("DELETE FROM session_projects")
        db.execute("DELETE FROM project_memberships")
        db.execute("DELETE FROM settings WHERE key IN ('project_groups_seeded','project_groups_version')")
    store = Store(store.directory)
    records = metric_rows(store)
    cancelled = threading.Event()
    result = groups.migrate(store, lambda _: cancelled.set(), cancelled, batch_size=1)
    assert result == {"sessions": 1, "status": "cancelled"}
    assert store.setting("project_groups_version") is None
    with pytest.raises(ValueError, match="migration"):
        groups.merge_projects(store, [ids["beta"]], ids["gamma"])
    store = Store(store.directory)
    # No source access is needed after the persisted facts have been accepted.
    for path in root.glob("*.jsonl"):
        path.unlink()
    assert groups.migrate(store, batch_size=1)["sessions"] == 3
    assert metric_rows(store) == records
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM session_projects WHERE original_project_id=?", (ids["alpha"],)).fetchone()[0] == 1
    assert dashboard(store, {"project_id": ids["beta"]})["summary"]["total_tokens"] == 330
    result = groups.merge_projects(store, [ids["beta"]], ids["gamma"])
    groups.undo_project_merge(store, result["operation_id"])
    assert dashboard(store, {"project_id": ids["beta"]})["summary"]["chats"] == 2


def test_membership_persists_through_import_and_both_rebuilds(grouped, tmp_path):
    store, root, ids = grouped
    result = groups.merge_projects(store, [ids["alpha"]], ids["beta"])
    other = Store(tmp_path / "other")
    folder = tmp_path / "other-chats"
    folder.mkdir()
    other.add_source(folder)
    add_chat(folder, "alpha", "imported-alpha", 800)
    refresh(other)
    snapshot = tmp_path / "usage.codex-insights"
    export_snapshot(other, snapshot)
    import_snapshot(store, snapshot)
    before = dashboard(store)["summary"]
    rebuild_projection(store)
    refresh(store, rebuild=True)
    assert dashboard(store)["summary"] == before
    assert dashboard(store, {"project_id": ids["beta"]})["summary"]["chats"] == 3
    groups.undo_project_merge(store, result["operation_id"])
    assert dashboard(store, {"project_id": ids["alpha"]})["summary"]["chats"] == 2


def test_dashboard_snapshot_remains_consistent_when_merge_completes_mid_query(grouped, monkeypatch):
    from codex_insights import queries
    store, _, ids = grouped
    before_revision = store.setting("data_revision", 0)
    summary = queries.query_summary
    def merge_during_query(*args):
        value = summary(*args)
        groups.merge_projects(store, [ids["alpha"]], ids["beta"])
        return value
    monkeypatch.setattr(queries, "query_summary", merge_during_query)
    snapshot = queries.dashboard(store, {"project_id": ids["alpha"]})
    assert snapshot["summary"]["total_tokens"] == 110
    assert snapshot["projects"][0]["name"] == "alpha"
    assert snapshot["revision"] == before_revision and snapshot["project_merge"] is None
    monkeypatch.setattr(queries, "query_summary", summary)
    assert queries.dashboard(store, {"project_id": ids["alpha"]})["summary"]["total_tokens"] == 330


def wait_job(engine, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        completion = next((c for c in engine.call("status")["completed"] if c["id"] == job_id), None)
        if completion:
            return completion
        time.sleep(.01)
    pytest.fail("Job did not finish")


def test_queued_api_coalesces_and_validates_at_execution(grouped):
    store, _, ids = grouped
    engine = Engine(store.directory, exporter=True)
    entered, release = threading.Event(), threading.Event()
    def work():
        entered.set()
        release.wait(3)
    try:
        engine.submit("Busy", work)
        assert entered.wait(1)
        args = {"sources": [ids["alpha"], ids["gamma"]], "target": ids["beta"]}
        response = engine.call("merge_projects", args)
        assert response["status"] == "queued"
        assert engine.call("merge_projects", args)["job_id"] == response["job_id"]
        # Remove the destination while the operation is waiting in the queue.
        with store.connect() as db:
            db.execute("DELETE FROM canonical WHERE project_id=?", (ids["beta"],))
        release.set()
        assert wait_job(engine, response["job_id"])["state"] == "failed"
        alias = engine.call("alias", {"source": ids["alpha"], "target": ids["delta"]})
        finished = wait_job(engine, alias["job_id"])
        assert finished["state"] == "completed" and finished["result"]["operation_id"]
        undo = engine.call("undo_project_merge", {"operation_id": finished["result"]["operation_id"]})
        assert wait_job(engine, undo["job_id"])["result"]["undone"]
    finally:
        release.set()
        engine.close()


def test_metadata_merge_10000_sessions_under_one_second(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.executemany("INSERT INTO project_memberships VALUES(?,?,?)", [(str(i), f"Project {i}", str(i)) for i in range(100)])
        db.executemany("INSERT INTO canonical(segment_id,project_id,project_label) VALUES(?,?,?)",
                       [(str(i), str(i % 100), f"Project {i % 100}") for i in range(10000)])
        db.executemany("INSERT INTO session_projects VALUES(?,?)", [(str(i), str(i % 100)) for i in range(10000)])
        db.executemany("INSERT INTO records(event_id,segment_id,session_id,project_id,kind,ts,total) VALUES(?,?,?,?,?,?,?)",
                       [(str(i), str(i), str(i), str(i % 100), 'usage', '2026-10-01T12:00:00+00:00', 100) for i in range(10000)])
        from codex_insights.buckets import SELECT, GROUP
        db.execute('INSERT INTO metric_buckets SELECT ' + SELECT + ' FROM records GROUP BY ' + GROUP)
        # Triggers would abort the operation if it tried to touch metric records.
        for table in ("records", "metric_buckets"):
            for action in ("INSERT", "UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER protect_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Metric write during merge'); END")
    started = time.perf_counter()
    result = groups.merge_projects(store, [str(i) for i in range(99)], "99")
    elapsed = time.perf_counter() - started
    print(f"Metadata merge: 10,000 sessions / 100 projects in {elapsed:.4f}s")
    assert elapsed < 1
    assert result["sessions"] == 9900 and result["identities"] == 99
