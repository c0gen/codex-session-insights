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
    db.execute('CREATE INDEX IF NOT EXISTS buckets_segment ON metric_buckets(segment_id)')
    db.execute('CREATE INDEX IF NOT EXISTS buckets_time ON metric_buckets(ts)')


def update_segment(db,segment):
    db.execute('DELETE FROM metric_buckets WHERE segment_id=?',(segment,))
    db.execute('INSERT INTO metric_buckets ('+','.join(KEYS+['ts']+SUMS+['event_count'])+') SELECT '+SELECT+' FROM records WHERE segment_id=? GROUP BY '+GROUP,(segment,))


def rebuild_buckets(store):
    with store.lock,store.connect() as db:
        db.execute('DELETE FROM metric_buckets')
        db.execute('INSERT INTO metric_buckets ('+','.join(KEYS+['ts']+SUMS+['event_count'])+') SELECT '+SELECT+' FROM records GROUP BY '+GROUP)
        db.execute("INSERT OR REPLACE INTO settings VALUES('bucket_version','1')")
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)",(json.dumps(store.setting('data_revision',0)+1),))
