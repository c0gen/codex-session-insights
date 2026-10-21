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
        from .copy_migration import backup_before_upgrade
        backup_before_upgrade(self.path)
        with self.connect() as db:
            db.executescript(SCHEMA)
            from .index_health import migrate as migrate_index_health
            migrate_index_health(db)
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
            from .copy_migration import migrate as migrate_copies
            migrate_copies(db)
            from .claude_recovery_store import migrate as migrate_claude_recovery
            migrate_claude_recovery(db)
            from .hot_metadata import migrate as migrate_hot_metadata
            migrate_hot_metadata(db)
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

    def put_candidate(self, db, source_id, fact, parser_version=0, path=None):
        provider = fact.setdefault("provider", "codex")
        if provider != "codex" and not fact["id"].startswith(provider + ":"):
            raise ValueError("Provider session identity must be namespaced")
        if fact.get('snapshot_mode') == 'complete_binary':
            from .providers.legacy.snapshots import put_snapshot
            put_snapshot(db, source_id, fact, parser_version)
        elif provider == 'antigravity' and fact.get('history_mode') == 'antigravity_steps':
            from .providers.public_snapshots import put_snapshot
            put_snapshot(db, source_id, fact, parser_version)
        from .copy_store import put
        put(db, source_id, fact, parser_version, path)

    def choose_canonical(self, db, segment_id):
        from .copy_canonical import choose
        return choose(db, segment_id)

    def related_segments(self, db, changed, removed_session_ids=()):
        from .hot_metadata import accounting_dependencies
        result = accounting_dependencies(db, changed)
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

    def forget_source(self, source_id, *, reprojection=False):
        with self.lock, self.connect() as db:
            source = db.execute("SELECT provider,root,kind FROM sources WHERE id=?", (source_id,)).fetchone()
            if source and source['provider'] == 'claude_code' and source['kind'] == 'folder' and source['root']:
                from .providers.profiles import remember_root
                remember_root(db, source['root'])
            segments = [r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=?", (source_id,))]
            db.execute("DELETE FROM files WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM file_failures WHERE source_id=?", (source_id,))
            from .index_health import forget as forget_index_health
            forget_index_health(db, source_id)
            db.execute('DELETE FROM source_private WHERE source_id=?', (source_id,))
            db.execute('DELETE FROM source_diagnostics WHERE source_id=?', (source_id,))
            from .copy_store import forget
            forget(db, source_id)
            db.execute("DELETE FROM candidates WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            if reprojection:
                from .projection_state import request
                request(db)
            return segments
