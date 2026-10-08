#!/usr/bin/env python3
"""Parent/child token-trace reconciliation.

Spawned Codex session logs can inherit cumulative token snapshots from their
parent. Exact component-for-component matches are verified against any
pre-spawn position in the parent trace. When an exact alignment is unavailable,
response accounting removes initial baselines without discarding the first
response. Paginated sources can name a verified physical history boundary.
"""
from __future__ import annotations

from collections import defaultdict
from .history_boundary import resolve_history_seed


from .token_accounting import (
    TOKEN_USAGE_KEYS, TokenUsageAccumulator, empty_usage, normalize_usage,
    add_usage, subtract_usage, usage_signature,
)

INFERRED_BASELINE_MIN_TOKENS = 100_000
INFERRED_BASELINE_MIN_SHARE = 0.90
SPAWN_TIMESTAMP_TOLERANCE_SECONDS = 1.0


def build_lineage_index(entries):
    """Index complete cached session facts before report scoping/windowing."""
    index = {}
    for _path, payload in entries:
        for session in payload.get("sessions", []):
            session_id = str(session.get("id") or "")
            if session_id:
                if len(session.get("raw_token_trace") or []) >= len(index.get(session_id, {}).get("raw_token_trace") or []):
                    session["_physical_path"] = str(_path)
                    index[session_id] = session
    return index


def _event_in_window(timestamp, start, end):
    return bool(timestamp and start <= timestamp < end)


def _trace_before_spawn(parent, child):
    trace = parent.get("raw_token_trace") or []
    spawn_timestamp = child.get("spawn_timestamp")
    if spawn_timestamp is None:
        child_trace = child.get("raw_token_trace") or []
        spawn_timestamp = next(
            (item.get("timestamp") for item in child_trace if item.get("timestamp")),
            None,
        )
    if spawn_timestamp is None:
        return trace
    return [
        item
        for item in trace
        if item.get("timestamp") is not None and item["timestamp"] <= spawn_timestamp
    ]


def _trace_signatures(trace):
    return [(usage_signature(item.get("cumulative_usage")), usage_signature(item.get("last_usage"))) for item in trace]


def _signature_positions(signatures):
    positions = defaultdict(list)
    for index, signature in enumerate(signatures):
        positions[signature].append(index)
    return positions


def _event_is_pre_spawn(item, spawn_timestamp):
    if spawn_timestamp is None:
        return True
    timestamp = item.get("timestamp")
    return timestamp is not None and timestamp <= spawn_timestamp


def _aligned_prefix_match(
    child_trace,
    parent_trace,
    parent_signatures=None,
    parent_positions=None,
    spawn_timestamp=None,
):
    """Return the longest child-prefix match at any eligible parent offset."""
    if not child_trace or not parent_trace:
        return 0, None

    child_signatures = _trace_signatures(child_trace)
    parent_signatures = parent_signatures or _trace_signatures(parent_trace)
    parent_positions = parent_positions or _signature_positions(parent_signatures)

    best_length = 0
    best_start = None
    for parent_start in parent_positions.get(child_signatures[0], []):
        if not _event_is_pre_spawn(parent_trace[parent_start], spawn_timestamp):
            continue
        matched = 0
        while matched < len(child_signatures) and parent_start + matched < len(parent_signatures):
            parent_index = parent_start + matched
            if not _event_is_pre_spawn(parent_trace[parent_index], spawn_timestamp):
                break
            if child_signatures[matched] != parent_signatures[parent_index]:
                break
            matched += 1
        if matched > best_length or (
            matched == best_length
            and matched > 0
            and (best_start is None or parent_start > best_start)
        ):
            best_length = matched
            best_start = parent_start
    return best_length, best_start


def _slice_from_trace_item(item, delta):
    return {
        "timestamp": item.get("timestamp"),
        "model": item.get("model"),
        "effort": item.get("effort"),
        "service_tier": item.get("service_tier"),
        "model_context_window": item.get("model_context_window"),
        "request_input_tokens": (item.get("last_usage") or {}).get("input_tokens"),
        "usage": normalize_usage(delta) or empty_usage(),
    }


