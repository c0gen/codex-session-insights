"""SQLite source catalog, incremental checkpoints and canonical fact selection."""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .codec import pack, unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,label TEXT NOT NULL,kind TEXT NOT NULL,
 root TEXT,enabled INTEGER NOT NULL DEFAULT 1,revision INTEGER DEFAULT 0,status TEXT DEFAULT 'Ready',
 updated TEXT, detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS files(source_id TEXT,path TEXT,offset INTEGER,mtime INTEGER,size INTEGER,
 anchor TEXT,state BLOB,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS candidates(source_id TEXT,segment_id TEXT,session_id TEXT,parent_id TEXT,
 record_count INTEGER,trace_count INTEGER,byte_count INTEGER,prefix_hash TEXT,fact BLOB,
 PRIMARY KEY(source_id,segment_id));
CREATE INDEX IF NOT EXISTS candidates_session ON candidates(session_id);
CREATE INDEX IF NOT EXISTS candidates_parent ON candidates(parent_id);
CREATE TABLE IF NOT EXISTS canonical(segment_id TEXT PRIMARY KEY,source_id TEXT,session_id TEXT,parent_id TEXT,
 project_id TEXT,project_label TEXT,category TEXT,last_active TEXT,trace_count INTEGER,fact BLOB,diagnostic TEXT);
CREATE INDEX IF NOT EXISTS canonical_session ON canonical(session_id,trace_count);
CREATE TABLE IF NOT EXISTS records(event_id TEXT PRIMARY KEY,segment_id TEXT,session_id TEXT,source_id TEXT,
 project_id TEXT,kind TEXT,ts TEXT,day TEXT,hour INTEGER,weekday INTEGER,model TEXT,effort TEXT,tier TEXT,
 total INTEGER DEFAULT 0,input INTEGER DEFAULT 0,cached INTEGER DEFAULT 0,writes INTEGER DEFAULT 0,
 output INTEGER DEFAULT 0,reasoning INTEGER DEFAULT 0,cost REAL,priced INTEGER DEFAULT 0,
 prompts INTEGER DEFAULT 0,added INTEGER DEFAULT 0,removed INTEGER DEFAULT 0,
 unknown INTEGER DEFAULT 0,unsupported INTEGER DEFAULT 0,unknown_size INTEGER DEFAULT 0,resolved_at TEXT);
CREATE INDEX IF NOT EXISTS records_time ON records(ts);
CREATE INDEX IF NOT EXISTS records_day ON records(day);
CREATE INDEX IF NOT EXISTS records_segment ON records(segment_id);
CREATE INDEX IF NOT EXISTS records_project ON records(project_id,ts);
CREATE INDEX IF NOT EXISTS records_model ON records(model,ts);
"""


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "insights.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("PRAGMA journal_mode=WAL")
            if not db.execute("SELECT 1 FROM settings WHERE key='exporter_id'").fetchone():
                db.execute("INSERT INTO settings VALUES('exporter_id',?)", (json.dumps(str(uuid.uuid4())),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def sources(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT s.*, (SELECT count(*) FROM candidates c WHERE c.source_id=s.id) AS segments FROM sources s ORDER BY kind,label")]

    def add_source(self, root, label=None):
        root = str(Path(root).expanduser().resolve())
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT id FROM sources WHERE root=? AND kind='folder'", (root,)).fetchone()
            if existing:
                return existing[0]
            sid = str(uuid.uuid4())
            db.execute("INSERT INTO sources(id,label,kind,root) VALUES(?,?,'folder',?)", (sid, label or Path(root).name or "Session folder", root))
            return sid

    def put_candidate(self, db, source_id, fact):
        db.execute("INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?,?,?,?,?)", (
            source_id, fact["segment_id"], fact["id"], fact.get("parent_session_id"), fact["record_count"],
            len(fact["raw_token_trace"]), fact["byte_count"], fact["prefix_hash"], pack(fact)))

    def choose_canonical(self, db, segment_id):
        rows = db.execute("SELECT c.* FROM candidates c JOIN sources s ON s.id=c.source_id WHERE c.segment_id=? AND s.enabled=1 ORDER BY c.record_count DESC,c.source_id", (segment_id,)).fetchall()
        old = db.execute("SELECT * FROM canonical WHERE segment_id=?", (segment_id,)).fetchone()
        if not rows:
            db.execute("DELETE FROM canonical WHERE segment_id=?", (segment_id,))
            db.execute("DELETE FROM records WHERE segment_id=?", (segment_id,))
            return True
        winner = rows[0]
        fact = unpack(winner["fact"])
        conflicting = []
        for row in rows[1:]:
            shorter = unpack(row["fact"])
            if fact.get("proofs", {}).get(str(shorter["byte_count"])) != shorter["prefix_hash"]:
                conflicting.append(row["source_id"])
        if conflicting and old and any(r["source_id"] == old["source_id"] for r in rows):
            winner = next(r for r in rows if r["source_id"] == old["source_id"])
            fact = unpack(winner["fact"])
        diagnostic = json.dumps({"conflicts": conflicting, "parse_errors": fact.get("parse_errors", 0)})
        changed = not old or old["fact"] != winner["fact"] or old["source_id"] != winner["source_id"]
        if not changed:
            db.execute("UPDATE canonical SET diagnostic=? WHERE segment_id=?", (diagnostic, segment_id))
            return False
        db.execute("INSERT OR REPLACE INTO canonical VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            segment_id, winner["source_id"], fact["id"], fact.get("parent_session_id"), fact["project_id"],
            fact["project_label"], fact["session_source"], None, len(fact["raw_token_trace"]), winner["fact"], diagnostic))
        return True

    def related_segments(self, db, changed, removed_session_ids=()):
        result = set(changed)
        todo = list(changed)
        visited = set()
        for sid in removed_session_ids:
            for child in db.execute("SELECT segment_id FROM canonical WHERE parent_id=?", (sid,)):
                if child[0] not in result:
                    result.add(child[0]); todo.append(child[0])
        while todo:
            segment = todo.pop()
            row = db.execute("SELECT session_id FROM canonical WHERE segment_id=?", (segment,)).fetchone()
            if not row or row[0] in visited:
                continue
            visited.add(row[0])
            for child in db.execute("SELECT segment_id FROM canonical WHERE parent_id=?", (row[0],)):
                if child[0] not in result:
                    result.add(child[0]); todo.append(child[0])
        return result

    def forget_source(self, source_id):
        with self.lock, self.connect() as db:
            segments = [r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=?", (source_id,))]
            db.execute("DELETE FROM files WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM candidates WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            return segments
