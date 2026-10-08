"""Resolve explicitly named, immutable paginated history boundaries on demand.

No base (or null) is an independent counter. A malformed base stays unresolved.
Logical parent final totals must never substitute for the physical cutoff.
"""
import json
from pathlib import Path
from .pricing import normalize_service_tier
from .token_accounting import normalize_usage


def resolve_history_seed(session, index, visited=None):
    base = session.get("history_base")
    if base is None:
        return None, None
    if not isinstance(base, dict):
        return None, "malformed_history_base"
    thread_id = base.get("thread_id")
    offset, ordinal = base.get("end_byte_offset"), base.get("end_ordinal_exclusive")
    if (not isinstance(thread_id, str) or type(offset) is not int or type(ordinal) is not int
            or offset < 0 or ordinal < 0):
        return None, "malformed_history_base"
    visited = set(visited or ())
    if thread_id in visited:
        return None, "cyclic_history_base"
    visited.add(thread_id)
    parent = index.get(thread_id)
    if parent is None:
        return None, "history_base_source_unavailable"
    seed, error = resolve_history_seed(parent, index, visited)
    if error:
        return None, error
    state = dict(seed or {})
    if "record_boundaries" in parent:
        boundaries = dict(parent["record_boundaries"])
        if offset and boundaries.get(offset) != ordinal - 1:
            return None, "history_base_boundary_mismatch"
        if offset == 0 and ordinal != 0:
            return None, "history_base_boundary_mismatch"
        for item in parent.get("boundaries", []):
            if item["end_byte_offset"] > offset:
                break
            for field in ("model", "effort", "service_tier", "usage"):
                if item.get(field) is not None:
                    state[field] = item[field]
        return state, None
    if not parent.get("_physical_path"):
        return None, "history_base_source_unavailable"
    consumed, last_ordinal = 0, None
    try:
        with Path(parent["_physical_path"]).open("rb") as source:
            while consumed < offset:
                line = source.readline(offset - consumed)
                if not line or not line.endswith(b"\n"):
                    return None, "history_base_boundary_incomplete"
                consumed += len(line)
                event = json.loads(line)
                last_ordinal = event.get("ordinal")
                payload = event.get("payload") or {}
                if not isinstance(payload, dict):
                    continue
                if event.get("type") == "turn_context":
                    for field in ("model", "effort", "reasoning_effort"):
                        if payload.get(field) is not None:
                            state["effort" if field == "reasoning_effort" else field] = payload[field]
                    if "service_tier" in payload:
                        state["service_tier"] = normalize_service_tier(payload["service_tier"])
                elif payload.get("type") == "thread_settings_applied":
                    settings = payload.get("thread_settings") or payload.get("settings") or payload
                    if "model" in settings:
                        state["model"] = settings["model"]
                    if "service_tier" in settings:
                        state["service_tier"] = normalize_service_tier(settings["service_tier"])
                elif payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    usage = normalize_usage(info.get("total_token_usage"))
                    if usage is not None:
                        state["usage"] = usage
    except (OSError, ValueError, TypeError):
        return None, "history_base_read_failed"
    if consumed != offset or (ordinal != 0 and last_ordinal != ordinal - 1):
        return None, "history_base_boundary_mismatch"
    return state, None