def _rebuild_from_trace(session, prefix_length, start, end, exclusion_kind="verified", seed=None):
    trace = session.get("raw_token_trace") or []
    adjusted_usage = empty_usage()
    replay_usage = empty_usage()
    raw_usage = empty_usage()
    adjusted_slices = []
    replay_slices = []
    accumulator = TokenUsageAccumulator((seed or {}).get("usage"))
    mismatch_count = 0

    for index, item in enumerate(trace):
        cumulative = normalize_usage(item.get("cumulative_usage"))
        delta = accumulator.consume(cumulative, item.get("last_usage"))
        if not _event_in_window(item.get("timestamp"), start, end):
            continue
        add_usage(raw_usage, delta)
        if delta["total_tokens"] <= 0:
            continue
        normalized_last = normalize_usage(item.get("last_usage"))
        if normalized_last and usage_signature(normalized_last) != usage_signature(delta):
            mismatch_count += 1
        output = _slice_from_trace_item(item, delta)
        for field in ("model", "effort", "service_tier"):
            if output.get(field) is None and seed and field in seed:
                output[field] = seed[field]
        if index < prefix_length:
            add_usage(replay_usage, delta)
            replay_slices.append(output)
        else:
            add_usage(adjusted_usage, delta)
            adjusted_slices.append(output)

    verified_usage = replay_usage if exclusion_kind == "verified" else empty_usage()
    inferred_usage = replay_usage if exclusion_kind == "inferred" else empty_usage()
    verified_slices = replay_slices if exclusion_kind == "verified" else []
    inferred_slices = replay_slices if exclusion_kind == "inferred" else []
    return {
        "token_usage": adjusted_usage,
        "token_slices": adjusted_slices,
        "verified_replay_usage": verified_usage,
        "verified_replay_slices": verified_slices,
        "inferred_replay_usage": inferred_usage,
        "inferred_replay_slices": inferred_slices,
        "raw_logged_usage": raw_usage,
        "token_slice_last_mismatches": mismatch_count,
        "accounting_adjustments": dict(accumulator.adjustments),
    }


def _mark_unreconciled(session, method):
    session["token_reconciliation_method"] = method
    session["token_reconciliation_confidence"] = "unreconciled"
    session["verified_replay_usage"] = empty_usage()
    session["verified_replay_slices"] = []
    session["verified_replay_events"] = 0
    session["verified_replay_prefix_events"] = 0
    session["inferred_replay_usage"] = empty_usage()
    session["inferred_replay_slices"] = []
    session["inferred_replay_events"] = 0
    session["inferred_replay_prefix_events"] = 0
    session["replay_alignment_parent_index"] = None
    session["raw_logged_usage"] = normalize_usage(session.get("token_usage")) or empty_usage()


def _startup_baseline_candidate(session):
    """Return whether the first child snapshot is a dominant spawn baseline."""
    trace = session.get("raw_token_trace") or []
    spawn_timestamp = session.get("spawn_timestamp")
    if not trace or spawn_timestamp is None:
        return False

    first = trace[0]
    timestamp = first.get("timestamp")
    if timestamp is None:
        return False
    if abs((timestamp - spawn_timestamp).total_seconds()) > SPAWN_TIMESTAMP_TOLERANCE_SECONDS:
        return False

    cumulative = normalize_usage(first.get("cumulative_usage"))
    last_usage = normalize_usage(first.get("last_usage"))
    if cumulative is None or last_usage is None or cumulative["total_tokens"] <= 0:
        return False

    inferred_baseline = cumulative["total_tokens"] - last_usage["total_tokens"]
    if inferred_baseline < INFERRED_BASELINE_MIN_TOKENS:
        return False
    return inferred_baseline / cumulative["total_tokens"] >= INFERRED_BASELINE_MIN_SHARE


