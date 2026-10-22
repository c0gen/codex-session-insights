"""Durable, content-free evidence about local indexing coverage."""
import json
import time

from .codec import timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_health(source_id TEXT PRIMARY KEY, discovered_at REAL,
 checked_at REAL, error TEXT);
CREATE TABLE IF NOT EXISTS index_pending(source_id TEXT,path TEXT,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS pending_progress(source_id TEXT,path TEXT,oldest_pending_at REAL,last_progress_at REAL,
 PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS source_progress(source_id TEXT PRIMARY KEY,last_progress_at REAL);
CREATE TABLE IF NOT EXISTS pending_origins(source_id TEXT,path TEXT,origin TEXT,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS projection_progress(segment_id TEXT PRIMARY KEY,oldest_pending_at REAL);
CREATE TABLE IF NOT EXISTS file_coverage(source_id TEXT,path TEXT,checked_at REAL,
 affected_until REAL,issue_count INTEGER NOT NULL DEFAULT 0,reason TEXT,
 PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS index_retries(source_id TEXT,path TEXT,attempts INTEGER,
 next_retry_at REAL,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS file_time_evidence(source_id TEXT,path TEXT,size INTEGER,mtime INTEGER,
 affected_until REAL,PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS pending_time_evidence(source_id TEXT,path TEXT,affected_until REAL,
 PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS coverage_state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL);
INSERT OR IGNORE INTO coverage_state VALUES(1,0);
CREATE INDEX IF NOT EXISTS coverage_issues ON file_coverage(source_id,affected_until) WHERE issue_count>0;
"""


def migrate(db):
    db.executescript(SCHEMA)
    db.executescript('''CREATE TRIGGER IF NOT EXISTS pending_age_insert AFTER INSERT ON index_pending BEGIN
        INSERT OR IGNORE INTO pending_progress VALUES(new.source_id,new.path,unixepoch('now'),NULL); END;''')
    db.executescript('''CREATE TRIGGER IF NOT EXISTS projection_age_insert AFTER INSERT ON projection_queue BEGIN
        INSERT OR IGNORE INTO projection_progress VALUES(new.segment_id,unixepoch('now')); END;
        CREATE TRIGGER IF NOT EXISTS projection_age_delete AFTER DELETE ON projection_queue BEGIN
        DELETE FROM projection_progress WHERE segment_id=old.segment_id; END;''')
    db.execute("INSERT OR IGNORE INTO pending_progress SELECT source_id,path,unixepoch('now'),NULL FROM index_pending")
    db.execute("INSERT OR IGNORE INTO projection_progress SELECT segment_id,unixepoch('now') FROM projection_queue")
    for table in ('sources', 'index_health', 'index_pending', 'pending_progress', 'pending_origins', 'source_progress', 'projection_progress', 'file_coverage', 'index_retries', 'file_failures', 'projection_queue', 'pending_time_evidence'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            db.executescript(f'''CREATE TRIGGER IF NOT EXISTS coverage_{table}_{event} AFTER {event} ON {table}
                BEGIN UPDATE coverage_state SET revision=revision+1 WHERE id=1; END;''')
    db.execute("INSERT OR IGNORE INTO settings VALUES('index_coverage_version','1')")


def event_time_bound(path, size):
    """A small failed file is historical only if EVERY physical record has a time.

    Never infer this from mtime, a directory name, or the last accepted prefix.
    Large files and incomplete/invalid records conservatively remain unbounded.
    """
    if size is None or size > 2 * 1024 * 1024:
        return None
    latest = None
    try:
        with path.open('rb') as stream:
            raw = stream.read(size + 1)
        if len(raw) != size or not raw.endswith(b'\n'):
            return None
        for line in raw.splitlines():
            event = json.loads(line)
            at = timestamp(event.get('timestamp')) if isinstance(event, dict) else None
            if at is None:
                return None
            latest = max(latest or at.timestamp(), at.timestamp())
    except (OSError, ValueError, UnicodeError):
        return None
    return latest


def checkpoints(db, source, path=None):
    """Coverage verifies the same captured bytes, and pending work must retire."""
    return db.execute('SELECT f.path,f.size,f.mtime,f.parser_version,p.path AS pending,'
        'CASE WHEN e.size=f.size AND e.mtime=f.mtime THEN c.checked_at END AS verified FROM files f '
        'LEFT JOIN file_coverage c ON c.source_id=f.source_id AND c.path=f.path '
        'LEFT JOIN file_time_evidence e ON e.source_id=f.source_id AND e.path=f.path '
        'LEFT JOIN index_pending p ON p.source_id=f.source_id AND p.path=f.path '
        'WHERE f.source_id=?' + (' AND f.path=?' if path is not None else ''),
        (source, str(path)) if path is not None else (source,))


def file_checked(db, source_id, path, *, issues=0, bound=None, reason=None, progress=False):
    db.execute('INSERT OR REPLACE INTO file_coverage VALUES(?,?,?,?,?,?)',
               (source_id, str(path), time.time(), bound, issues, reason))
    db.execute('DELETE FROM index_pending WHERE source_id=? AND path=?', (source_id, str(path)))
    db.execute('DELETE FROM pending_time_evidence WHERE source_id=? AND path=?', (source_id, str(path)))
    # The captured boundary has completed. A subsequent append starts a fresh
    # pending interval; unreadable retries retain their original oldest age.
    if reason != 'file_error':
        if progress:
            db.execute('INSERT OR REPLACE INTO source_progress VALUES(?,?)', (source_id, time.time()))
        db.execute('DELETE FROM pending_progress WHERE source_id=? AND path=?', (source_id, str(path)))
        db.execute('DELETE FROM pending_origins WHERE source_id=? AND path=?', (source_id, str(path)))


def source_checked(db, source_id, at=None, error=None, discovered=False):
    at = time.time() if at is None else at
    db.execute('INSERT INTO index_health VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET '
               'checked_at=excluded.checked_at,error=excluded.error,discovered_at='
               'COALESCE(excluded.discovered_at,index_health.discovered_at)',
               (source_id, at if discovered else None, at, error))


def forget(db, source_id):
    for table in ('index_health', 'index_pending', 'pending_progress', 'pending_origins', 'source_progress', 'file_coverage', 'index_retries', 'file_time_evidence', 'pending_time_evidence'):
        db.execute(f'DELETE FROM {table} WHERE source_id=?', (source_id,))


def summary(db, source_id):
    row = db.execute('SELECT discovered_at,checked_at,error FROM index_health WHERE source_id=?', (source_id,)).fetchone()
    value = dict(row) if row else {'discovered_at': None, 'checked_at': None, 'error': None}
    for name, query in (
        ('pending_files', 'SELECT count(*) FROM index_pending WHERE source_id=?'),
        ('file_errors', 'SELECT count(*) FROM file_failures WHERE source_id=?'),
        ('parse_gaps', "SELECT count(*) FROM file_coverage WHERE source_id=? AND issue_count>0 AND reason!='file_error'"),
        ('next_retry_at', 'SELECT min(next_retry_at) FROM index_retries WHERE source_id=?'),
    ):
        value[name] = db.execute(query, (source_id,)).fetchone()[0]
    return value
