from datetime import datetime, timezone

import pytest

from codex_insights.ingestion import refresh
from codex_insights.local_token_burn import LocalTokenBurn
from conftest import T, log, token


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def scanned(store, at):
    with store.connect() as db:
        db.execute("UPDATE sources SET updated=?,status='Ready' WHERE kind='folder'", (stamp(at),))
        db.execute("INSERT OR REPLACE INTO index_health SELECT id,?,?,NULL FROM sources WHERE kind='folder'", (at, at))


def record(store, source, identifier, at, total, kind="usage"):
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO records(event_id,source_id,kind,ts,total) VALUES(?,?,?,?,?)",
                   (identifier, source, kind, stamp(at), total))
    store.set_setting("data_revision", store.setting("data_revision", 0) + 1)


@pytest.fixture
def local(indexed):
    store, root, source = indexed
    clock = [T.timestamp() + 600]
    return LocalTokenBurn(store, clock=lambda: clock[0]), store, root, source, clock


def test_event_times_define_exact_five_minute_window_and_include_idle_time(local):
    rate, store, _, source, clock = local
    now = clock[0]
    for identifier, age, total in (("cutoff", 300, 50000), ("first", 299, 6000),
                                  ("second", 120, 9000), ("latest", 0, 1000),
                                  ("future", -5, 99999)):
        record(store, source, identifier, now - age, total)
    record(store, source, "not-usage", now, 99999, "activity")
    scanned(store, now)
    assert rate.read() == {"value": 3200, "status": "available", "observed_seconds": 300, "updated_at": now,
        "coverage": {"state": "complete", "checked_at": now, "reasons": [], "historical_pending_files": 0, "live_pending_files": 0},
        "indexing": {"live_checked_at": now, "historical_pending_files": 0, "live_pending_files": 0}}


def test_first_scan_is_immediately_available_and_unchanged_reads_do_not_sample(local):
    rate, store, _, _, clock = local
    assert rate.read()["status"] == "collecting"
    scanned(store, clock[0])
    expected = rate.read()
    assert expected["value"] == 0 and expected["observed_seconds"] == 300
    for _ in range(20):
        assert rate.read() == expected


def test_idle_events_age_out_without_new_tokens(local):
    rate, store, _, source, clock = local
    record(store, source, "burst", clock[0] - 240, 30000)
    scanned(store, clock[0])
    assert rate.read()["value"] == 6000
    clock[0] += 59
    assert rate.read()["value"] == 6000
    clock[0] += 1
    assert rate.read()["value"] == 0


def test_backfill_and_reindex_use_event_time_and_reconciled_value(local):
    rate, store, _, source, clock = local
    scanned(store, clock[0])
    record(store, source, "recent", clock[0] - 30, 5000)
    assert rate.read()["value"] == 1000
    record(store, source, "old-batch", clock[0] - 1800, 60000)
    assert rate.read()["value"] == 1000
    record(store, source, "recent", clock[0] - 30, 2500)
    assert rate.read()["value"] == 500


def test_only_enabled_local_sources_contribute_and_imports_do_not(local):
    rate, store, root, source, clock = local
    disabled = store.add_source(root / "disabled")
    with store.connect() as db:
        db.execute("INSERT INTO sources(id,label,kind) VALUES('remote','Imported','snapshot')")
        db.execute("UPDATE sources SET enabled=0 WHERE id=?", (disabled,))
    for sid in (source, disabled, "remote"):
        record(store, sid, sid, clock[0] - 20, 5000)
    scanned(store, clock[0])
    assert rate.read()["value"] == 1000
    with store.connect() as db:
        db.execute("UPDATE sources SET enabled=0 WHERE id=?", (source,))
    assert rate.read()["status"] == "unavailable"
    with store.connect() as db:
        db.execute("UPDATE sources SET enabled=1 WHERE id=?", (disabled,))
    assert rate.read()["value"] == 1000


@pytest.mark.parametrize("failure", ["offline", "long-gap", "clock-reversal"])
def test_index_failures_preserve_last_estimate_as_stale_and_recovery_uses_current_window(local, failure):
    rate, store, _, source, clock = local
    record(store, source, "usage", clock[0] - 10, 5000)
    scanned(store, clock[0])
    expected = rate.read()
    if failure == "long-gap":
        clock[0] += 601
    elif failure == "clock-reversal":
        clock[0] -= 60
    else:
        with store.connect() as db:
            db.execute("UPDATE sources SET status='Offline'")
    result = rate.read()
    assert result.pop("detail")
    assert result.pop('partial')
    coverage = result.pop('coverage')
    assert coverage['state'] == 'partial'
    assert coverage['reasons'][0]['code'] == ('source_offline' if failure == 'offline' else 'indexing_delayed')
    expected.pop('coverage')
    assert result == {**expected, "status": "stale"}
    clock[0] = expected["updated_at"] + 700
    with store.connect() as db:
        db.execute("DELETE FROM file_failures")
    scanned(store, clock[0])
    assert rate.read()["value"] == 0 and rate.read()["status"] == "available"


