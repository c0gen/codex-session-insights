"""Additive migration preserves existing Codex identities and counters exactly."""


def migrate(db):
    for table in ("sources", "candidates", "canonical", "records"):
        columns = {row["name"] for row in db.execute("PRAGMA table_info(" + table + ")")}
        if "provider" not in columns:
            db.execute("ALTER TABLE " + table + " ADD COLUMN provider TEXT NOT NULL DEFAULT 'codex'")
    db.execute("CREATE INDEX IF NOT EXISTS records_provider ON records(provider,ts)")
    columns = {row['name'] for row in db.execute('PRAGMA table_info(sources)')}
    if 'format' not in columns:
        db.execute("ALTER TABLE sources ADD COLUMN format TEXT NOT NULL DEFAULT 'jsonl'")
    db.execute('CREATE TABLE IF NOT EXISTS source_private(source_id TEXT PRIMARY KEY,profile_location TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS source_diagnostics(source_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for name in ('total', 'input', 'cached', 'writes', 'output', 'reasoning'):
        if 'known_' + name not in {row['name'] for row in db.execute('PRAGMA table_info(records)')}:
            db.execute('ALTER TABLE records ADD COLUMN known_' + name + ' INTEGER NOT NULL DEFAULT 0')
            db.execute("UPDATE records SET known_" + name + "=1 WHERE kind='usage'")
    if 'completion_unavailable' not in {row['name'] for row in db.execute('PRAGMA table_info(records)')}:
        db.execute('ALTER TABLE records ADD COLUMN completion_unavailable INTEGER NOT NULL DEFAULT 0')


def coverage(db, table, where, params):
    rows = db.execute("SELECT r.provider,count(DISTINCT r.session_id) sessions,"
        "count(DISTINCT CASE WHEN r.known_total>0 THEN r.session_id END) recorded_sessions "
        "FROM " + table + " r JOIN session_metadata c ON c.segment_id=r.segment_id WHERE " + where +
        " GROUP BY r.provider", params).fetchall()
    providers = [dict(row) for row in rows]
    sessions = sum(row["sessions"] for row in rows)
    recorded = sum(row["recorded_sessions"] for row in rows)
    metrics = {}
    count = 'r.event_count' if table == 'metric_buckets' else '1'
    columns = ('total','input','cached','writes','output','reasoning')
    row = db.execute('SELECT coalesce(sum(' + count + '),0) observations,' +
        ','.join('coalesce(sum(r.known_' + name + '),0) ' + name for name in columns) +
        ' FROM ' + table + " r WHERE r.kind='usage' AND " + where, params).fetchone()
    for name in columns:
        available, observations = row[name], row['observations']
        state = 'unavailable' if not available else 'complete' if available == observations else 'partial'
        metrics[name] = {'state': state, 'available': available, 'observations': observations}
    state = metrics['total']['state']
    if state == 'complete' and recorded < sessions:
        state = 'partial'
    return {"state": state, "sessions": sessions, "recorded_sessions": recorded, "providers": providers, 'metrics': metrics}
