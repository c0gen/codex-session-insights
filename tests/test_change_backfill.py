import json
import sqlite3
import threading

import pytest

from codex_insights import ingestion
from codex_insights.codec import pack, unpack
from codex_insights.parser import PARSER_VERSION, SessionParser, portable_fact
from codex_insights.projection import project_segments
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import event, log, token
from test_structured_changes import call, completion, output


def content(sid="chat", parent=None):
    return (log(sid, parent) + token(100) + event("response_item", call(), 10)
            + event("event_msg", completion(), 11) + event("response_item", output(), 12))


def make_old_index(store):
    """Simulate persisted v1 facts/checkpoints without touching session files."""
    with store.connect() as db:
        db.execute("UPDATE files SET parser_version=1")
        for row in db.execute("SELECT * FROM candidates").fetchall():
            fact = unpack(row["fact"])
            for edit in fact["change_events"]:
                edit["outcome"] = "unknown"
                edit.pop("resolved_at", None)
            store.put_candidate(db, row["source_id"], fact, 1)
            store.choose_canonical(db, fact["segment_id"])
            project_segments(store, db, [fact["segment_id"]])


def test_unchanged_files_backfill_once_with_identical_tokens_cost_and_buckets(indexed):
    store, root, _ = indexed
    path = root / "chat.jsonl"
    path.write_bytes(content())
    ingestion.refresh(store)
    make_old_index(store)
    before = dashboard(store)["summary"]
    stat = path.stat()
    assert before["lines_added"] == 0
    report = ingestion.refresh(store)
    after = dashboard(store)
    assert report["bytes_read"] == len(content())
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert (after["summary"]["lines_added"], after["summary"]["lines_removed"]) == (2, 1)
    for field in ("total_tokens", "input_tokens", "cached_tokens", "output_tokens", "cost", "prompts"):
        assert before[field] == after["summary"][field]
    assert sum(day["lines"] for day in after["timeline"]) == 3
    with store.connect() as db:
        assert tuple(db.execute("SELECT sum(added),sum(removed) FROM records").fetchone()) == (2, 1)
        assert tuple(db.execute("SELECT sum(added),sum(removed) FROM metric_buckets").fetchone()) == (2, 1)
        assert db.execute("SELECT parser_version FROM files").fetchone()[0] == PARSER_VERSION
    assert ingestion.refresh(store)["bytes_read"] == 0


def test_schema_migration_is_idempotent_and_preserves_existing_rows(tmp_path):
    folder = tmp_path / "database"
    folder.mkdir()
    db = sqlite3.connect(folder / "insights.sqlite3")
    db.execute("CREATE TABLE files(source_id TEXT,path TEXT,offset INTEGER,mtime INTEGER,size INTEGER,anchor TEXT,state BLOB,PRIMARY KEY(source_id,path))")
    db.execute("INSERT INTO files VALUES('source','file',4,3,4,'anchor',?)", (pack({"version": 1}),))
    db.execute("CREATE TABLE candidates(source_id TEXT,segment_id TEXT,session_id TEXT,parent_id TEXT,record_count INTEGER,trace_count INTEGER,byte_count INTEGER,prefix_hash TEXT,fact BLOB,PRIMARY KEY(source_id,segment_id))")
    db.commit(); db.close()
    Store(folder)
    store = Store(folder)
    with store.connect() as db:
        row = db.execute("SELECT * FROM files").fetchone()
        assert row["offset"] == 4 and row["parser_version"] == 0
        assert unpack(row["state"]) == {"version": 1}
        assert sum(r["name"] == "parser_version" for r in db.execute("PRAGMA table_info(files)")) == 1


