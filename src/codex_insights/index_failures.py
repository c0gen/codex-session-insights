"""Remember failed file signatures and write diagnostics without session text."""
import json
import traceback
from datetime import datetime, timezone

from .parser import PARSER_VERSION


class FileFailures:
    def __init__(self, store, source_id, parser_version=None):
        self.parser_version = PARSER_VERSION if parser_version is None else parser_version
        self.store, self.source_id = store, source_id
        self.log = store.directory / "indexing-errors.jsonl"
        with store.connect() as db:
            self.failed = {row["path"]: dict(row) for row in db.execute(
                "SELECT * FROM file_failures WHERE source_id=?", (source_id,))}
        self.seen = set()

    def skip(self, path, stat, automatic):
        key = str(path)
        self.seen.add(key)
        failure = self.failed.get(key)
        return bool(automatic and failure and failure["size"] == stat.st_size
                    and failure["mtime"] == stat.st_mtime_ns
                    and failure["parser_version"] == self.parser_version)

    def record(self, path, stat, error, offset=None):
        key = str(path)
        self.seen.add(key)
        stamp = datetime.now(timezone.utc).isoformat()
        record = {"time": stamp, "path": key, "error_type": type(error).__name__,
                  "parser_version": self.parser_version, "byte_offset": offset,
                  "frames": [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                             for frame in traceback.extract_tb(error.__traceback__)]}
        diagnostic = str(self.log)
        try:
            if self.log.exists() and self.log.stat().st_size >= 1024 * 1024:
                self.log.replace(self.log.with_name("indexing-errors.previous.jsonl"))
            with self.log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError:
            diagnostic = ""
        failure = {"path": key, "size": stat.st_size if stat else None,
                   "mtime": stat.st_mtime_ns if stat else None, "parser_version": self.parser_version,
                   "error_type": type(error).__name__, "diagnostic": diagnostic, "updated": stamp}
        with self.store.lock, self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO file_failures VALUES(?,?,?,?,?,?,?,?)",
                       (self.source_id, key, failure["size"], failure["mtime"], self.parser_version,
                        failure["error_type"], diagnostic, stamp))
        self.failed[key] = failure

    def clear(self, path):
        key = str(path)
        if key in self.failed:
            with self.store.lock, self.store.connect() as db:
                db.execute("DELETE FROM file_failures WHERE source_id=? AND path=?", (self.source_id, key))
            del self.failed[key]

    def summarize(self, complete=False):
        if complete:
            for key in set(self.failed) - self.seen:
                self.clear(key)
        count = len(self.failed)
        if count:
            kinds = ", ".join(sorted({value["error_type"] for value in self.failed.values()}))
            detail = f"{count} session file{'s' if count != 1 else ''} could not be indexed ({kinds})."
            if any(value["diagnostic"] for value in self.failed.values()):
                detail += f" Details: {self.log}"
        else:
            detail = ""
        with self.store.lock, self.store.connect() as db:
            old = db.execute("SELECT detail FROM sources WHERE id=?", (self.source_id,)).fetchone()
            if old and old[0] != detail:
                db.execute("UPDATE sources SET detail=? WHERE id=?", (detail, self.source_id))
                revision = self.store.setting("data_revision", 0) + 1
                db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(revision),))
