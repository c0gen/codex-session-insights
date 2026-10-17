"""Read completed file edits and correlate them without retaining source text."""
import hashlib
import json
import posixpath
import re
from collections import Counter


def path_key(path, cwd=""):
    path = path.replace("\\", "/")
    if not path.startswith("/") and not re.match(r"^[A-Za-z]:/", path):
        path = posixpath.join(cwd.replace("\\", "/"), path)
    path = posixpath.normpath(path)
    return path.lower() if re.match(r"^[A-Za-z]:/", path) or path.startswith("//") else path


def fingerprint(parts, cwd=""):
    normalized = []
    for path, kind, move, added, removed in parts:
        if kind == "update":
            # Diff generators shift repeated boundary lines and omit unchanged
            # remove/add pairs. Compare net line contents within the call, not
            # hunk layout. Retain ordering for pure rearrangements (zero delta).
            additions, removals = Counter(added), Counter(removed)
            if additions != removals:
                added = sorted((additions - removals).items())
                removed = sorted((removals - additions).items())
        # A delete request omits the old contents; the completion supplies them.
        normalized.append([path_key(path, cwd), kind, path_key(move, cwd) if move else None,
                           added, [] if kind == "delete" else removed])
    # Repeated paths can mix net-count tuples with ordered rearrangement lines,
    # or moved and unmoved edits. Those values are not directly comparable.
    # Keep the usual path/kind ordering and use JSON for heterogeneous ties.
    ordered = sorted(normalized, key=lambda part: (
        part[0], part[1], json.dumps(part[2:], ensure_ascii=False, separators=(",", ":"))))
    encoded = json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="surrogatepass")).hexdigest()


def patch_fingerprint(patch, cwd=""):
    if not isinstance(patch, str) or not patch.startswith("*** Begin Patch"):
        return None
    parts = []
    current = None
    for line in patch.splitlines():
        header = re.fullmatch(r"\*\*\* (Add|Update|Delete) File: (.+)", line)
        if header:
            current = [header[2].strip(), header[1].lower(), None, [], []]
            parts.append(current)
        elif line == "*** End Patch":
            return fingerprint(parts, cwd) if parts else None
        elif current:
            if line.startswith("*** Move to: "):
                current[2] = line[len("*** Move to: "):].strip()
            elif line.startswith("+") and current[1] in {"add", "update"}:
                current[3].append(line[1:])
            elif line.startswith("-") and current[1] == "update":
                current[4].append(line[1:])
    return None


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def diff_lines(diff):
    """Validate hunk lengths, keeping only real additions and removals."""
    if not isinstance(diff, str):
        raise ValueError("Missing unified diff")
    added, removed = [], []
    remaining = None
    saw_hunk = False
    for line in diff.splitlines():
        match = _HUNK.fullmatch(line)
        if match:
            if remaining and any(remaining):
                raise ValueError("Incomplete diff hunk")
            remaining = [int(match[2] or 1), int(match[4] or 1)]
            saw_hunk = True
        elif line == "\\ No newline at end of file" and saw_hunk:
            continue
        elif remaining is not None and any(remaining):
            if line.startswith("+"):
                added.append(line[1:]); remaining[1] -= 1
            elif line.startswith("-"):
                removed.append(line[1:]); remaining[0] -= 1
            elif line.startswith(" "):
                remaining[0] -= 1; remaining[1] -= 1
            else:
                raise ValueError("Invalid diff line")
            if min(remaining) < 0:
                raise ValueError("Diff hunk overflow")
        elif not saw_hunk and line.startswith(("--- ", "+++ ", "diff --git ", "index ")):
            continue
        else:
            raise ValueError("Unexpected diff content")
    if remaining and any(remaining):
        raise ValueError("Incomplete diff hunk")
    if diff and not saw_hunk:
        raise ValueError("Missing diff hunks")
    return added, removed


