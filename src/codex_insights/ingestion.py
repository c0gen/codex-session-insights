"""Only appended complete lines are read during normal refreshes."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .codec import pack, unpack
from .index_failures import FileFailures
from .parser import PARSER_VERSION, portable_fact
from .providers import adapter
from .projection import ensure_projection, project_segments


def anchor(path, offset):
    with path.open("rb") as stream:
        stream.seek(max(0, offset - 4096))
        return hashlib.sha256(stream.read(min(offset, 4096))).hexdigest()


def refresh(store, progress=None, cancel=None, rebuild=False, automatic=False):
    ensure_projection(store)
    report = {"files": 0, "changed_files": 0, "bytes_read": 0, "errors": 0, "skipped_errors": 0}
    def flush_changes():
        # Queue entries commit with checkpoints; a restart cannot skip an edit
        # whose canonical facts were saved before its projection was rebuilt.
        with store.lock, store.connect() as db:
            changed = {row[0] for row in db.execute("SELECT segment_id FROM projection_queue")}
            if changed:
                project_segments(store, db, store.related_segments(db, changed))
                db.execute("DELETE FROM projection_queue")
                db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting("data_revision", 0) + 1),))
    flush_changes()
    sources = [s for s in store.sources() if s["kind"] in {"folder", "bridge"} and s["enabled"]]
    for source in sources:
        if not source["root"]:
            continue
        root = Path(source["root"])
        if source.get('format') == 'antigravity_legacy':
            with store.connect() as db:
                db.execute("UPDATE sources SET status='Collection disabled',detail='Encrypted archive collection is retired. Previously indexed history is retained; use public transcripts and official hooks.' WHERE id=?", (source['id'],))
            continue
        provider_adapter = adapter(source.get("provider", "codex"))
        parser_version = PARSER_VERSION if provider_adapter.provider == 'codex' else provider_adapter.version
        if not root.is_dir():
            with store.connect() as db:
                db.execute("UPDATE sources SET status='Offline',detail='Previously indexed history retained' WHERE id=?", (source["id"],))
            continue
        with store.connect() as db:
            checkpoints = {row['path']:dict(row) for row in db.execute('SELECT path,offset,mtime,size,anchor,parser_version FROM files WHERE source_id=?',(source['id'],))}
        failures = FileFailures(store, source["id"], parser_version)
        discovered_files = 0
        try:
            for path in provider_adapter.discover(root, source["kind"]):
                discovered_files += 1
                if cancel and cancel.is_set():
                    flush_changes()
                    failures.summarize()
                    return {**report, "cancelled": True}
                report["files"] += 1
                if progress:
                    progress({**report, "source": source["label"]})
                stat, parser = None, None
                try:
                    stat = path.stat()
                    if failures.skip(path, stat, automatic and not rebuild):
                        report["skipped_errors"] += 1
                        continue
                    cached = checkpoints.get(str(path))
                    current = cached and cached["parser_version"] == parser_version
                    # A stable incomplete final line cannot become complete
                    # until the file changes. Avoid re-packing its entire
                    # checkpoint on every fallback scan while it is idle.
                    if (current and not rebuild and str(path) not in failures.failed
                            and cached["size"] == stat.st_size and cached["mtime"] == stat.st_mtime_ns):
                        continue
                    state = None
                    if current and not rebuild:
                        with store.connect() as db:
                            saved=db.execute('SELECT state FROM files WHERE source_id=? AND path=?',(source['id'],str(path))).fetchone()
                        state=unpack(saved[0]) if saved else None
                    if state and (state.get("version") != parser_version or stat.st_size < cached["offset"] or anchor(path, cached["offset"]) != cached["anchor"] or (stat.st_size == cached["size"] and stat.st_mtime_ns != cached["mtime"])):
                        state = None
                    from .providers.antigravity import read_metadata
                    metadata = read_metadata(store.directory, path) if provider_adapter.provider == 'antigravity' else None
                    parser = provider_adapter.parser(state, path, source["kind"], metadata=metadata)
                    start_offset = parser.state["offset"]
                    with path.open("rb") as stream:
                        stream.seek(start_offset)
                        while not cancel or not cancel.is_set():
                            line = stream.readline()
                            if not line or not line.endswith(b"\n"):
                                break
                            parser.consume(line, stream.tell())
                    if provider_adapter.provider == 'antigravity' and (path.stat().st_size != stat.st_size or path.stat().st_mtime_ns != stat.st_mtime_ns):
                        raise ValueError('Public transcript changed while reading; retrying on the next refresh')
                    if cancel and cancel.is_set():
                        flush_changes()
                        failures.summarize()
                        return {**report, "cancelled": True}
                    offset = parser.state["offset"]
                    fact = parser.fact()
                    with store.lock, store.connect() as db:
                        db.execute("INSERT OR REPLACE INTO files(source_id,path,offset,mtime,size,anchor,state,parser_version) VALUES(?,?,?,?,?,?,?,?)", (source["id"], str(path), offset, stat.st_mtime_ns, stat.st_size, anchor(path, offset), pack(parser.checkpoint()), parser_version))
                        if fact:
                            fact = portable_fact(fact)
                            store.put_candidate(db, source["id"], fact, parser_version)
                            if store.choose_canonical(db, fact["segment_id"]):
                                db.execute("INSERT OR IGNORE INTO projection_queue VALUES(?)", (fact["segment_id"],))
                    report["bytes_read"] += offset - start_offset
                    report["changed_files"] += 1
                    failures.clear(path)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    report["errors"] += 1
                    failures.record(path, stat, exc, parser.state.get("offset") if parser else None)
                    continue
                if report["changed_files"] % 25 == 0:
                    flush_changes()
            flush_changes()
            failures.summarize(complete=True)
            from .providers.history_status import missing_history
            missing = missing_history(provider_adapter.provider, source["kind"], discovered_files)
            with store.lock, store.connect() as db:
                if missing:
                    db.execute("UPDATE sources SET status=?,detail=?,updated=? WHERE id=?", (
                        missing["status"], missing["detail"], datetime.now(timezone.utc).isoformat(), source["id"]))
                else:
                    db.execute("UPDATE sources SET status='Ready',updated=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), source["id"]))
        except OSError:
            report["errors"] += 1
    return report


def register_defaults(store):
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    for name in ("sessions", "archived_sessions"):
        store.add_source(home / name, "This computer" if name == "sessions" else "Archived sessions")


def register_provider_defaults(store):
    home = Path.home()
    from .providers.profiles import register_claude_profiles
    register_claude_profiles(store)
    for application in ("antigravity", "antigravity-cli", "antigravity-ide"):
        store.add_source(home / ".gemini" / application / "brain", "Antigravity · " + application, "antigravity")
    store.add_source(store.directory / "bridge" / "events", "Antigravity · passive hooks", "antigravity", "bridge")
