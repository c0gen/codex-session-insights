"""Claude tool edit accounting retains sizes and hashes, never tool arguments."""
import difflib

from ..codec import digest


def observe(state, content, role, at, model):
    if not isinstance(content, list):
        return
    pending = state.setdefault("pending_edits", {})
    facts = state["fact"]
    for item in content:
        if not isinstance(item, dict):
            continue
        if role == "assistant" and item.get("type") == "tool_use":
            name, identifier, args = item.get("name"), item.get("id"), item.get("input")
            if name not in {"Edit", "Write", "MultiEdit"} or not isinstance(identifier, str) or not isinstance(args, dict):
                continue
            changes = [args] if name == "Edit" else args.get("edits", []) if name == "MultiEdit" else []
            known = bool(changes) and isinstance(changes, list) and all(isinstance(c, dict) and
                isinstance(c.get("old_string"), str) and isinstance(c.get("new_string"), str) and
                c.get("replace_all", False) is False and len(c["old_string"]) + len(c["new_string"]) <= 256 * 1024 and
                c["old_string"].count("\n") + c["new_string"].count("\n") <= 2000 for c in changes)
            added = removed = 0
            if known:
                for change in changes:
                    for line in difflib.ndiff(change["old_string"].splitlines(), change["new_string"].splitlines()):
                        added += line.startswith("+ ")
                        removed += line.startswith("- ")
            call_id = digest([facts["provider"], identifier])
            edit = {"timestamp": at, "call_id": call_id, "added": added, "removed": removed,
                "files": [], "result_files": [], "supported": known, "unknown_size": not known,
                "outcome": "unknown", "index": 0, "digest": call_id, "direct": True, "model": model}
            if call_id not in pending:
                facts["change_events"].append(edit)
                pending[call_id] = len(facts["change_events"]) - 1
        elif role == "user" and item.get("type") == "tool_result":
            call_id = digest([facts["provider"], item.get("tool_use_id")])
            if call_id in pending:
                edit = facts["change_events"][pending[call_id]]
                if item.get("is_error", False) in (True, False):
                    edit.update(outcome="failed" if item.get("is_error", False) else "confirmed", resolved_at=at)
