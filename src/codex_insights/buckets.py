"""Small hourly metric groups keep large histories responsive.

Filters have whole-day precision. Exact edit-resolution timestamps stay in the
group key so historical cutoffs retain their conservative confirmation rules.
"""
import json

KEYS='provider segment_id session_id source_id project_id kind day hour weekday model effort tier priced resolved_at'.split()
SUMS='total input cached writes output reasoning cost prompts added removed unknown unsupported unknown_size cache_discount cache_priced'.split()
SUMS += ['known_' + name for name in ('total','input','cached','writes','output','reasoning')]
SUMS += ['completion_unavailable']
SELECT=','.join(KEYS)+',max(ts) AS ts,'+','.join(f'sum({k}) AS {k}' for k in SUMS)+',count(*) AS event_count'
GROUP=','.join(KEYS)
VERSION = 2
PAIRED = ['paired_reasoning', 'paired_output', 'paired_responses']
PAIRED_SELECT = ','.join((
    'sum(CASE WHEN known_reasoning=1 AND known_output=1 THEN reasoning ELSE 0 END) AS paired_reasoning',
    'sum(CASE WHEN known_reasoning=1 AND known_output=1 THEN output ELSE 0 END) AS paired_output',
    'sum(CASE WHEN known_reasoning=1 AND known_output=1 THEN 1 ELSE 0 END) AS paired_responses'))
SELECT += ',' + PAIRED_SELECT


def current(version):
    return type(version) is int and version >= VERSION


def ensure_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS metric_buckets AS SELECT '+SELECT+' FROM records WHERE 0 GROUP BY '+GROUP)
    for name, column_type in (('cache_discount', 'REAL'), ('cache_priced', 'INTEGER'), ('provider', "TEXT NOT NULL DEFAULT 'codex'")):
        if name not in {r['name'] for r in db.execute('PRAGMA table_info(metric_buckets)')}:
            db.execute('ALTER TABLE metric_buckets ADD COLUMN ' + name + ' ' + column_type)
    for name in ('total','input','cached','writes','output','reasoning'):
        column = 'known_' + name
        if column not in {r['name'] for r in db.execute('PRAGMA table_info(metric_buckets)')}:
            db.execute('ALTER TABLE metric_buckets ADD COLUMN ' + column + ' INTEGER NOT NULL DEFAULT 0')
    if 'completion_unavailable' not in {r['name'] for r in db.execute('PRAGMA table_info(metric_buckets)')}:
        db.execute('ALTER TABLE metric_buckets ADD COLUMN completion_unavailable INTEGER NOT NULL DEFAULT 0')
    columns = {r['name'] for r in db.execute('PRAGMA table_info(metric_buckets)')}
    for name in PAIRED:
        if name not in columns:
            db.execute('ALTER TABLE metric_buckets ADD COLUMN ' + name + ' INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS bucket_migration(segment_id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS bucket_migration_pending(segment_id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS bucket_migration_state(version INTEGER PRIMARY KEY)')
    db.execute('CREATE INDEX IF NOT EXISTS buckets_segment ON metric_buckets(segment_id)')
    db.execute('CREATE INDEX IF NOT EXISTS buckets_time ON metric_buckets(ts)')
    db.execute('CREATE INDEX IF NOT EXISTS buckets_model ON metric_buckets(model)')


def update_segment(db,segment):
    db.execute('DELETE FROM metric_buckets WHERE segment_id=?',(segment,))
    db.execute('INSERT INTO metric_buckets ('+','.join(KEYS+['ts']+SUMS+['event_count']+PAIRED)+') SELECT '+SELECT+' FROM records WHERE segment_id=? GROUP BY '+GROUP,(segment,))


def rebuild_buckets(store, *, resume=False):
    """Resume in small transactions using stored records, never source logs."""
    from .cooperative import checkpoint, cancelled
    with store.lock, store.connect() as db:
        if not resume:
            db.execute('DELETE FROM bucket_migration')
            db.execute('DELETE FROM bucket_migration_pending')
            db.execute('DELETE FROM bucket_migration_state')
        if not db.execute('SELECT 1 FROM bucket_migration_state WHERE version=?', (VERSION,)).fetchone():
            db.execute('INSERT OR IGNORE INTO bucket_migration_pending SELECT DISTINCT segment_id FROM records')
            db.execute('INSERT INTO bucket_migration_state VALUES(?)', (VERSION,))
    while True:
        cancelled(store)
        checkpoint(store)
        cancelled(store)
        with store.lock, store.connect() as db:
            segments = [r[0] for r in db.execute('SELECT segment_id FROM bucket_migration_pending LIMIT 16')]
            for segment in segments:
                update_segment(db, segment)
                db.execute('INSERT OR IGNORE INTO bucket_migration VALUES(?)', (segment,))
                db.execute('DELETE FROM bucket_migration_pending WHERE segment_id=?', (segment,))
            if not segments:
                db.execute("INSERT OR REPLACE INTO settings VALUES('bucket_version',?)", (json.dumps(VERSION),))
                db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='data_revision'")
                return
