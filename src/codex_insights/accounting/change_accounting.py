"""Conservative, static accounting of edits recorded in session logs.

No source code is evaluated. Counts describe observed operations, not repository
size. Opaque results and unsupported write mechanisms remain explicit gaps.
"""
from __future__ import annotations

import hashlib
import json
import re


CONTRACT_VERSION = "2.0"
COUNT_FIELDS = (
    "lines_added", "lines_removed", "recovered_attempt_lines_added",
    "recovered_attempt_lines_removed", "confirmed_operations", "failed_operations",
    "unknown_operations", "unsupported_operations", "unknown_size_operations",
    "excluded_replay_operations", "unresolved_duplicate_operations",
)


def empty_changes():
    return {"contract_version": CONTRACT_VERSION, **dict.fromkeys(COUNT_FIELDS, 0)}


def coverage(changes):
    gap = any(changes.get(k, 0) for k in (
        "unknown_operations", "unsupported_operations", "unknown_size_operations",
        "unresolved_duplicate_operations",
    ))
    if not changes.get("confirmed_operations", 0) or (changes.get("unknown_size_operations", 0) and not (changes.get("lines_added", 0) or changes.get("lines_removed", 0))):
        return "not_measured" if gap else "no_observed_changes"
    return "partial" if gap else "observed"


def merge_changes(target, source):
    for key in COUNT_FIELDS:
        target[key] += source.get(key, 0)
    target["coverage_status"] = coverage(target)
    return target


def patch_stats(patch):
    """Parse the apply_patch grammar; deletion bodies are not present in logs."""
    added = removed = 0
    files = set()
    result_files = set()
    current_file = None
    section = None
    unknown_size = False
    valid = patch.startswith("*** Begin Patch") and "*** End Patch" in patch
    for line in patch.splitlines():
        match = re.match(r"\*\*\* (Add|Update|Delete) File: (.+)", line)
        if match:
            section = match[1]
            files.add(match[2].strip())
            current_file = match[2].strip()
            result_files.add(current_file)
            unknown_size |= section == "Delete"
        elif line.startswith("*** Move to: "):
            destination = line[len("*** Move to: "):].strip()
            files.add(destination)
            result_files.discard(current_file)
            result_files.add(destination)
        elif line.startswith("*** End Patch"):
            section = None
        elif section in {"Add", "Update"}:
            if line.startswith("+"):
                added += 1
            elif section == "Update" and line.startswith("-"):
                removed += 1
    return {"added": added, "removed": removed, "files": sorted(files), "result_files": sorted(result_files),
            "unknown_size": unknown_size, "supported": bool(valid and files)}


# A small lexer, deliberately not a JS interpreter. Comments and quoted content
# cannot masquerade as calls. Nonliteral expressions are never approximated.
_TOKEN = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|\s+|"
    r"\"(?:\\[\s\S]|[^\"\\])*\"|'(?:\\[\s\S]|[^'\\])*'|"
    r"`(?:\\[\s\S]|[^`\\])*`|[A-Za-z_$][\w$]*|[^\s]"
)


def literal(token):
    if not token or token[0] not in "\"'`" or token[-1] != token[0]:
        return None
    if token[0] == "`" and "${" in token:
        return None
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    out = []
    i = 1
    while i < len(token) - 1:
        ch = token[i]
        i += 1
        if ch != "\\":
            out.append(ch)
            continue
        ch = token[i]
        i += 1
        if ch in "xu":
            length = 2 if ch == "x" else 4
            try:
                out.append(chr(int(token[i:i + length], 16)))
            except ValueError:
                return None
            i += length
        elif ch == "\r" or ch == "\n":
            if ch == "\r" and token[i:i + 1] == "\n":
                i += 1
        else:
            out.append(escapes.get(ch, ch))
    return "".join(out)


def nested_patches(code):
    tokens = [m[0] for m in _TOKEN.finditer(code)
              if not m[0].isspace() and not m[0].startswith(("//", "/*"))]
    scopes = [{}]
    def lookup(name):
        return next((scope[name] for scope in reversed(scopes) if name in scope), None)
    patches = []
    for i, token in enumerate(tokens):
        if token == "{":
            scopes.append({})
        elif token == "}" and len(scopes) > 1:
            scopes.pop()
        if token in {"const", "let", "var"} and i + 4 < len(tokens) and tokens[i + 2] == "=":
            name, value = tokens[i + 1], tokens[i + 3]
            # Only immutable single-token declarations, before their use.
            scopes[-1][name] = ((literal(value) if value[:1] in {"\"", "'", "`"} else lookup(value)) if token == "const" and tokens[i + 4] == ";" else None)
        if tokens[i:i + 4] == ["tools", ".", "apply_patch", "("]:
            value = tokens[i + 4] if i + 4 < len(tokens) else ""
            simple = i + 5 < len(tokens) and tokens[i + 5] in {")", ","}
            patches.append((literal(value) if value[:1] in {"\"", "'", "`"} else lookup(value)) if simple else None)
    return patches


