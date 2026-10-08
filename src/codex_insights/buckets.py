"""Small hourly metric groups keep large histories responsive.

Filters have whole-day precision. Exact edit-resolution timestamps stay in the
group key so historical cutoffs retain their conservative confirmation rules.
"""
import json

KEYS='segment_id session_id source_id project_id kind day hour weekday model effort tier priced resolved_at'.split()
SUMS='total input cached writes output reasoning cost prompts added removed unknown unsupported unknown_size'.split()
SELECT=','.join(KEYS)+',max(ts) AS ts,'+','.join(f'sum({k}) AS {k}' for k in SUMS)+',count(*) AS event_count'
GROUP=','.join(KEYS)


def ensure_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS metric_buckets AS SELECT '+SELECT+' FROM records WHERE 0 GROUP BY '+GROUP)
    db.execute('CREATE INDEX IF NOT EXISTS buckets_segment ON metric_buckets(segment_id)')
    db.execute('CREATE INDEX IF NOT EXISTS buckets_time ON metric_buckets(ts)')


def update_segment(db,segment):
    db.execute('DELETE FROM metric_buckets WHERE segment_id=?',(segment,))
    db.execute('INSERT INTO metric_buckets SELECT '+SELECT+' FROM records WHERE segment_id=? GROUP BY '+GROUP,(segment,))


def rebuild_buckets(store):
    with store.lock,store.connect() as db:
        db.execute('DELETE FROM metric_buckets')
        db.execute('INSERT INTO metric_buckets SELECT '+SELECT+' FROM records GROUP BY '+GROUP)
        db.execute("INSERT OR REPLACE INTO settings VALUES('bucket_version','1')")
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)",(json.dumps(store.setting('data_revision',0)+1),))
