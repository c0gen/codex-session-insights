"""Headless bridge: stdin only, no credentials, provider requests or UI imports."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..codec import digest
from ..paths import default_directory
from ..parser import project_identity
from .allowances import normalize
from .bridge_io import MAX_INPUT, MAX_HISTORY, atomic_write, locked, write_json


def hook_record(payload, event, now):
    sid = payload.get("conversationId")
    if not isinstance(sid, str) or not sid or len(sid) > 400:
        return None
    workspaces = payload.get("workspacePaths")
    cwd = workspaces[0] if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str) else ""
    model = payload.get("modelName")
    record = {"bridge_schema": 1, "conversationId": sid, "timestamp": now.isoformat(),
              "project": project_identity({"cwd": cwd}), "modelName": model[:200] if isinstance(model, str) else None}
    # Only a completed tool with an explicit success result proves an edit.
    tool = payload.get("toolCall")
    if event != "PostToolUse" or not isinstance(tool, dict) or payload.get("error") != "":
        return record
    args = tool.get("args")
    if not isinstance(args, dict):
        return record
    pairs = []
    name = tool.get("name")
    if name == "write_to_file" and args.get("Overwrite") is False and isinstance(args.get("CodeContent"), str):
        pairs = [("", args["CodeContent"])]
    elif name == "replace_file_content" and args.get("AllowMultiple") is False:
        pairs = [(args.get("TargetContent"), args.get("ReplacementContent"))]
    elif name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if isinstance(chunks, list) and all(isinstance(c, dict) and c.get("AllowMultiple") is False for c in chunks):
            pairs = [(c.get("TargetContent"), c.get("ReplacementContent")) for c in chunks]
    if not pairs or any(not isinstance(a, str) or not isinstance(b, str) for a, b in pairs):
        return record
    if sum(len(a) + len(b) for a, b in pairs) > 256 * 1024 or sum(a.count("\n") + b.count("\n") for a, b in pairs) > 2000:
        return record
    import difflib
    added = removed = 0
    for old, new in pairs:
        for line in difflib.ndiff(old.splitlines(), new.splitlines()):
            added += line.startswith("+ ")
            removed += line.startswith("- ")
    identity = digest([sid, payload.get("stepIdx"), name])
    record["edit"] = {"timestamp": now.isoformat(), "call_id": identity,
                      "added": added, "removed": removed, "files": [], "result_files": [],
                      "supported": True, "unknown_size": False, "outcome": "confirmed",
                      "index": 0, "digest": identity, "direct": True, "model": record["modelName"]}
    return record


def receive(directory, provider, mode, payload, event=None, now=None):
    if not isinstance(payload, dict) or payload.get("bridge_schema", 1) != 1:
        return
    now = now or datetime.now(timezone.utc)
    target = Path(directory) / "bridge"
    with locked(target):
        # Local discovery metadata is private and never part of portable facts.
        # Accept only the documented public transcript filename/directory.
        reference = payload.get("transcriptPath") or payload.get("transcript_path")
        if provider == "antigravity" and isinstance(reference, str) and len(reference) < 4096:
            path = Path(reference).expanduser()
            if path.is_absolute() and path.name == "transcript.jsonl" and path.parent.name == "logs" and path.parent.parent.name == ".system_generated":
                registry_path = target / "transcript-references.json"
                try:
                    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() and registry_path.stat().st_size <= 4 * MAX_INPUT else {}
                except (OSError, ValueError):
                    registry = {}
                if isinstance(registry, dict) and len(registry) < 10000:
                    registry[digest(str(path))] = str(path)
                    if len(json.dumps(registry)) <= 4 * MAX_INPUT:
                        write_json(registry_path, registry)
                    metadata_path = target / 'transcript-metadata.json'
                    try:
                        metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() and metadata_path.stat().st_size <= MAX_INPUT else {}
                    except (OSError, ValueError):
                        metadata = {}
                    if isinstance(metadata, dict) and len(metadata) < 10000:
                        workspaces = payload.get('workspacePaths')
                        cwd = workspaces[0] if isinstance(workspaces, list) and workspaces and isinstance(workspaces[0], str) else payload.get('cwd', '')
                        model = payload.get('modelName')
                        if not model and isinstance(payload.get('model'), dict):
                            model = payload['model'].get('id')
                        metadata[digest(str(path))] = {'project': project_identity({'cwd': cwd if isinstance(cwd, str) else ''}),
                                                      'modelName': model[:200] if isinstance(model, str) else None}
                        if len(json.dumps(metadata)) <= MAX_INPUT:
                            write_json(metadata_path, metadata)
                    (target / "events").mkdir(exist_ok=True, mode=0o700)
        if mode == "status":
            write_json(target / (provider + "-allowance.json"), normalize(provider, payload, now.timestamp()))
        elif provider == "antigravity" and event in {"PostToolUse", "PostInvocation"}:
            record = hook_record(payload, event, now)
            if record:
                events = target / "events" / (digest(record["conversationId"]) + ".jsonl")
                if events.exists() and events.stat().st_size >= MAX_HISTORY:
                    return
                history = events.read_bytes() if events.exists() else b""
                if len(history) >= MAX_HISTORY - MAX_INPUT:
                    return  # Bounded storage; never silently rotate accounted history.
                line = json.dumps(record, separators=(",", ":")).encode() + b"\n"
                atomic_write(events, history + line)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=default_directory())
    parser.add_argument("--provider", choices=("claude_code", "antigravity"), required=True)
    parser.add_argument("--mode", choices=("status", "hook"), required=True)
    parser.add_argument("--event", choices=("PostToolUse", "PostInvocation"))
    parser.add_argument("--previous-file", type=Path)
    args = parser.parse_args(argv)
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    try:
        if len(raw) <= MAX_INPUT:
            receive(args.data_dir, args.provider, args.mode, json.loads(raw), args.event)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Passive hooks never fail provider execution.
    if args.mode == "hook":
        print("{}")  # Documented neutral PostToolUse / PostInvocation response.
    elif args.previous_file:
        try:
            previous = json.loads(args.previous_file.read_text(encoding="utf-8"))
            command = previous.get("command") if isinstance(previous, dict) else None
            if isinstance(command, str) and command:
                subprocess.run(command, shell=True, input=raw, stdout=sys.stdout,
                               stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