def tool_name(name):
    return re.split(r"\.|__", str(name))[-1]


def arguments(payload):
    value = payload.get("arguments", payload.get("input", ""))
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            pass
    return value


def output_text(value):
    """Decode JSON envelopes and content arrays without losing nested text."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, (list, dict)):
            return output_text(decoded)
        return value
    if isinstance(value, list):
        return "\n".join(output_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(output_text(value[key]) for key in ("text", "output", "content") if key in value)
    return ""


def explicit_failure(value):
    if isinstance(value, str):
        try:
            return explicit_failure(json.loads(value))
        except ValueError:
            return False
    if isinstance(value, dict):
        return value.get("isError") is True or (isinstance(value.get("exit_code"), int) and value["exit_code"] != 0) or any(explicit_failure(v) for v in value.values())
    if isinstance(value, list):
        return any(explicit_failure(v) for v in value)
    return False


def normalized_files(paths):
    normalized = set()
    for path in paths:
        path = path.strip().replace("\\", "/")
        normalized.add(path.lower() if re.match(r"^[A-Za-z]:/", path) else path)
    return normalized


_WRITES = re.compile(
    r"\b(?:Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|writeFileSync|writeFile|"
    r"write_text|write_bytes|unlink|rmtree)\b|\bopen\([^\n]*,[ ]*['\"](?:w|a|x)|"
    r"\bsed\s+-i\b|\b(?:rm|mv|cp|tee)\s+|\b(?:echo|printf|cat)\b[^\n]*>{1,2}\s*\S",
    re.I,
)


class ChangeTracker:
    def __init__(self):
        self.events = []
        self.pending = {}
        self.cells = {}
        self.waits = {}

    def observe(self, payload, timestamp):
        kind = payload.get("type", "")
        call_id = payload.get("call_id")
        if kind in {"function_call", "custom_tool_call"}:
            name = tool_name(payload.get("name"))
            arg = arguments(payload)
            if name == "wait" and isinstance(arg, dict):
                self.waits[call_id] = str(arg.get("cell_id", ""))
                return
            patches = []
            if name == "apply_patch":
                patches = [arg if isinstance(arg, str) else next((arg[k] for k in ("patch", "input") if isinstance(arg, dict) and isinstance(arg.get(k), str)), None)]
            elif name == "exec" and isinstance(arg, str):
                if "apply_patch" in arg:
                    patches = nested_patches(arg)
            raw = arg if isinstance(arg, str) else json.dumps(arg, sort_keys=True)
            write_source = raw
            if name == "exec" and patches:
                def without_patch(match):
                    token = match[0]
                    if token[:1] in {"\"", "'", "`"}:
                        value = literal(token)
                        if value and value.startswith("*** Begin Patch"):
                            return "''"
                    return token
                write_source = _TOKEN.sub(without_patch, raw)
            unsupported_write = name in {"exec", "exec_command", "shell", "shell_command", "write_stdin"} and bool(_WRITES.search(write_source))
            unsupported_write |= name in {"exec_command", "shell", "shell_command"} and bool(re.search(r"\bapply_patch\b", raw))
            unsupported_write |= name in {"write_file", "edit_file", "str_replace", "create_file", "delete_file"}
            indices = []
            for index, patch in enumerate(patches + ([None] if unsupported_write else [])):
                stats = patch_stats(patch) if isinstance(patch, str) else {"added": 0, "removed": 0, "files": [], "supported": False, "unknown_size": False}
                event = {**stats, "timestamp": timestamp, "call_id": call_id, "index": index,
                         "digest": hashlib.sha256((patch if patch is not None else raw).encode("utf-8", errors="surrogatepass")).hexdigest(),
                         "outcome": "unknown", "direct": name == "apply_patch"}
                indices.append(len(self.events))
                self.events.append(event)
            if indices:
                self.pending[call_id] = indices
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            indices = self.pending.get(call_id)
            if call_id in self.waits:
                indices = self.cells.get(self.waits[call_id])
            if not indices:
                return
            text = output_text(payload.get("output"))
            cell = re.search(r"Script running with cell ID\s+([^\s]+)", text)
            if cell:
                self.cells[cell[1]] = indices
            events = [self.events[i] for i in indices]
            success_blocks = re.findall(r"Success\. Updated the following files:\s*\n((?:[AMD] [^\n]+\n?)+)", text)
            successful_files = [normalized_files(re.findall(r"^[AMD] (.+)$", block, re.M)) for block in success_blocks]
            failure = bool(re.search(r"apply_patch.*(?:failed|error)|(?:Failed to find expected lines|Invalid patch|patch rejected|User rejected)", text, re.I))
            for event in events:
                if not event["supported"]:
                    continue
                # Multiple calls touching identical files cannot be distinguished
                # from unlabelled nested output; keep them unknown.
                expected = normalized_files(event["result_files"])
                matching = expected in successful_files
                unique = sum(normalized_files(other.get("result_files", [])) == expected for other in events) == 1
                if matching and unique:
                    event["outcome"] = "confirmed"
                elif len(events) == 1 and (failure or (event["direct"] and (explicit_failure(payload.get("output")) or re.search(r"permission denied|access.*denied", text, re.I)))) and event["outcome"] != "confirmed":
                    event["outcome"] = "failed"


def event_signature(event):
    return (event.get("call_id"), event["index"], event["digest"], event["timestamp"])


def apply_events(session, start=None, end=None, excluded=None, unresolved=False, unresolved_signatures=None):
    stats = empty_changes()
    files = set()
    times = []
    groups = {}
    for event in session.get("change_events", []):
        t = event["timestamp"]
        if t is None or (start is not None and not start <= t < end):
            continue
        signature = event_signature(event)
        # No identity means no reliable result pairing or duplicate exclusion.
        key = signature if event.get("call_id") else ("unidentified", len(groups))
        groups.setdefault(key, []).append(event)
    for group in groups.values():
        event = group[0]
        t = event["timestamp"]
        signature = event_signature(event)
        stats["excluded_replay_operations"] += len(group) - 1
        if event.get("call_id") and signature in (excluded or set()):
            stats["excluded_replay_operations"] += 1
            continue
        outcomes = {item["outcome"] for item in group} - {"unknown"}
        # A later exact duplicate can supply a previously missing result, but
        # contradictory conclusive results cannot establish an applied edit.
        outcome = next(iter(outcomes)) if len(outcomes) == 1 and event.get("call_id") else "unknown"
        if unresolved or signature in (unresolved_signatures or set()) or not event.get("call_id"):
            stats["unresolved_duplicate_operations"] += 1
        stats["recovered_attempt_lines_added"] += event["added"]
        stats["recovered_attempt_lines_removed"] += event["removed"]
        stats[outcome + "_operations"] += 1
        stats["unsupported_operations"] += not event["supported"]
        stats["unknown_size_operations"] += event["unknown_size"] and outcome != "failed"
        if outcome == "confirmed":
            stats["lines_added"] += event["added"]
            stats["lines_removed"] += event["removed"]
            files.update(event["files"])
            times.append(t)
    stats["coverage_status"] = coverage(stats)
    session.update(change_accounting=stats, plus=stats["lines_added"], minus=stats["lines_removed"], files=files, patch_times=times)


def reconcile_changes(sessions, entries, start, end):
    """Exclude only exact operation identities replayed before recorded spawn."""
    ancestors = {}
    for _path, payload in entries:
        for session in payload.get("sessions", []):
            ancestors.setdefault(session["id"], session)
    recorded = {}
    for session in sessions:
        excluded = set(recorded.get(session["id"], set()))
        ancestor_identities = set()
        parent = session.get("parent_session_id")
        spawn = session.get("spawn_timestamp")
        visited = {session["id"]}
        unresolved = bool(parent and (parent not in ancestors or spawn is None))
        while parent and parent in ancestors and parent not in visited:
            visited.add(parent)
            ancestor = ancestors[parent]
            ancestor_identities.update(event_signature(e)[:3] for e in ancestor.get("change_events", []) if e.get("call_id"))
            excluded.update(event_signature(e) for e in ancestor.get("change_events", [])
                            if e.get("call_id") and spawn and e["timestamp"] and e["timestamp"] < spawn)
            parent = ancestor.get("parent_session_id")
        unresolved_signatures = {event_signature(e) for e in session.get("change_events", [])
                                 if event_signature(e) not in excluded and (
                                     (spawn and e["timestamp"] and e["timestamp"] < spawn)
                                     or event_signature(e)[:3] in ancestor_identities)}
        apply_events(session, start, end, excluded, unresolved, unresolved_signatures)
        recorded.setdefault(session["id"], set()).update(event_signature(e) for e in session.get("change_events", []) if e.get("call_id"))