def test_cancelled_backfill_resumes_remaining_files(indexed):
    store, root, _ = indexed
    (root / "a.jsonl").write_bytes(content("a"))
    (root / "b.jsonl").write_bytes(content("b").replace(b"call-1", b"call-2").replace(b"edit-1", b"edit-2"))
    ingestion.refresh(store); make_old_index(store)
    cancel = threading.Event()
    def progress(report):
        if report["files"] == 2:
            cancel.set()
    report = ingestion.refresh(store, progress=progress, cancel=cancel)
    assert report["cancelled"] and report["changed_files"] == 1
    assert dashboard(store)["summary"]["lines_added"] == 2
    report = ingestion.refresh(Store(store.directory))
    assert report["changed_files"] == 1
    assert dashboard(store)["summary"]["lines_added"] == 4
    assert ingestion.refresh(store)["bytes_read"] == 0


def test_restart_finishes_queued_projection_without_rereading(indexed, monkeypatch):
    store, root, _ = indexed
    (root / "chat.jsonl").write_bytes(content())
    from codex_insights import index_file
    original = index_file.project_segments
    def interrupted(*args):
        raise RuntimeError("Simulated process interruption")
    monkeypatch.setattr(index_file, "project_segments", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        ingestion.refresh(store)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM projection_queue").fetchone()[0] == 1
    monkeypatch.setattr(index_file, "project_segments", original)
    assert ingestion.refresh(Store(store.directory))["bytes_read"] == 0
    assert dashboard(store)["summary"]["lines_added"] == 2
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM projection_queue").fetchone()[0] == 0


def test_delayed_completion_filters_and_snapshot_round_trip(indexed, tmp_path):
    store, root, _ = indexed
    path = root / "chat.jsonl"
    path.write_bytes(log() + token(100) + event("response_item", call(), 10))
    ingestion.refresh(store)
    with path.open("ab") as stream:
        stream.write(event("event_msg", completion(), 86400))
    ingestion.refresh(store)
    assert dashboard(store, {"model": "gpt-5.3-codex"})["summary"]["lines_added"] == 2
    previous = dashboard(store, {"range": "custom", "start": "2026-10-01", "end": "2026-10-01"})
    assert previous["summary"]["lines_added"] == 0
    assert previous["summary"]["change_coverage"] == "partial"
    snapshot = tmp_path / "edits.codex-insights"
    export_snapshot(store, snapshot)
    imported = Store(tmp_path / "imported")
    import_snapshot(imported, snapshot)
    assert dashboard(imported)["summary"]["lines_added"] == 2
    assert ingestion.refresh(imported)["bytes_read"] == 0
    assert dashboard(imported)["summary"]["lines_added"] == 2


def test_copied_history_and_offline_source_keep_counts(indexed):
    store, root, sid = indexed
    parent = content("parent")
    child = log("child", "parent")
    # Child metadata is later, while inherited records keep original timestamps.
    first, *rest = child.splitlines(keepends=True)
    meta = json.loads(first)
    meta["timestamp"] = "2026-10-01T14:01:00+00:00"
    inherited = parent.splitlines(keepends=True)[1:]
    (root / "parent.jsonl").write_bytes(parent)
    (root / "child.jsonl").write_bytes((json.dumps(meta) + "\n").encode() + b"".join(inherited))
    ingestion.refresh(store)
    assert dashboard(store)["summary"]["lines_added"] == 2
    with store.connect() as db:
        db.execute("UPDATE sources SET root=? WHERE id=?", (str(root / "unplugged"), sid))
        db.execute("UPDATE files SET parser_version=1")
    ingestion.refresh(store)
    assert dashboard(store)["summary"]["lines_added"] == 2
    assert store.sources()[0]["status"] == "Offline"


def test_reparsed_copy_wins_over_equal_stale_import(indexed):
    store, root, _ = indexed
    (root / "chat.jsonl").write_bytes(content())
    ingestion.refresh(store); make_old_index(store)
    with store.connect() as db:
        fact = unpack(db.execute("SELECT fact FROM canonical").fetchone()[0])
        db.execute("INSERT INTO sources(id,label,kind) VALUES('000-old-import','Old snapshot','import')")
        store.put_candidate(db, "000-old-import", fact)
        store.choose_canonical(db, fact["segment_id"])
    ingestion.refresh(store)
    assert dashboard(store)["summary"]["lines_added"] == 2