def reconcile_sessions(sessions, lineage_index, start, end):
    """Apply verified alignment and guarded startup inference."""
    parent_trace_cache = {}

    def cached_parent_trace(parent_id, parent):
        cached = parent_trace_cache.get(parent_id)
        if cached is not None:
            return cached
        trace = parent.get("raw_token_trace") or []
        signatures = _trace_signatures(trace)
        cached = (trace, signatures, _signature_positions(signatures))
        parent_trace_cache[parent_id] = cached
        return cached

    for session in sessions:
        trace = session.get("raw_token_trace") or []
        source = str(session.get("session_source") or "top_level")

        if not trace:
            _mark_unreconciled(session, "raw_trace_unavailable")
            continue

        seed, seed_error = resolve_history_seed(session, lineage_index)
        if session.get("history_base") is not None:
            rebuilt = _rebuild_from_trace(session, 0, start, end, seed=seed)
            session.update(rebuilt)
            _mark_unreconciled(session, seed_error or "bounded_paginated_history")
            if not seed_error:
                session["token_reconciliation_confidence"] = "verified"
            continue

        if source != "spawned_subagent" and not session.get("parent_session_id"):
            session.update(_rebuild_from_trace(session, 0, start, end))
            session["token_reconciliation_method"] = "not_applicable"
            session["token_reconciliation_confidence"] = "observed"
            session["verified_replay_usage"] = empty_usage()
            session["verified_replay_slices"] = []
            session["verified_replay_events"] = 0
            session["verified_replay_prefix_events"] = 0
            session["inferred_replay_usage"] = empty_usage()
            session["inferred_replay_slices"] = []
            session["inferred_replay_events"] = 0
            session["inferred_replay_prefix_events"] = 0
            session["replay_alignment_parent_index"] = None
            session["raw_logged_usage"] = normalize_usage(session.get("token_usage")) or empty_usage()
            continue

        parent_id = str(session.get("parent_session_id") or "")
        parent = lineage_index.get(parent_id)
        if parent is None:
            rebuilt = _rebuild_from_trace(session, 0, start, end)
            session.update(rebuilt)
            session["token_slice_invalid"] = False
            _mark_unreconciled(session, "parent_missing")
            continue

        parent_trace, parent_signatures, parent_positions = cached_parent_trace(parent_id, parent)
        prefix_length, parent_start = _aligned_prefix_match(
            trace,
            parent_trace,
            parent_signatures=parent_signatures,
            parent_positions=parent_positions,
            spawn_timestamp=session.get("spawn_timestamp"),
        )
        exclusion_kind = "verified"
        method = None
        confidence = None
        if prefix_length:
            method = "exact_parent_prefix" if parent_start == 0 else "exact_parent_aligned_prefix"
            confidence = "verified"
        elif _startup_baseline_candidate(session):
            # The response accumulator already removes the inherited initial baseline.
            # Retain the first response; do not exclude it a second time.
            prefix_length = 0
            exclusion_kind = "inferred"
            method = "inferred_startup_baseline"
            confidence = "inferred"

        rebuilt = _rebuild_from_trace(
            session,
            prefix_length,
            start,
            end,
            exclusion_kind=exclusion_kind,
        )
        session.update(rebuilt)
        session["token_slice_invalid"] = False
        session["verified_replay_events"] = len(rebuilt["verified_replay_slices"])
        session["verified_replay_prefix_events"] = prefix_length if exclusion_kind == "verified" else 0
        session["inferred_replay_events"] = len(rebuilt["inferred_replay_slices"])
        session["inferred_replay_prefix_events"] = prefix_length if exclusion_kind == "inferred" else 0
        session["replay_alignment_parent_index"] = parent_start
        if method:
            session["token_reconciliation_method"] = method
            session["token_reconciliation_confidence"] = confidence
        else:
            first = trace[0]
            cumulative = normalize_usage(first.get("cumulative_usage"))
            last_usage = normalize_usage(first.get("last_usage"))
            if (
                cumulative is not None
                and last_usage is not None
                and usage_signature(cumulative) == usage_signature(last_usage)
            ):
                session["token_reconciliation_method"] = "child_local_counter"
                session["token_reconciliation_confidence"] = "observed"
            elif session.get("history_mode") == "paginated":
                session["token_reconciliation_method"] = "independent_paginated_usage"
                session["token_reconciliation_confidence"] = "observed"
            else:
                session["token_reconciliation_method"] = "no_parent_alignment"
                session["token_reconciliation_confidence"] = "unreconciled"

    return sessions


