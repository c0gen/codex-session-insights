"""Small transactional projections used by interactive reads and dependencies."""
import json

from .codec import unpack

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_metadata(
 segment_id TEXT PRIMARY KEY,source_id TEXT,session_id TEXT,parent_id TEXT,
 provider TEXT,category TEXT,trace_count INTEGER,last_active TEXT,diagnostic TEXT,
 project_id TEXT,project_label TEXT);
CREATE INDEX IF NOT EXISTS metadata_source ON session_metadata(source_id,last_active);
CREATE INDEX IF NOT EXISTS metadata_session ON session_metadata(provider,session_id);
CREATE INDEX IF NOT EXISTS metadata_parent ON session_metadata(parent_id);
CREATE TABLE IF NOT EXISTS response_claims(
 provider TEXT,response_id TEXT,segment_id TEXT,quality TEXT,
 PRIMARY KEY(provider,response_id,segment_id));
CREATE INDEX IF NOT EXISTS claims_segment ON response_claims(segment_id);
CREATE TABLE IF NOT EXISTS projection_dependencies(segment_id TEXT,dependent_segment TEXT,
 PRIMARY KEY(segment_id,dependent_segment));
CREATE TABLE IF NOT EXISTS canonical_changes(segment_id TEXT PRIMARY KEY,revision INTEGER);
CREATE TABLE IF NOT EXISTS performance_state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL);
INSERT OR IGNORE INTO performance_state VALUES(1,0);
CREATE TABLE IF NOT EXISTS overlap_summary(provider TEXT,session_id TEXT,state TEXT,PRIMARY KEY(provider,session_id));
"""
COLUMNS = 'segment_id,source_id,session_id,parent_id,provider,category,trace_count,last_active,diagnostic,project_id,project_label'


def migrate(db):
    db.executescript(SCHEMA)
    columns = {r[1] for r in db.execute('PRAGMA table_info(session_metadata)')}
    for name in ('project_id', 'project_label'):
        if name not in columns:
            db.execute('ALTER TABLE session_metadata ADD COLUMN ' + name + ' TEXT')
    for operation, reference in (('INSERT', 'new'), ('UPDATE', 'new'), ('DELETE', 'old')):
        mutation = ('DELETE FROM session_metadata WHERE segment_id=old.segment_id;' if operation == 'DELETE'
                    else 'INSERT OR REPLACE INTO session_metadata(' + COLUMNS + ') VALUES('
                    + ','.join(reference + '.' + c for c in COLUMNS.split(',')) + ');')
        db.executescript(f'''CREATE TRIGGER IF NOT EXISTS metadata_{operation.lower()} AFTER {operation} ON canonical BEGIN
            {mutation}
            UPDATE performance_state SET revision=revision+1 WHERE id=1;
            INSERT OR REPLACE INTO canonical_changes VALUES({reference}.segment_id,(SELECT revision FROM performance_state WHERE id=1));
            END;''')
    if not db.execute("SELECT 1 FROM settings WHERE key='hot_metadata_version' AND value='1'").fetchone():
        db.execute('INSERT OR REPLACE INTO session_metadata SELECT ' + COLUMNS + ' FROM canonical')
        for row in db.execute("SELECT segment_id,fact FROM canonical WHERE provider!='codex'").fetchall():
            update_claims(db, row['segment_id'], unpack(row['fact']))
        db.execute("INSERT OR REPLACE INTO settings VALUES('hot_metadata_version','1')")
    if not db.execute("SELECT 1 FROM settings WHERE key='overlap_summary_version' AND value='1'").fetchone():
        from .history_overlaps import groups
        update_overlaps(db, None, groups(db))
        db.execute("INSERT OR REPLACE INTO settings VALUES('overlap_summary_version','1')")
    # Keep project grouping reads on small rows, independently of fact size.
    db.execute('DROP VIEW IF EXISTS project_sessions')
    from .project_groups import SCHEMA as project_schema
    db.execute(project_schema[project_schema.index('CREATE VIEW'):].replace('FROM canonical c', 'FROM session_metadata c').strip().rstrip(';'))


def update_claims(db, segment, fact=None):
    """Queue both former and new competitors before losing old response keys."""
    affected = competitors(db, {segment})
    db.execute('DELETE FROM response_claims WHERE segment_id=?', (segment,))
    if fact and fact.get('provider', 'codex') != 'codex':
        from .providers.reconciliation import completeness
        claims = {}
        for item in fact.get('raw_token_trace', []):
            if item.get('response_id'):
                rid = item['response_id']
                claims[rid] = max(claims.get(rid, ()), completeness(item))
        db.executemany('INSERT INTO response_claims VALUES(?,?,?,?)',
                       [(fact['provider'], rid, segment, json.dumps(quality)) for rid, quality in claims.items()])
    affected.update(competitors(db, {segment}))
    db.executemany('INSERT OR IGNORE INTO projection_dependencies VALUES(?,?)',
                   [(segment, sid) for sid in affected if sid != segment])
    db.executemany('INSERT OR IGNORE INTO projection_queue VALUES(?)', [(sid,) for sid in affected if sid != segment])


def competitors(db, segments):
    result = set()
    for segment in segments:
        result.update(r[0] for r in db.execute('SELECT dependent_segment FROM projection_dependencies WHERE segment_id=?', (segment,)))
        result.update(r[0] for r in db.execute('SELECT DISTINCT b.segment_id FROM response_claims a '
            'JOIN response_claims b ON b.provider=a.provider AND b.response_id=a.response_id WHERE a.segment_id=?', (segment,)))
        result.update(r[0] for r in db.execute("SELECT b.segment_id FROM session_metadata a JOIN session_metadata b "
            "ON b.provider=a.provider AND b.session_id=a.session_id WHERE a.segment_id=? AND a.provider!='codex'", (segment,)))
    return result


def accounting_dependencies(db, segments):
    result = set(segments)
    pending = set(result)
    while pending:
        pending = competitors(db, pending) - result
        result.update(pending)
    return result


def update_overlaps(db, sessions, groups):
    if sessions is None:
        db.execute('DELETE FROM overlap_summary')
    else:
        db.executemany('DELETE FROM overlap_summary WHERE session_id=?', [(sid,) for sid in sessions])
    db.execute('DELETE FROM overlap_summary WHERE NOT EXISTS(SELECT 1 FROM session_metadata m '
               'WHERE m.session_id=overlap_summary.session_id AND m.provider=overlap_summary.provider)')
    db.executemany('INSERT OR REPLACE INTO overlap_summary VALUES(?,?,?)',
        [(group['entries'][0]['fact']['provider'], group['session_id'], group['state']) for group in groups])
