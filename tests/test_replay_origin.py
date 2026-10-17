"""Replay exclusion needs event-origin evidence as well as equal counters."""
from copy import deepcopy
from datetime import timedelta

import pytest

from codex_insights.accounting.token_reconciliation import (
    _aligned_prefix_match, reconcile_sessions, reconciliation_quality,
)
from codex_insights.codec import unpack
from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import T, event, log, token, usage


def trace(n=100, seconds=3, last=None, model="gpt-5.3-codex"):
    return {
        "timestamp": T + timedelta(seconds=seconds) if seconds is not None else None,
        "cumulative_usage": usage(n),
        "last_usage": usage(n if last is None else last),
        "model": model,
    }


def family(child_trace, parent_trace=None, spawn=5):
    parent = {"id": "parent", "raw_token_trace": parent_trace or [trace()]}
    child = {
        "id": "child", "parent_session_id": "parent",
        "session_source": "spawned_subagent",
        "spawn_timestamp": T + timedelta(seconds=spawn) if spawn is not None else None,
        "raw_token_trace": child_trace,
    }
    return [parent, child]


def reconcile(sessions):
    reconcile_sessions(sessions, {s["id"]: s for s in sessions}, T, T + timedelta(days=1))
    return reconciliation_quality(sessions)


@pytest.mark.parametrize("model", ["gpt-5.3-codex", "different-child-model"])
def test_equal_post_spawn_response_is_independent(model):
    sessions = family([trace(seconds=6, model=model)])
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 220
    assert quality["verified_replay_usage"]["total_tokens"] == 0
    assert sessions[1]["token_reconciliation_method"] == "child_local_counter"
    assert sessions[1]["token_slices"][0]["model"] == model


@pytest.mark.parametrize("seconds", [4, 5, 6])
def test_counter_match_without_preserved_timestamp_is_not_replay(seconds):
    sessions = family([trace(200, seconds=seconds, last=100)], [trace(200, last=100)])
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 220
    assert quality["verified_replay_usage"]["total_tokens"] == 0
    assert quality["unresolved_spawned_sessions"] == 1
    assert quality["confidence"] == "low"


@pytest.mark.parametrize("offset", [0, 1])
def test_preserved_pre_spawn_prefix_still_deduplicates(offset):
    parent_trace = [trace(), trace(150, seconds=4, last=50)]
    sessions = family(deepcopy(parent_trace[offset:]) + [trace(175, seconds=6, last=25)], parent_trace)
    quality = reconcile(sessions)
    child = sessions[1]
    assert quality["adjusted_usage"]["total_tokens"] == 192
    assert child["token_usage"]["total_tokens"] == 27
    assert child["verified_replay_prefix_events"] == 2 - offset
    assert child["replay_alignment_parent_index"] == offset
    assert child["token_reconciliation_confidence"] == "verified"
    assert quality["component_reconciled"]


def test_independent_event_ends_verified_prefix_even_if_counters_continue_matching():
    parent_trace = [trace(), trace(150, seconds=4, last=50)]
    sessions = family([trace(), trace(150, seconds=6, last=50)], parent_trace)
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 220
    assert sessions[1]["verified_replay_prefix_events"] == 1
    assert sessions[1]["token_usage"]["total_tokens"] == 55


@pytest.mark.parametrize("parent_time,child_time,spawn", [
    (None, 3, 5), (3, None, 5), (None, None, 5), (3, 3, None), (6, 6, 5),
])
def test_missing_or_post_spawn_origin_cannot_verify(parent_time, child_time, spawn):
    sessions = family([trace(seconds=child_time)], [trace(seconds=parent_time)], spawn)
    assert _aligned_prefix_match(
        sessions[1]["raw_token_trace"], sessions[0]["raw_token_trace"],
        spawn_timestamp=sessions[1]["spawn_timestamp"],
    ) == (0, None)


def test_missing_spawn_retains_uncertainty_and_counts():
    sessions = family([trace()], spawn=None)
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 220
    assert quality["unresolved_spawned_sessions"] == 1


