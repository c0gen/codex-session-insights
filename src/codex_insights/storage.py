"""SQLite source catalog, incremental checkpoints and canonical fact selection."""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .codec import pack, unpack
from .buckets import ensure_schema
from . import project_groups

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,label TEXT NOT NULL,kind TEXT NOT NULL,
 root TEXT,enabled INTEGER NOT NULL DEFAULT 1,revision INTEGER DEFAULT 0,status TEXT DEFAULT 'Ready',
 updated TEXT, detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS files(source_id TEXT,path TEXT,offset INTEGER,mtime INTEGER,size INTEGER,
 anchor TEXT,state BLOB,parser_version INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS projection_queue(segment_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS file_failures(source_id TEXT,path TEXT,size INTEGER,mtime INTEGER,
 parser_version INTEGER,error_type TEXT,diagnostic TEXT,updated TEXT,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS candidates(source_id TEXT,segment_id TEXT,session_id TEXT,parent_id TEXT,
 record_count INTEGER,trace_count INTEGER,byte_count INTEGER,prefix_hash TEXT,fact BLOB,
 parser_version INTEGER NOT NULL DEFAULT 0,same_source_conflict INTEGER NOT NULL DEFAULT 0,
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
            for table in ("files", "candidates"):
                if "parser_version" not in {row["name"] for row in db.execute("PRAGMA table_info(" + table + ")")}:
                    db.execute("ALTER TABLE " + table + " ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 0")
            if "same_source_conflict" not in {row["name"] for row in db.execute("PRAGMA table_info(candidates)")}:
                db.execute("ALTER TABLE candidates ADD COLUMN same_source_conflict INTEGER NOT NULL DEFAULT 0")
            # Nullable additions allow cached dashboards during deferred rebuilds.
            for name, column_type in (("cache_discount", "REAL"), ("cache_priced", "INTEGER")):
                if name not in {r["name"] for r in db.execute("PRAGMA table_info(records)")}:
                    db.execute("ALTER TABLE records ADD COLUMN " + name + " " + column_type)
            from .providers.schema import migrate
            migrate(db)
            ensure_schema(db)
            project_groups.ensure_schema(db)
            db.commit()
            db.execute("PRAGMA journal_mode=WAL")
            if not db.execute("SELECT 1 FROM settings WHERE key='exporter_id'").fetchone():
                db.execute("INSERT INTO settings VALUES('exporter_id',?)", (json.dumps(str(uuid.uuid4())),))
            if not db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
                db.execute("INSERT OR REPLACE INTO settings VALUES('bucket_version','1')")

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

    def add_source(self, root, label=None, provider="codex", kind="folder", format="jsonl", profile_location=None):
        from .providers import adapter
        adapter(provider)
        if format not in ('jsonl', 'antigravity_legacy'):
            raise ValueError('Unsupported source format')
        if format == 'antigravity_legacy':
            raise ValueError('Encrypted Antigravity archive collection is disabled. Use public transcripts and official hooks.')
        root = str(Path(root).expanduser().resolve())
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT id FROM sources WHERE root=? AND kind=? AND provider=? AND format=?", (root, kind, provider, format)).fetchone()
            if existing:
                if profile_location:
                    db.execute('INSERT OR REPLACE INTO source_private VALUES(?,?)', (existing[0], str(Path(profile_location).resolve())))
                return existing[0]
            sid = str(uuid.uuid4())
            db.execute("INSERT INTO sources(id,label,kind,root,provider,format) VALUES(?,?,?,?,?,?)", (sid, label or Path(root).name or "Session folder", kind, root, provider, format))
            if profile_location:
                db.execute('INSERT INTO source_private VALUES(?,?)', (sid, str(Path(profile_location).resolve())))
            if format == 'antigravity_legacy':
                db.execute("UPDATE sources SET status='Pending' WHERE id=?", (sid,))
            return sid

    def put_candidate(self, db, source_id, fact, parser_version=0):
        provider = fact.setdefault("provider", "codex")
        if provider != "codex" and not fact["id"].startswith(provider + ":"):
            raise ValueError("Provider session identity must be namespaced")
        if fact.get('snapshot_mode') == 'complete_binary':
            from .providers.legacy.snapshots import put_snapshot
            return put_snapshot(db, source_id, fact, parser_version)
        if provider == 'antigravity' and fact.get('history_mode') == 'antigravity_steps':
            from .providers.public_snapshots import put_snapshot
            return put_snapshot(db, source_id, fact, parser_version)
        # A source may contain several physical copies. Keep one bounded accepted
        # history, allowing only proven extensions (or a reparse of equal bytes).
        # No physical paths enter portable facts or conflict diagnostics.
        old = db.execute("SELECT * FROM candidates WHERE source_id=? AND segment_id=?",
                         (source_id, fact["segment_id"])).fetchone()
        conflict = old["same_source_conflict"] if old else 0
        if old:
            accepted = unpack(old["fact"])
            equal = (fact["byte_count"] == accepted["byte_count"]
                     and fact["prefix_hash"] == accepted["prefix_hash"])
            extends = fact.get("proofs", {}).get(str(accepted["byte_count"])) == accepted["prefix_hash"]
            if not equal and not extends:
                shorter = accepted.get("proofs", {}).get(str(fact["byte_count"])) == fact["prefix_hash"]
                if not shorter:
                    # Persist this warning even when an unchanged refresh skips
                    # the divergent file or a later accepted copy is reparsed.
                    db.execute("UPDATE candidates SET same_source_conflict=1 WHERE source_id=? AND segment_id=?",
                               (source_id, fact["segment_id"]))
                return
        db.execute("INSERT OR REPLACE INTO candidates(source_id,segment_id,session_id,parent_id,record_count,trace_count,byte_count,prefix_hash,fact,parser_version,same_source_conflict) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            source_id, fact["segment_id"], fact["id"], fact.get("parent_session_id"), fact["record_count"],
            len(fact["raw_token_trace"]), fact["byte_count"], fact["prefix_hash"], pack(fact), parser_version, conflict))

        db.execute("UPDATE candidates SET provider=? WHERE source_id=? AND segment_id=?", (provider, source_id, fact["segment_id"]))

    def choose_canonical(self, db, segment_id):
        rows = db.execute("SELECT c.* FROM candidates c JOIN sources s ON s.id=c.source_id WHERE c.segment_id=? AND s.enabled=1 ORDER BY c.record_count DESC,c.parser_version DESC,c.source_id", (segment_id,)).fetchall()
        old = db.execute("SELECT * FROM canonical WHERE segment_id=?", (segment_id,)).fetchone()
        if not rows:
            db.execute("DELETE FROM canonical WHERE segment_id=?", (segment_id,))
            db.execute("DELETE FROM session_projects WHERE segment_id=?", (segment_id,))
            db.execute("DELETE FROM records WHERE segment_id=?", (segment_id,))
            db.execute("DELETE FROM metric_buckets WHERE segment_id=?", (segment_id,))
            return True
        winner = rows[0]
        fact = unpack(winner["fact"])
        conflicting = []
        for row in rows[1:]:
            shorter = unpack(row["fact"])
            if fact.get('snapshot_mode') == shorter.get('snapshot_mode') == 'complete_binary':
                from .providers.legacy.snapshots import compatible
                matches = compatible(fact, shorter)
            elif fact.get('history_mode') == shorter.get('history_mode') == 'antigravity_steps':
                from .providers.public_snapshots import compatible
                matches = compatible(fact, shorter)
            else:
                matches = fact.get("proofs", {}).get(str(shorter["byte_count"])) == shorter["prefix_hash"]
            if not matches:
                conflicting.append(row["source_id"])
        if conflicting and old and any(r["source_id"] == old["source_id"] for r in rows):
            winner = next(r for r in rows if r["source_id"] == old["source_id"])
            fact = unpack(winner["fact"])
        # Ignored same-source branches are diagnostics, not competing accepted
        # candidates; they must not block a proven fuller copy in another source.
        conflicting.extend(row["source_id"] for row in rows if row["same_source_conflict"])
        previous_diagnostic = json.loads(old["diagnostic"] or "{}") if old else {}
        diagnostic = json.dumps({**previous_diagnostic, "conflicts": sorted(set(conflicting)), "parse_errors": fact.get("parse_errors", 0)})
        project_groups.register_session(db, segment_id, fact)
        changed = not old or old["fact"] != winner["fact"] or old["source_id"] != winner["source_id"]
        if not changed:
            db.execute("UPDATE canonical SET diagnostic=? WHERE segment_id=?", (diagnostic, segment_id))
            return json.loads(diagnostic) != previous_diagnostic
        db.execute("INSERT OR REPLACE INTO canonical(segment_id,source_id,session_id,parent_id,project_id,project_label,category,last_active,trace_count,fact,diagnostic) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            segment_id, winner["source_id"], fact["id"], fact.get("parent_session_id"), fact["project_id"],
            fact["project_label"], fact["session_source"], None, len(fact["raw_token_trace"]), winner["fact"], diagnostic))
        db.execute("UPDATE canonical SET provider=? WHERE segment_id=?", (fact.get("provider", "codex"), segment_id))
        return True

    def related_segments(self, db, changed, removed_session_ids=()):
        # Copied responses may move ownership when any provider history changes.
        result = set(changed)
        result.update(r[0] for r in db.execute("SELECT segment_id FROM canonical WHERE provider!='codex'"))
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
            source = db.execute("SELECT provider,root,kind FROM sources WHERE id=?", (source_id,)).fetchone()
            if source and source['provider'] == 'claude_code' and source['kind'] == 'folder' and source['root']:
                from .providers.profiles import remember_root
                remember_root(db, source['root'])
            segments = [r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=?", (source_id,))]
            db.execute("DELETE FROM files WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM file_failures WHERE source_id=?", (source_id,))
            db.execute('DELETE FROM source_private WHERE source_id=?', (source_id,))
            db.execute('DELETE FROM source_diagnostics WHERE source_id=?', (source_id,))
            db.execute("DELETE FROM candidates WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            return segments