def completed_stats(item, cwd=""):
    changes = item.get("changes")
    parts, files, result_files = [], set(), set()
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Missing file changes")
    for path, change in changes.items():
        if not isinstance(path, str) or not path or not isinstance(change, dict):
            raise ValueError("Invalid file change")
        kind, move = change.get("type"), change.get("move_path")
        if move is not None and (not isinstance(move, str) or not move):
            raise ValueError("Invalid move path")
        if kind in {"add", "delete"}:
            content = change.get("content")
            if not isinstance(content, str):
                raise ValueError("Missing file contents")
            lines = content.splitlines()
            added, removed = (lines, []) if kind == "add" else ([], lines)
        elif kind == "update":
            added, removed = diff_lines(change.get("unified_diff"))
        else:
            raise ValueError("Unknown file change")
        parts.append([path, kind, move, added, removed])
        files.add(path)
        if move:
            files.add(move)
        result_files.add(move or path)
    return {"added": sum(len(p[3]) for p in parts), "removed": sum(len(p[4]) for p in parts),
            "files": sorted(files), "result_files": sorted(result_files),
            "supported": True, "unknown_size": False}, fingerprint(parts, cwd)


class StructuredChanges:
    """Checkpointable correlation state; only fingerprints, IDs and paths persist."""

    def __init__(self, state=None):
        self.state = state if state is not None else {
            "cwd": "", "calls": {}, "cells": {}, "fingerprints": {}, "seen": {}, "ambiguous": [],
        }
        self.claimed = set(self.state["seen"].values())
        self.ambiguous = set(self.state.get("ambiguous", []))

    def start_call(self, call_id, name):
        if name not in {"exec", "apply_patch", "exec_command", "shell", "shell_command"}:
            return
        self.state["calls"] = {k: v for k, v in self.state["calls"].items() if v["open"]}
        self.state["calls"][call_id] = {"open": True, "indices": []}

    def register(self, call_id, index, patch):
        scope = self.state["calls"].get(call_id)
        if scope is not None:
            scope["indices"].append(index)
        self.state["fingerprints"][str(index)] = patch_fingerprint(patch, self.state["cwd"])

    def finish_call(self, call_id, text, wait_cell=None):
        origin = self.state["cells"].get(wait_cell, call_id)
        scope = self.state["calls"].get(origin)
        if scope is None:
            return
        cell = re.search(r"Script running with cell ID\s+([^\s]+)", text)
        if cell:
            self.state["cells"][cell[1]] = origin
        else:
            scope["open"] = False

    def observe(self, item, timestamp, events):
        identity = item.get("id")
        identity = identity if isinstance(identity, str) and identity else None
        if identity in self.state["seen"]:
            return
        try:
            stats, signature = completed_stats(item, self.state["cwd"])
        except (ValueError, TypeError):
            stats = {"added": 0, "removed": 0, "files": [], "result_files": [],
                     "supported": False, "unknown_size": True}
            signature = None
        matches = [i for scope in self.state["calls"].values() for i in scope["indices"]
                   if i not in self.claimed and signature is not None
                   and self.state["fingerprints"].get(str(i)) == signature]
        # Within a call, identical operations are paired by occurrence. Across
        # overlapping calls there is no safe attribution, so retain uncertainty.
        origins = {events[i]["call_id"] for i in matches}
        if len(origins) == 1:
            index = matches[0]
            event = events[index]
            event.update(stats)
        else:
            if matches:
                # One completed item cannot establish which overlapping call
                # succeeded. Count the item once, and do not also count an
                # unlabelled legacy success against any of these candidates.
                self.ambiguous.update(matches)
                self.state["ambiguous"] = sorted(self.ambiguous)
                for i in matches:
                    events[i]["outcome"] = "unknown"
                    events[i].pop("resolved_at", None)
            index = len(events)
            event = {**stats, "timestamp": timestamp, "call_id": "filechange:" + identity if identity else None,
                     "index": 0, "digest": signature or hashlib.sha256(str(identity).encode()).hexdigest(),
                     "direct": False}
            events.append(event)
        status = item.get("status")
        event["outcome"] = ("confirmed" if status == "completed" and stats["supported"] and identity
                            else "failed" if status in {"failed", "declined"} else "unknown")
        if event["outcome"] != "unknown":
            event["resolved_at"] = timestamp
        if identity:
            self.state["seen"][identity] = index
            self.claimed.add(index)

    def owns(self, index):
        return index in self.claimed or index in self.ambiguous
