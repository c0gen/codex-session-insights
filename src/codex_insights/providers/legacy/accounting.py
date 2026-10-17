"""Allowlisted trajectory facts; binary/tool/message contents stay transient."""
import re
from uuid import UUID

from ...codec import digest
from ...parser import project_identity
from .discovery import LegacyError
from .index import first, time_value, workspace
from .keys import DECODER_VERSION, READER_SHA256
from .schema import catalog
from .wire import message, varint

COMPONENTS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
              "output_tokens", "reasoning_output_tokens", "total_tokens")
MODEL_IDS = {312: "gemini-2.5-flash", 330: "gemini-2.5-flash-lite",
    333: "claude-sonnet-4-5-20250929", 334: "claude-sonnet-4-5-20250929"}


def uuid_text(raw):
    try:
        value = raw.decode("ascii")
        if str(UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, UnicodeError, AttributeError):
        raise LegacyError("invalid_trajectory_identity") from None


def model_name(enum, response_model=None):
    if response_model:
        value = response_model.decode('utf-8')
        if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}', value):
            return value
    return MODEL_IDS.get(enum, "antigravity-legacy-model-" + str(enum))


def usage(raw):
    """ModelUsageStats snapshots: noncached input + cache reads; thinking is
    an output subset. Never infer omitted scalar components as explicit zeros.
    Deprecated cache_write_tokens is a breakdown, not another input increment.
    """
    values = message(raw or b"")
    def numeric(number):
        value = first(values, number)
        if value is not None and (type(value) is not int or value < 0 or value > 2**53):
            raise LegacyError("invalid_usage_counter")
        return value
    noncached, output, reads, writes, thinking, answer = (numeric(n) for n in (2, 3, 5, 4, 9, 10))
    if output is not None and thinking is not None and thinking > output:
        raise LegacyError("invalid_reasoning_subset")
    if output is not None and answer is not None and answer > output:
        raise LegacyError("invalid_response_subset")
    if output is not None and answer is not None and thinking is not None and answer + thinking != output:
        raise LegacyError("inconsistent_output_breakdown")
    inputs = noncached + reads if noncached is not None and reads is not None else None
    counters = {"input_tokens": inputs, "cached_input_tokens": reads,
        "cache_write_input_tokens": writes, "output_tokens": output,
        "reasoning_output_tokens": thinking,
        "total_tokens": inputs + output if inputs is not None and output is not None else None}
    return counters, values


def packed_indices(raws):
    result = []
    for raw in raws:
        if type(raw) is int:
            result.append(raw)
        else:
            pos = 0
            while pos < len(raw):
                value, pos = varint(raw, pos)
                result.append(value)
    return result


def edit_event(step, metadata, sid, trajectory_id, ordinal, timestamp, model):
    if first(step, 1) != 5:
        return None
    status = first(step, 4)
    action = message(first(step, 10, b""))
    result = message(first(action, 2, b""))
    edit = message(first(result, 1, b""))
    diff = message(first(edit, 2, b""))
    unified = message(first(diff, 3, b"")) if 3 in diff else None
    tool = message(first(metadata, 4, b""))
    identity = first(tool, 1)
    call_id = digest(["antigravity", sid, identity.decode("utf-8") if identity else [trajectory_id, ordinal]])
    failed = status in (4, 5, 6, 7, 12) or 31 in step
    confirmed = status == 3 and not failed and bool(edit) and unified is not None
    added = removed = 0
    if confirmed:
        for encoded in unified.get(3, []):
            line = message(encoded)
            line_type = first(line, 2)
            if line_type not in (1, 2, 3):
                raise LegacyError("unsupported_diff_line")
            added += line_type == 1
            removed += line_type == 2
    path = first(edit, 8) or first(edit, 1)
    file_ids = ["file:" + digest([path.decode("utf-8")])] if path else []
    return {"timestamp": timestamp, "resolved_at": time_value(first(metadata, 8)),
        "call_id": call_id, "index": ordinal, "digest": digest([call_id, added, removed]), "files": file_ids,
        "result_files": file_ids, "added": added, "removed": removed, "supported": True,
        "unknown_size": not confirmed and not failed,
        "outcome": "failed" if failed else "confirmed" if confirmed else "unknown", "model": model}


