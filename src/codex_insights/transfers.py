"""Versioned full snapshots with atomic, idempotent replacement on import."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .codec import dumps, loads, timestamp, unpack
from .parser import portable_fact, repository
from .projection import project_segments

FORMAT_VERSION = 1
MAX_BYTES = 4 * 1024**3
MAX_LINE = 256 * 1024**2
FACT_KEYS = set("id segment_id metadata_timestamp project_id project_label session_source parent_session_id spawn_timestamp history_mode history_base raw_token_trace messages change_events activity tools contexts prefix_hash byte_count record_count boundaries last_event_ordinal parse_errors record_boundaries proofs".split())


def validate_fact(fact):
    if not isinstance(fact, dict) or set(fact) - FACT_KEYS:
        raise ValueError("Unsupported fact fields; export with a compatible version")
    required = {"id", "segment_id", "metadata_timestamp", "project_id", "project_label", "session_source", "raw_token_trace", "messages", "change_events", "activity", "prefix_hash", "byte_count", "record_count", "proofs"}
    if not required <= set(fact):
        raise ValueError("Incomplete session facts")
    for field in ("segment_id", "prefix_hash"):
        if not isinstance(fact[field], str) or not re.fullmatch(r"[0-9a-f]{64}", fact[field]):
            raise ValueError("Invalid session fingerprint")
    for field in ("id", "project_id", "project_label"):
        if not isinstance(fact[field], str) or len(fact[field]) > 500:
            raise ValueError("Invalid session identity")
    if fact["project_id"].startswith("https:") and repository(fact["project_id"]) != fact["project_id"]:
        raise ValueError("Repository identity contains unsupported URL components")
    if not fact["project_id"].startswith(("https://", "workspace:")):
        raise ValueError("Invalid project identity")
    if fact["session_source"] not in {"top_level", "spawned_subagent", "system_subagent"}:
        raise ValueError("Invalid session category")
    for field in ("byte_count", "record_count", "parse_errors"):
        if type(fact.get(field, 0)) is not int or fact.get(field, 0) < 0:
            raise ValueError("Invalid fact count")
    if not timestamp(fact["metadata_timestamp"]):
        raise ValueError("Missing metadata timestamp")
    allowed = {
        "raw_token_trace": set("timestamp ordinal end_byte_offset cumulative_usage last_usage model effort service_tier model_context_window".split()),
        "messages": {"timestamp", "role", "signature", "model"},
        "change_events": set("added removed files supported unknown_size result_files timestamp call_id index digest outcome direct resolved_at model".split()),
        "contexts": {"timestamp", "model", "effort", "service_tier"},
        "boundaries": {"end_byte_offset", "ordinal", "model", "effort", "service_tier", "usage"},
    }
    for name, keys in allowed.items():
        if not isinstance(fact.get(name, []), list):
            raise ValueError("Invalid fact array")
        for item in fact.get(name, []):
            if not isinstance(item, dict) or set(item) - keys:
                raise ValueError("Unsupported portable event fields")
            if "timestamp" in item and not timestamp(item["timestamp"]):
                raise ValueError("Invalid event timestamp")
            for key in ("model", "effort", "service_tier", "call_id"):
                if item.get(key) is not None and (not isinstance(item[key], str) or len(item[key]) > 200):
                    raise ValueError("Invalid event label")
            for key in ("added", "removed"):
                if key in item and (type(item[key]) is not int or item[key] < 0):
                    raise ValueError("Invalid edit count")
            for key in ("files", "result_files"):
                if key in item and any(not re.fullmatch(r"file:[0-9a-f]{64}", p) for p in item[key]):
                    raise ValueError("Portable edits must contain path hashes")
    for message in fact["messages"]:
        if message.get("role") not in {"user", "assistant"} or not re.fullmatch(r"[0-9a-f]{64}", message.get("signature", "")):
            raise ValueError("Invalid portable message")
    for event in fact["raw_token_trace"]:
        for key in ("cumulative_usage", "last_usage"):
            usage = event.get(key)
            if usage is not None and (not isinstance(usage, dict) or set(usage) - set("input_tokens cached_input_tokens cache_write_input_tokens output_tokens reasoning_output_tokens total_tokens".split()) or any(type(v) is not int or v < 0 for v in usage.values())):
                raise ValueError("Invalid token counters")
    return fact


def export_snapshot(store, destination, label="This computer", progress=None, cancel=None):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    revision = store.setting("export_revision", 0) + 1
    exporter_id = store.setting("exporter_id")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        facts_path = Path(temporary) / "facts.jsonl"
        checksum, count = hashlib.sha256(), 0
        with store.lock, store.connect() as db, facts_path.open("wb") as output:
            # Canonical local candidates only: never recirculate imported snapshots.
            # Select locally observed facts even when a longer imported copy is canonical.
            # One candidate per segment; the importer will verify all copy prefixes.
            rows = db.execute("SELECT c.segment_id,c.fact FROM candidates c JOIN sources s ON s.id=c.source_id LEFT JOIN canonical k ON k.segment_id=c.segment_id WHERE s.kind='folder' AND s.enabled=1 ORDER BY c.segment_id,CASE WHEN c.source_id=k.source_id THEN 0 ELSE 1 END,c.record_count DESC,c.source_id")
            previous = None
            for row in rows:
                if cancel and cancel.is_set():
                    raise InterruptedError('Export cancelled')
                if row[0] == previous:
                    continue
                previous = row[0]
                fact = validate_fact(unpack(row[1]))
                line = (dumps(fact) + "\n").encode("utf-8")
                output.write(line); checksum.update(line); count += 1
                if progress and count % 50 == 0:
                    progress({'sessions':count,'phase':'Exporting usage facts'})
        manifest = {"format": "codex-session-insights", "format_version": FORMAT_VERSION,
                    "exporter_version": __version__, "exporter_id": exporter_id, "revision": revision,
                    "label": str(label)[:200], "created_at": datetime.now(timezone.utc).isoformat(),
                    "fact_count": count, "facts_sha256": checksum.hexdigest(), "conversation_content": False}
        archive = Path(temporary) / "snapshot.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            bundle.write(facts_path, "facts.jsonl")
        os.replace(archive, destination)
    store.set_setting("export_revision", revision)
    return {"path": str(destination), "sessions": count, "bytes": destination.stat().st_size, "revision": revision}


def import_snapshot(store, path, progress=None, cancel=None):
    path = Path(path).resolve()
    with zipfile.ZipFile(path) as bundle:
        if sorted(bundle.namelist()) != ["facts.jsonl", "manifest.json"]:
            raise ValueError("A snapshot must contain exactly manifest.json and facts.jsonl")
        if bundle.getinfo("manifest.json").file_size > 64 * 1024 or bundle.getinfo("facts.jsonl").file_size > MAX_BYTES:
            raise ValueError("Snapshot exceeds the supported size limit")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("format") != "codex-session-insights" or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError("Unsupported snapshot version; update the app or exporter")
        exporter = manifest.get("exporter_id")
        if not isinstance(exporter, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", exporter):
            raise ValueError("Invalid exporter identity")
        revision = manifest.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("Invalid snapshot revision")
        source_id = "import:" + exporter
        existing = next((s for s in store.sources() if s["id"] == source_id), None)
        checksum = hashlib.sha256()
        with bundle.open("facts.jsonl") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != manifest.get("facts_sha256"):
            raise ValueError("Snapshot checksum does not match")
        if existing and revision <= existing["revision"]:
            return {"status": "unchanged", "revision": existing["revision"]}
        # Back up the exact accepted input, not any extracted paths.
        backups = store.directory / "imports"
        backups.mkdir(exist_ok=True)
        backup = backups / (exporter + "-" + str(revision) + ".codex-insights")
        with store.lock, store.connect() as db:
            segments = {r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=?", (source_id,))}
            previous_sessions={r[0] for r in db.execute("SELECT session_id FROM candidates WHERE source_id=?",(source_id,))}
            db.execute("DELETE FROM candidates WHERE source_id=?", (source_id,))
            db.execute("INSERT INTO sources(id,label,kind,revision,status,updated) VALUES(?,?,'import',?,'Imported',?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,revision=excluded.revision,status=excluded.status,updated=excluded.updated", (
                source_id, str(manifest.get("label") or "Imported computer")[:200], revision, manifest.get("created_at")))
            count = 0
            seen = set()
            with bundle.open("facts.jsonl") as stream:
                while True:
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if cancel and cancel.is_set():
                        raise InterruptedError('Import cancelled')
                    if len(line) > MAX_LINE or not line.endswith(b"\n"):
                        raise ValueError("Invalid or oversized fact record")
                    fact = validate_fact(loads(line.decode("utf-8")))
                    if fact["segment_id"] in seen:
                        raise ValueError("Duplicate session segment in snapshot")
                    seen.add(fact["segment_id"]); segments.add(fact["segment_id"])
                    store.put_candidate(db, source_id, fact); count += 1
                    if progress and count % 50 == 0:
                        progress({'sessions':count,'phase':'Reading snapshot facts'})
            if count != manifest.get("fact_count"):
                raise ValueError("Snapshot session count does not match")
            changed = {s for s in segments if store.choose_canonical(db, s)}
            if progress:
                progress({'sessions':count,'phase':'Updating dashboard index'})
            project_segments(store, db, store.related_segments(db, changed, previous_sessions))
            db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting("data_revision", 0) + 1),))
            shutil.copyfile(path, backup)
        return {"status": "imported", "sessions": count, "revision": revision}