@pytest.mark.parametrize("inherited", [False, True])
def test_late_parent_reconciles_only_preserved_history(inherited):
    parent, child = family([trace(seconds=3 if inherited else 6)])
    quality = reconcile([child])
    assert quality["adjusted_usage"]["total_tokens"] == 110
    assert quality["missing_parent_sessions"] == 1
    quality = reconcile([parent, child])
    assert quality["adjusted_usage"]["total_tokens"] == (110 if inherited else 220)
    assert quality["verified_replay_usage"]["total_tokens"] == (110 if inherited else 0)


def test_counter_reset_after_inherited_prefix_keeps_response():
    sessions = family([trace(), trace(20, seconds=6), trace(40, seconds=7, last=20)])
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 154
    assert sessions[1]["accounting_adjustments"]["counter_regressions"] == 1


def test_startup_baseline_keeps_first_response():
    sessions = family([trace(200_100, seconds=5, last=100)])
    quality = reconcile(sessions)
    assert quality["adjusted_usage"]["total_tokens"] == 220
    assert quality["inferred_startup_sessions"] == 1
    assert quality["excluded_replay_usage"]["total_tokens"] == 0


@pytest.mark.parametrize("valid", [False, True])
def test_explicit_portable_boundary_remains_authoritative(valid):
    parent, child = family([trace(150, seconds=6, last=50)])
    parent.update(record_boundaries=[[100, 0]], boundaries=[
        {"end_byte_offset": 100, "usage": usage(100)},
    ])
    child["history_base"] = {
        "thread_id": "parent", "end_byte_offset": 100 if valid else 99,
        "end_ordinal_exclusive": 1,
    }
    quality = reconcile([parent, child])
    assert quality["adjusted_usage"]["total_tokens"] == 165
    assert child["token_reconciliation_confidence"] == ("verified" if valid else "unreconciled")
    assert quality["unresolved_history_boundaries"] == (0 if valid else 1)


@pytest.mark.parametrize("inherited", [False, True])
def test_imported_portable_facts_repair_stale_projection_without_logs(indexed, tmp_path, inherited):
    store, root, _ = indexed
    parent_bytes = log("parent") + token(100)
    child_bytes = (
        event("session_meta", {"id": "child", "source": "cli", "forked_from_id": "parent"}, 5)
        + event("turn_context", {"model": "gpt-5.3-codex"}, 5)
        + token(100, 3 if inherited else 6)
    )
    (root / "parent.jsonl").write_bytes(parent_bytes)
    (root / "child.jsonl").write_bytes(child_bytes)
    refresh(store)
    snapshot = tmp_path / "portable.codex-insights"
    export_snapshot(store, snapshot)
    imported = Store(tmp_path / "imported")
    import_snapshot(imported, snapshot)
    expected = 110 if inherited else 220
    assert dashboard(imported)["summary"]["total_tokens"] == expected
    with imported.connect() as db:
        facts_before = [row[0] for row in db.execute("SELECT fact FROM canonical ORDER BY session_id")]
        assert all("_physical_path" not in unpack(fact) for fact in facts_before)
        # Simulate the old cached undercount; portable facts remain authoritative.
        db.execute("DELETE FROM records WHERE session_id='child' AND kind='usage'")
        db.execute("DELETE FROM metric_buckets")
    imported.set_setting("bucket_version", None)
    assert dashboard(imported)["summary"]["total_tokens"] == 110
    rebuild_projection(imported)
    assert dashboard(imported)["summary"]["total_tokens"] == expected
    with imported.connect() as db:
        assert facts_before == [row[0] for row in db.execute("SELECT fact FROM canonical ORDER BY session_id")]
        replay = db.execute("SELECT diagnostic FROM canonical WHERE session_id='child'").fetchone()[0]
        assert ('"replay_tokens": 110' if inherited else '"replay_tokens": 0') in replay
    assert (root / "parent.jsonl").read_bytes() == parent_bytes
    assert (root / "child.jsonl").read_bytes() == child_bytes
