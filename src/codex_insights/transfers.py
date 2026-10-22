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
from .codec import digest, dumps, loads, timestamp, unpack
from .parser import portable_fact, repository
from .projection import ensure_projection, project_segments

FORMAT_VERSION = 6
MAX_BYTES = 4 * 1024**3
MAX_LINE = 256 * 1024**2
FACT_KEYS = set("provider id segment_id metadata_timestamp project_id project_label session_source parent_session_id spawn_timestamp history_mode history_base raw_token_trace messages change_events activity tools contexts prefix_hash byte_count record_count boundaries last_event_ordinal parse_errors record_boundaries proofs".split())
FACT_KEYS |= {'provenance','coverage','snapshot_mode','subagent_relationships','record_hash','record_proofs'}


def validate_fact(fact, version=FORMAT_VERSION):
    if not isinstance(fact, dict) or set(fact) - FACT_KEYS:
        raise ValueError("Unsupported fact fields; export with a compatible version")
    for field in ('record_hash', 'record_proofs'):
        if field in fact and version < 6:
            raise ValueError('Normalized history proofs require transfer v6')
    if 'record_hash' in fact or 'record_proofs' in fact:
        count, proofs = fact.get('record_count'), fact.get('record_proofs')
        if (not isinstance(fact.get('record_hash'), str) or not re.fullmatch('[0-9a-f]{64}', fact['record_hash'])
                or type(count) is not int or count < 1 or not isinstance(proofs, dict)
                or any(not isinstance(k, str) or not k.isdigit() or not 1 <= int(k) <= count
                       or not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for k, v in proofs.items())
                or len(proofs) != count or proofs.get(str(count)) != fact['record_hash']):
            raise ValueError('Invalid normalized history proofs')
    from .providers import adapter
    provider = fact.get("provider", "codex")
    legacy = fact.get('snapshot_mode') == 'complete_binary'
    public_steps = provider == 'antigravity' and fact.get('history_mode') == 'antigravity_steps'
    if public_steps and version < 4:
        raise ValueError('Public step accounting with unavailable components requires transfer v4')
    if set(fact) & {'provenance','coverage','snapshot_mode','subagent_relationships'} and (not legacy or version < 3):
        raise ValueError('Legacy facts require transfer v3')
    adapter(provider)
    if provider != "codex" and not str(fact.get("id", "")).startswith(provider + ":"):
        raise ValueError("Invalid provider session namespace")
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
    if provider != "codex":
        sid = fact["id"][len(provider) + 1:]
        if fact["segment_id"] not in {digest([provider, sid, k]) for k in (("legacy",) if legacy else ("hook", "transcript"))}:
            raise ValueError("Invalid provider segment namespace")
        parent = fact.get("parent_session_id")
        if parent is not None and (not isinstance(parent, str) or not parent.startswith(provider + ":")):
            raise ValueError("Invalid provider parent namespace")
    for field in ("byte_count", "record_count", "parse_errors"):
        if type(fact.get(field, 0)) is not int or fact.get(field, 0) < 0:
            raise ValueError("Invalid fact count")
    if not timestamp(fact["metadata_timestamp"]):
        raise ValueError("Missing metadata timestamp")
    allowed = {
        "raw_token_trace": set("timestamp ordinal end_byte_offset cumulative_usage last_usage model effort service_tier speed inference_geo model_context_window response_id cache_creation recorded_components invocation_id model_enum".split()),
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
        if set(event) & {"speed", "inference_geo"} and (provider != "claude_code" or version < 5):
            raise ValueError("Claude pricing metadata requires transfer v5")
        if provider == "claude_code":
            from .providers.claude_pricing import METADATA_VALUES
            for key, values in METADATA_VALUES.items():
                if key in event and (not isinstance(event[key], str) or event[key] not in values):
                    raise ValueError("Invalid Claude pricing metadata")
        if provider != "codex":
            if not isinstance(event.get("response_id"), str) or not re.fullmatch(r"[0-9a-f]{64}", event["response_id"]):
                raise ValueError("Missing stable response identity")
            creation = event.get("cache_creation")
            if creation is not None and (not isinstance(creation, dict) or set(creation) != {"ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"} or any(type(v) is not int or v < 0 for v in creation.values())):
                raise ValueError("Invalid cache creation counters")
        for key in ("cumulative_usage", "last_usage"):
            usage = event.get(key)
            if usage is not None and (not isinstance(usage, dict) or set(usage) - set("input_tokens cached_input_tokens cache_write_input_tokens output_tokens reasoning_output_tokens total_tokens".split()) or any((v is None and not (legacy or public_steps)) or (v is not None and (type(v) is not int or v < 0)) for v in usage.values())):
                raise ValueError("Invalid token counters")
        if not legacy and set(event) & {'recorded_components','invocation_id','model_enum'}:
            raise ValueError('Recorded legacy components require transfer v3')
        if legacy and not re.fullmatch('[0-9a-f]{64}', event.get('invocation_id','')):
            raise ValueError('Invalid invocation identity')
        if legacy and (type(event.get('model_enum')) is not int or event['model_enum'] < 0 or event['model_enum'] > 2**31 - 1):
            raise ValueError('Invalid legacy model enum')
    if legacy:
        from .providers.legacy.transfer import validate_legacy
        validate_legacy(fact)
    fact.setdefault("provider", "codex")
    return fact


def export_snapshot(store, destination, label="This computer", progress=None, cancel=None):
    if cancel and cancel.is_set():
        raise InterruptedError('Export cancelled')
    ensure_projection(store)
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    revision = store.setting("export_revision", 0) + 1
    exporter_id = store.setting("exporter_id")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        facts_path = Path(temporary) / "facts.jsonl"
        checksum, count = hashlib.sha256(), 0
        with store.lock, store.connect() as db, facts_path.open("wb") as output:
            from .history_transfers import envelope, validate
            # Only enabled locally observed histories; imported alternatives and
            # choices must never be recirculated to another exporter identity.
            rows = db.execute("SELECT DISTINCT c.segment_id FROM candidates c JOIN sources s ON s.id=c.source_id WHERE s.kind IN ('folder','bridge') AND s.enabled=1 ORDER BY c.segment_id").fetchall()
            unresolved = 0
            for row in rows:
                if cancel and cancel.is_set():
                    raise InterruptedError('Export cancelled')
                value = validate(envelope(db, row[0]), validate_fact)
                unresolved += value['state'] in {'needs_review', 'awaiting_verification'}
                line = (dumps(value) + "\n").encode("utf-8")
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
        if cancel and cancel.is_set():
            raise InterruptedError('Export cancelled')
        os.replace(archive, destination)
    store.set_setting("export_revision", revision)
    return {"path": str(destination), "sessions": count, "bytes": destination.stat().st_size, "revision": revision, "unresolved_histories": unresolved}


def import_snapshot(store, path, progress=None, cancel=None):
    from .incremental_transfers import import_snapshot as incremental
    return incremental(store, path, progress, cancel)


def _legacy_import_snapshot(store, path, progress=None, cancel=None):
    if getattr(store, 'cooperate', None) and not getattr(store, 'isolated', False):
        from .isolated_jobs import run
        # The normal importer validates the archive and manifest in the private
        # workspace before any accepted source contribution changes.
        with zipfile.ZipFile(path) as archive:
            if archive.getinfo('manifest.json').file_size > 64 * 1024:
                raise ValueError('Snapshot manifest exceeds the supported size limit')
            manifest = json.loads(archive.read('manifest.json'))
        exporter = manifest.get('exporter_id')
        if not isinstance(exporter, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', exporter):
            raise ValueError('Invalid exporter identity')
        def preserve_archive(result, private):
            backups = store.directory / 'imports'
            backups.mkdir(exist_ok=True)
            destination = backups / (exporter + '-' + str(result['revision']) + '.codex-insights')
            with tempfile.NamedTemporaryFile(dir=backups, delete=False) as saved:
                temporary = Path(saved.name)
            try:
                shutil.copyfile(private.directory / 'imports' / destination.name, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        result = run(store, 'import:' + exporter,
                     lambda private, report: _legacy_import_snapshot(private, path, report, cancel), progress, preserve_archive,
                     job_key=str(manifest.get('revision')) + ':' + str(manifest.get('facts_sha256')))
        return result
    ensure_projection(store)
    path = Path(path).resolve()
    with zipfile.ZipFile(path) as bundle:
        if sorted(bundle.namelist()) != ["facts.jsonl", "manifest.json"]:
            raise ValueError("A snapshot must contain exactly manifest.json and facts.jsonl")
        if bundle.getinfo("manifest.json").file_size > 64 * 1024 or bundle.getinfo("facts.jsonl").file_size > MAX_BYTES:
            raise ValueError("Snapshot exceeds the supported size limit")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("format") != "codex-session-insights" or manifest.get("format_version") not in (1, 2, 3, 4, 5, FORMAT_VERSION):
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
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                checksum.update(chunk)
        if checksum.hexdigest() != manifest.get("facts_sha256"):
            raise ValueError("Snapshot checksum does not match")
        if existing and revision <= existing["revision"]:
            return {"status": "unchanged", "revision": existing["revision"]}
        # Identify legacy Claude input before changing the accepted snapshot.
        # Keep the checksum pass first so corrupt inputs never trigger upgrades.
        claude_input, legacy_agents = False, False
        with bundle.open('facts.jsonl') as stream:
            while True:
                line = stream.readline(MAX_LINE + 1)
                if not line:
                    break
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    raise ValueError('Invalid or oversized fact record')
                if not re.search(rb'"provider"\s*:\s*"claude_code"', line):
                    continue
                value = loads(line.decode('utf-8'))
                alternatives = value.get('alternatives', []) if isinstance(value, dict) else []
                entries = ([value.get('accepted', value)] + (alternatives if isinstance(alternatives, list) else [])) if isinstance(value, dict) else []
                for entry in entries:
                    if isinstance(entry, dict) and entry.get('provider') == 'claude_code':
                        claude_input = True
                        legacy_agents |= str(entry.get('id', '')).startswith('claude_code:agent-') and bool(entry.get('parent_session_id'))
        with store.connect() as db:
            previous_recovery = db.execute('SELECT report FROM claude_recovery_sources WHERE source_id=?', (source_id,)).fetchone()
            source_decisions = db.execute("SELECT 1 FROM history_choices h JOIN candidates c ON h.group_id='copy:'||c.segment_id "
                                          "WHERE c.source_id=? AND c.provider='claude_code' AND h.scope=''", (source_id,)).fetchone()
        recover_input = bool(claude_input and (legacy_agents or manifest['format_version'] < 6 or previous_recovery or source_decisions)
                             and (not existing or existing['enabled']))
        if recover_input:
            from .claude_recovery_store import backup as recovery_backup
            recovery_backup(store)
        # Back up the exact accepted input, not any extracted paths.
        backups = store.directory / "imports"
        backups.mkdir(exist_ok=True)
        backup = backups / (exporter + "-" + str(revision) + ".codex-insights")
        with store.lock, store.connect() as db:
            if recover_input:
                from .claude_history_stats import accounted_tokens, baseline
                recovery_report = {'accepted_tokens_before': accounted_tokens(db), 'reopened_choices': 0}
                previous_report = json.loads(previous_recovery[0]) if previous_recovery else {}
                recovery_report.update(prior_included_tokens=previous_report.get('newly_included_tokens', 0),
                                       prior_included_responses=previous_report.get('newly_included_responses', 0),
                                       reopened_choices=previous_report.get('reopened_choices', 0))
                baseline(db, source_id)
            segments = {r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=?", (source_id,))}
            previous_sessions={r[0] for r in db.execute("SELECT session_id FROM candidates WHERE source_id=?",(source_id,))}
            for table in ('history_variants', 'variant_locations', 'history_pending'):
                db.execute('DELETE FROM ' + table + ' WHERE source_id=?', (source_id,))
            db.execute('DELETE FROM history_choices WHERE scope=?', (source_id,))
            db.execute("DELETE FROM candidates WHERE source_id=?", (source_id,))
            db.execute('DELETE FROM transfer_fingerprints WHERE source_id=?', (source_id,))
            db.execute('DELETE FROM transfer_fingerprint_sources WHERE source_id=?', (source_id,))
            db.execute("INSERT INTO sources(id,label,kind,revision,status,updated) VALUES(?,?,'import',?,'Imported',?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,revision=excluded.revision,status=excluded.status,updated=excluded.updated", (
                source_id, str(manifest.get("label") or "Imported computer")[:200], revision, manifest.get("created_at")))
            count = 0
            seen = set()
            providers = set()
            with bundle.open("facts.jsonl") as stream:
                while True:
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if cancel and cancel.is_set():
                        raise InterruptedError('Import cancelled')
                    if len(line) > MAX_LINE or not line.endswith(b"\n"):
                        raise ValueError("Invalid or oversized fact record")
                    value = loads(line.decode("utf-8"))
                    if manifest['format_version'] == 6:
                        from .history_transfers import validate, accept
                        value = validate(value, validate_fact)
                        fact = value['accepted']
                    else:
                        fact = value
                    if manifest["format_version"] == 1:
                        if fact.get("provider", "codex") != "codex":
                            raise ValueError("Version 1 only supports Codex")
                        fact["provider"] = "codex"
                    fact = validate_fact(fact, manifest['format_version'])
                    if fact["segment_id"] in seen:
                        raise ValueError("Duplicate session segment in snapshot")
                    seen.add(fact["segment_id"]); segments.add(fact["segment_id"])
                    providers.add(fact.get("provider", "codex"))
                    if manifest['format_version'] == 6:
                        accept(db, source_id, value)
                    else:
                        store.put_candidate(db, source_id, fact)
                    count += 1
                    if progress and count % 50 == 0:
                        progress({'sessions':count,'phase':'Reading snapshot facts'})
            if count != manifest.get("fact_count"):
                raise ValueError("Snapshot session count does not match")
            db.execute("UPDATE sources SET provider=? WHERE id=?", (next(iter(providers)) if len(providers) == 1 else "mixed" if providers else "codex", source_id))
            if 'claude_code' in providers:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('claude_import_format:' + source_id, json.dumps(manifest['format_version'])))
            else:
                from .claude_recovery_store import retire_verification
                retire_verification(db, source_id, revision)
            if recover_input:
                from .claude_recovery_publish import publish
                incoming_source = dict(db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone())
                publish(store, incoming_source, recovery_report, digest([[], revision]), cancel, progress,
                        manifest['format_version'], connection=db)
            changed = {s for s in segments if store.choose_canonical(db, s)}
            if progress:
                progress({'sessions':count,'phase':'Updating dashboard index'})
            project_segments(store, db, store.related_segments(db, changed, previous_sessions), progress)
            db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting("data_revision", 0) + 1),))
            shutil.copyfile(path, backup)
        return {"status": "imported", "sessions": count, "revision": revision}