def facts(trajectory, conversation_id, index=None):
    """One verified snapshot per conversation, including nested trajectory steps."""
    trajectory_id = uuid_text(first(trajectory, 1))
    metadata = message(first(trajectory, 7, b""))
    created = time_value(first(metadata, 2))
    if created is None:
        raise LegacyError("creation_time_missing")
    project = workspace(first(metadata, 1)) if metadata.get(1) else project_identity({})
    index_match = False
    if index:
        if index["trajectory_id"] != trajectory_id:
            raise LegacyError("index_identity_mismatch")
        index_match = (index["created_at"] is not None
            and abs((created - index["created_at"]).total_seconds()) <= 5
            and (not metadata.get(1) or project["project_id"] == index["project_id"]))
        if index_match and not metadata.get(1):
            project = {k: index[k] for k in ("project_id", "project_label")}
    parent_raw = first(metadata, 5)
    parent = "antigravity:" + uuid_text(parent_raw) if parent_raw else None
    result = {"provider": "antigravity", "id": "antigravity:" + conversation_id,
        "segment_id": digest(["antigravity", conversation_id, "legacy"]),
        "metadata_timestamp": created, **project,
        "session_source": "spawned_subagent" if parent else "top_level",
        "parent_session_id": parent, "spawn_timestamp": created,
        "raw_token_trace": [], "messages": [], "change_events": [], "activity": [],
        "contexts": [], "tools": {}, "parse_errors": 0,
        "subagent_relationships": [],
        "provenance": {"format": "antigravity_legacy", "decoder": DECODER_VERSION,
            "reader_sha256": READER_SHA256, "authenticated": True,
            "index_matched": index_match, "trajectory_id": trajectory_id},
        "coverage": {}, "snapshot_mode": "complete_binary"}
    responses = {}
    step_count = 0
    def record(raw, timestamp, enum, invocation, response_model=None):
        counters, values = usage(raw)
        response = first(values, 11) or first(values, 12) or first(values, 7)
        rid = digest(["antigravity", response.decode("utf-8")]) if response else digest(["antigravity", "legacy-invocation", invocation])
        model_enum = first(values, 1, enum or 0)
        model = model_name(model_enum, response_model)
        item = {"timestamp": timestamp, "ordinal": len(responses), "end_byte_offset": 0,
                "response_id": rid, "last_usage": counters, "model": model,
                "invocation_id": digest(invocation),
                'model_enum': model_enum,
                "recorded_components": {"noncached_input_tokens": first(values, 2),
                    "response_output_tokens": first(values, 10)}}
        previous = responses.get(rid)
        if previous:
            # A repeated request snapshot is a maximum, never another increment.
            old = previous["last_usage"]
            item["last_usage"] = {k: max(old[k], counters[k]) if old[k] is not None and counters[k] is not None
                else old[k] if counters[k] is None else counters[k] for k in COMPONENTS}
            merged = item['last_usage']
            merged['total_tokens'] = merged['input_tokens'] + merged['output_tokens'] if merged['input_tokens'] is not None and merged['output_tokens'] is not None else None
            item["timestamp"] = previous["timestamp"]
        responses[rid] = item
        result["contexts"].append({"timestamp": timestamp, "model": model})
    def visit(current, depth=0):
        nonlocal step_count
        if depth > 32:
            raise LegacyError("subtrajectory_depth_limit")
        tid = uuid_text(first(current, 1))
        steps = [message(s) for s in current.get(2, [])]
        for ordinal, step in enumerate(steps):
            step_count += 1
            md = message(first(step, 5, b""))
            timestamp = time_value(first(md, 1))
            if timestamp is None:
                raise LegacyError("step_time_missing")
            model = model_name(first(md, 11, 0))
            result["activity"].append(timestamp)
            result["contexts"].append({"timestamp": timestamp, "model": model})
            if first(step, 1) in (14, 15):
                result["messages"].append({"timestamp": timestamp, "role": "user" if first(step, 1) == 14 else "assistant",
                    "signature": digest(["antigravity", tid, ordinal]), "model": model})
            if 9 in md:
                record(first(md, 9), timestamp, first(md, 11), [tid, "step", ordinal])
            edit = edit_event(step, md, conversation_id, tid, ordinal, timestamp, model)
            if edit:
                result["change_events"].append(edit)
            if 6 in step:
                child = message(first(step, 6))
                child_id = uuid_text(first(child, 1))
                result['subagent_relationships'].append({'id': 'antigravity:' + child_id,
                    'parent_session_id': result['id'], 'timestamp': timestamp,
                    'step_count': len(child.get(2, []))})
                visit(child, depth + 1)
        for ordinal, encoded in enumerate(current.get(3, [])):
            generator = message(encoded)
            if 1 not in generator:
                continue  # Injected responses have no model invocation.
            chat = message(first(generator, 1))
            start = message(first(chat, 9, b""))
            timestamp = time_value(first(start, 4))
            if timestamp is None:
                indices = packed_indices(generator.get(2, []))
                timestamp = time_value(first(message(first(steps[indices[0]], 5, b"")), 1)) if indices and indices[0] < len(steps) else None
            if timestamp is None:
                raise LegacyError("invocation_time_missing")
            record(first(chat, 4, b""), timestamp, first(chat, 3), [tid, "generator", ordinal], first(chat, 19))
    visit(trajectory)
    result["raw_token_trace"] = list(responses.values())
    edits = {}
    for edit in result['change_events']:
        previous = edits.get(edit['call_id'])
        if previous and previous['outcome'] == edit['outcome'] == 'confirmed' and (previous['added'], previous['removed']) != (edit['added'], edit['removed']):
            raise LegacyError('inconsistent_tool_outcome')
        if previous is None or previous['outcome'] != 'confirmed':
            edits[edit['call_id']] = edit
    result['change_events'] = list(edits.values())
    observations = len(responses)
    result["coverage"] = {k: {"available": sum(item["last_usage"][k] is not None for item in responses.values()),
        "observations": observations} for k in COMPONENTS}
    result["coverage"]["edits"] = {"available": sum(e["outcome"] == "confirmed" for e in result["change_events"]),
        "observations": sum(e["outcome"] != "failed" for e in result["change_events"])}
    result['coverage']['edit_completion_time'] = {
        'available': sum(e['outcome'] == 'confirmed' and e['resolved_at'] is not None for e in result['change_events']),
        'observations': sum(e['outcome'] == 'confirmed' for e in result['change_events'])}
    result["record_count"] = step_count
    return result
