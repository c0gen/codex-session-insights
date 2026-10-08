"""Only appended complete lines are read during normal refreshes."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .codec import pack, unpack
from .parser import PARSER_VERSION, SessionParser, portable_fact
from .projection import project_segments


def anchor(path, offset):
    with path.open("rb") as stream:
        stream.seek(max(0, offset - 4096))
        return hashlib.sha256(stream.read(min(offset, 4096))).hexdigest()


def refresh(store, progress=None, cancel=None, rebuild=False):
    report = {"files": 0, "changed_files": 0, "bytes_read": 0, "errors": 0}
    sources = [s for s in store.sources() if s["kind"] == "folder" and s["enabled"]]
    for source in sources:
        if not source["root"]:
            continue
        root = Path(source["root"])
        if not root.is_dir():
            with store.connect() as db:
                db.execute("UPDATE sources SET status='Offline',detail='Previously indexed history retained' WHERE id=?", (source["id"],))
            continue
        changed = set()
        def flush_changes():
            with store.lock, store.connect() as db:
                if changed:
                    project_segments(store, db, store.related_segments(db, changed))
                    db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting("data_revision", 0) + 1),))
        try:
            for base, dirs, names in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith(".") or d == ".codex"]
                for name in sorted(names):
                    if cancel and cancel.is_set():
                        flush_changes()
                        return {**report, "cancelled": True}
                    if not name.endswith(".jsonl") or name.startswith("._"):
                        continue
                    path = Path(base) / name
                    report["files"] += 1
                    if progress:
                        progress({**report, "source": source["label"]})
                    try:
                        stat = path.stat()
                        with store.connect() as db:
                            cached = db.execute("SELECT * FROM files WHERE source_id=? AND path=?", (source["id"], str(path))).fetchone()
                        if cached and not rebuild and cached["offset"] == stat.st_size and cached["size"] == stat.st_size and cached["mtime"] == stat.st_mtime_ns:
                            continue
                        state = unpack(cached["state"]) if cached and not rebuild else None
                        if state and (state.get("version") != PARSER_VERSION or stat.st_size < cached["offset"] or anchor(path, cached["offset"]) != cached["anchor"] or (stat.st_size == cached["size"] and stat.st_mtime_ns != cached["mtime"])):
                            state = None
                        parser = SessionParser(state)
                        start_offset = parser.state["offset"]
                        with path.open("rb") as stream:
                            stream.seek(start_offset)
                            while not cancel or not cancel.is_set():
                                line = stream.readline()
                                if not line or not line.endswith(b"\n"):
                                    break
                                parser.consume(line, stream.tell())
                        offset = parser.state["offset"]
                        fact = parser.fact()
                        with store.lock, store.connect() as db:
                            db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)", (source["id"], str(path), offset, stat.st_mtime_ns, stat.st_size, anchor(path, offset), pack(parser.checkpoint())))
                            if fact:
                                fact = portable_fact(fact)
                                store.put_candidate(db, source["id"], fact)
                                if store.choose_canonical(db, fact["segment_id"]):
                                    changed.add(fact["segment_id"])
                        report["bytes_read"] += offset - start_offset
                        report["changed_files"] += 1
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        report["errors"] += 1
                        with store.connect() as db:
                            db.execute("UPDATE sources SET detail=? WHERE id=?", ("Some session files could not be indexed: " + type(exc).__name__, source["id"]))
            flush_changes()
            with store.lock, store.connect() as db:
                db.execute("UPDATE sources SET status='Ready',updated=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), source["id"]))
        except OSError:
            report["errors"] += 1
    return report


def register_defaults(store):
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    for name in ("sessions", "archived_sessions"):
        store.add_source(home / name, "This computer" if name == "sessions" else "Archived sessions")