def reconciliation_quality(sessions):
    methods = defaultdict(int)
    raw = empty_usage()
    adjusted = empty_usage()
    verified = empty_usage()
    inferred = empty_usage()
    matched_events = 0
    matched_prefix_events = 0
    inferred_events = 0
    inferred_prefix_events = 0
    unresolved_sessions = 0
    unresolved_token_sessions = 0
    unresolved_boundaries = 0

    for session in sessions:
        method = str(session.get("token_reconciliation_method") or "unknown")
        methods[method] += 1
        if session.get("history_base") is not None and session.get("token_reconciliation_confidence") == "unreconciled":
            unresolved_boundaries += 1
        session_adjusted = normalize_usage(session.get("token_usage")) or empty_usage()
        session_verified = normalize_usage(session.get("verified_replay_usage")) or empty_usage()
        session_inferred = normalize_usage(session.get("inferred_replay_usage")) or empty_usage()
        session_raw = normalize_usage(session.get("raw_logged_usage"))
        if session_raw is None:
            session_raw = dict(session_adjusted)
            add_usage(session_raw, session_verified)
            add_usage(session_raw, session_inferred)
        add_usage(raw, session_raw)
        add_usage(adjusted, session_adjusted)
        add_usage(verified, session_verified)
        add_usage(inferred, session_inferred)
        matched_events += int(session.get("verified_replay_events", 0) or 0)
        matched_prefix_events += int(session.get("verified_replay_prefix_events", 0) or 0)
        inferred_events += int(session.get("inferred_replay_events", 0) or 0)
        inferred_prefix_events += int(session.get("inferred_replay_prefix_events", 0) or 0)
        if str(session.get("session_source") or "top_level") == "spawned_subagent" and method in {
            "no_parent_alignment",
            "parent_missing",
            "invalid_cumulative_trace",
            "raw_trace_unavailable",
        }:
            unresolved_sessions += 1
            if session_adjusted["total_tokens"] > 0:
                unresolved_token_sessions += 1

    component_reconciled = all(
        raw[key] == adjusted[key] + verified[key] + inferred[key]
        for key in TOKEN_USAGE_KEYS
    )
    matched_sessions = int(methods.get("exact_parent_prefix", 0)) + int(
        methods.get("exact_parent_aligned_prefix", 0)
    )
    inferred_sessions = int(methods.get("inferred_startup_baseline", 0))
    if not component_reconciled or unresolved_token_sessions or unresolved_boundaries:
        confidence = "low"
    elif inferred_sessions:
        confidence = "medium"
    else:
        confidence = "high"
    return {
        "method": "aligned_parent_prefix_with_guarded_startup_inference",
        "matched_sessions": matched_sessions,
        "matched_root_prefix_sessions": int(methods.get("exact_parent_prefix", 0)),
        "matched_offset_prefix_sessions": int(methods.get("exact_parent_aligned_prefix", 0)),
        "matched_replay_events_in_window": matched_events,
        "matched_prefix_events": matched_prefix_events,
        "inferred_startup_sessions": inferred_sessions,
        "inferred_replay_events_in_window": inferred_events,
        "inferred_prefix_events": inferred_prefix_events,
        "retained_local_counter_sessions": int(methods.get("child_local_counter", 0)),
        "unresolved_spawned_sessions": unresolved_sessions,
        "unresolved_token_bearing_spawned_sessions": unresolved_token_sessions,
        "unresolved_history_boundaries": unresolved_boundaries,
        "unmatched_spawned_sessions": int(methods.get("child_local_counter", 0))
        + int(methods.get("no_parent_alignment", 0)),
        "missing_parent_sessions": int(methods.get("parent_missing", 0)),
        "invalid_trace_sessions": int(methods.get("invalid_cumulative_trace", 0)),
        "raw_trace_unavailable_sessions": int(methods.get("raw_trace_unavailable", 0)),
        "methods": dict(methods),
        "raw_logged_usage": raw,
        "verified_replay_usage": verified,
        "inferred_replay_usage": inferred,
        "excluded_replay_usage": {
            key: verified[key] + inferred[key]
            for key in TOKEN_USAGE_KEYS
        },
        "adjusted_usage": adjusted,
        "component_reconciled": component_reconciled,
        "confidence": confidence,
    }