def test_offline_before_first_read_is_unavailable_and_missing_index_is_collecting(local):
    rate, store, _, _, _ = local
    assert rate.read()["status"] == "collecting"
    with store.connect() as db:
        db.execute("UPDATE sources SET status='Offline'")
    assert rate.read()["status"] == "unavailable"
    assert rate.read()["value"] is None


def test_never_indexed_missing_optional_folder_does_not_block_local_usage(local):
    rate, store, root, source, clock = local
    record(store, source, "local", clock[0] - 20, 5000)
    scanned(store, clock[0])
    missing = store.add_source(root / "missing-archive")
    with store.connect() as db:
        db.execute("UPDATE sources SET status='Offline' WHERE id=?", (missing,))
    assert rate.read()["value"] == 1000


def test_successful_subsecond_index_timestamp_is_fresh(local):
    rate, store, _, _, clock = local
    clock[0] += .8
    scanned(store, clock[0] - .1)
    assert rate.read()["status"] == "available"


def test_reconciled_duplicate_logs_append_and_restart_need_no_counter_warmup(local):
    rate, store, root, source, clock = local
    content = log() + token(1000, 290) + token(2000, 350) + token(6000, 550)
    (root / "chat.jsonl").write_bytes(content)
    duplicate = root / "duplicate"
    duplicate.mkdir()
    (duplicate / "copy.jsonl").write_bytes(content)
    refresh(store)
    scanned(store, clock[0])
    assert rate.read()["value"] == 1100  # Only the 5,500 new tokens since the cutoff.
    with (root / "chat.jsonl").open("ab") as stream:
        stream.write(token(7000, 590))
    refresh(store)
    scanned(store, clock[0])
    assert rate.read()["value"] == 1320
    assert LocalTokenBurn(store, clock=lambda: clock[0]).read() == rate.read()


def test_demo_and_exporter_do_not_read_live_rates(local):
    _, store, _, _, _ = local
    assert LocalTokenBurn(store, allowed=False).read()["status"] == "unavailable"


def test_failed_historical_file_does_not_hide_rate_after_restart(local):
    rate, store, _, source, clock = local
    record(store, source, "recent", clock[0] - 20, 5000)
    scanned(store, clock[0])
    with store.connect() as db:
        db.execute("INSERT INTO file_failures(source_id,path) VALUES(?,'old-session.jsonl')", (source,))
    for reader in (rate, LocalTokenBurn(store, clock=lambda: clock[0])):
        result = reader.read()
        assert result["value"] == 1000 and result["status"] == "available"
        assert result["partial"] and "may be incomplete" in result["detail"]
    record(store, source, "recent", clock[0] - 20, 10000)
    assert rate.read()["value"] == 2000
    with store.connect() as db:
        db.execute("DELETE FROM file_failures")
    assert "partial" not in rate.read() and "detail" not in rate.read()


def test_long_scan_exposes_recent_indexed_events_as_partial_but_never_invents_idle_zero(local):
    rate, store, _, source, clock = local
    scanned(store, clock[0] - 1200)
    assert rate.read()["status"] == "collecting"
    assert "fresh local scan" in rate.read()["detail"]
    record(store, source, "recent", clock[0] - 20, 5000)
    result = rate.read()
    assert result["value"] == 1000 and result["partial"]
    clock[0] += 301
    result = rate.read()
    assert result["value"] == 1000 and result["status"] == "stale"
    scanned(store, clock[0])
    assert rate.read()["value"] == 0 and "partial" not in rate.read()


def test_one_fresh_source_can_report_partial_zero_despite_stale_failed_archive(local):
    rate, store, root, source, clock = local
    scanned(store, clock[0])
    archived = store.add_source(root / "archived")
    with store.connect() as db:
        db.execute("UPDATE sources SET updated=? WHERE id=?", (stamp(clock[0] - 1200), archived))
        db.execute("INSERT INTO file_failures(source_id,path) VALUES(?,'old-session.jsonl')", (archived,))
    result = rate.read()
    assert result["value"] == 0 and result["status"] == "available" and result["partial"]
    record(store, source, "recent", clock[0] - 20, 5000)
    assert rate.read()["value"] == 1000
