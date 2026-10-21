"""Restartable shadow projections with atomic publication and live catch-up.

The overlay keeps large canonical facts in their original pages until a selection
or diagnostic changes. Shadow metric tables are built in committed session units;
the existing tables remain the only reader-visible generation until publication.
"""
import json
import re
import uuid

from .cooperative import checkpoint, cancelled

TABLES = ('records', 'metric_buckets', 'session_projects', 'project_memberships', 'response_claims', 'projection_queue', 'projection_dependencies', 'overlap_summary')
DETAILS = ('last_active', 'diagnostic', 'project_id', 'project_label')
NAMES = {name: 'rebuild_' + name for name in TABLES}
NAMES.update(canonical='rebuild_canonical', session_metadata='rebuild_metadata', project_sessions='rebuild_projects')
PATTERN = re.compile(r'\b(' + '|'.join(NAMES) + r')\b')


class Overlay:
    def __init__(self, db):
        self.db = db
    def execute(self, sql, args=()):
        return self.db.execute(PATTERN.sub(lambda m: NAMES[m[0]], sql), args)
    def executemany(self, sql, args):
        return self.db.executemany(PATTERN.sub(lambda m: NAMES[m[0]], sql), args)


def signature(db, version):
    from .projection_state import target, DEFAULTS
    settings = [tuple(r) for r in db.execute("SELECT key,value FROM settings WHERE key IN "
        "('timezone','assumed_fast_percent','pricing_catalog','project_aliases') ORDER BY key")]
    present = dict(settings)
    settings = sorted({**present, **{k: json.dumps(v) for k, v in target(db).items()
                                    if k in present or v != DEFAULTS[k]}}.items())
    sources = [tuple(r) for r in db.execute('SELECT id,enabled FROM sources ORDER BY id')]
    return json.dumps([4, version, settings, sources])


def clone_table(db, original, target, *, rows=False):
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (original,)).fetchone()[0]
    # Reuse the exact column types, defaults and primary keys.
    sql = re.sub(r'^(CREATE TABLE\s+)(?:"?[\w]+"?)', lambda m: m[1] + target, sql, count=1, flags=re.I)
    db.execute(sql)
    if rows:
        db.execute('INSERT INTO ' + target + ' SELECT * FROM ' + original)
    for name, statement in db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (original,)).fetchall():
        statement = statement.replace(name, 'rebuild_' + uuid.uuid4().hex[:8] + '_' + name, 1)
        statement = re.sub(r'\bON\s+(?:"' + original + '"|' + original + r')(?=\s|\()',
                           'ON ' + target, statement, count=1, flags=re.I)
        db.execute(statement)


def reset(db):
    for name in ('rebuild_canonical', 'rebuild_metadata', 'rebuild_projects'):
        db.execute('DROP VIEW IF EXISTS ' + name)
    for name in (*NAMES.values(), 'rebuild_selected', 'rebuild_deleted', 'rebuild_diagnostics', 'rebuild_work', 'rebuild_state'):
        if name not in ('rebuild_canonical', 'rebuild_metadata', 'rebuild_projects'):
            db.execute('DROP TABLE IF EXISTS ' + name)


def prepare(db, version):
    wanted = signature(db, version)
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='rebuild_state'").fetchone()
    if exists:
        saved = db.execute('SELECT signature FROM rebuild_state').fetchone()
        if saved and saved[0] == wanted:
            return
        reset(db)
    for original in ('records', 'metric_buckets'):
        db.execute('DROP TABLE IF EXISTS retired_' + original)
    for original in TABLES:
        clone_table(db, original, NAMES[original], rows=original not in ('records', 'metric_buckets', 'projection_queue'))
    clone_table(db, 'canonical', 'rebuild_selected')
    db.execute('CREATE TABLE rebuild_deleted(segment_id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE rebuild_diagnostics(segment_id TEXT PRIMARY KEY,last_active TEXT,diagnostic TEXT,project_id TEXT,project_label TEXT)')
    db.execute('CREATE TABLE rebuild_work(segment_id TEXT PRIMARY KEY,phase INTEGER NOT NULL DEFAULT 0)')
    db.execute('INSERT INTO rebuild_work(segment_id) SELECT segment_id FROM canonical UNION SELECT segment_id FROM candidates')
    db.execute('CREATE TABLE rebuild_state(signature TEXT,revision INTEGER)')
    db.execute('INSERT INTO rebuild_state SELECT ?,revision FROM performance_state WHERE id=1', (wanted,))
    columns = [r['name'] for r in db.execute('PRAGMA table_info(canonical)')]
    expressions = ['CASE WHEN d.segment_id IS NULL THEN c.' + c + ' ELSE d.' + c + ' END AS ' + c
                   if c in DETAILS else 'c.' + c for c in columns]
    db.execute('CREATE VIEW rebuild_canonical AS SELECT ' + ','.join(expressions) + ' FROM ('
               'SELECT * FROM rebuild_selected UNION ALL SELECT c.* FROM canonical c '
               'WHERE NOT EXISTS(SELECT 1 FROM rebuild_selected x WHERE x.segment_id=c.segment_id) '
               'AND NOT EXISTS(SELECT 1 FROM rebuild_deleted x WHERE x.segment_id=c.segment_id)) c '
               'LEFT JOIN rebuild_diagnostics d ON d.segment_id=c.segment_id')
    fields = ','.join(columns)
    values = ','.join('new.' + name for name in columns)
    db.execute(f'''CREATE TRIGGER rebuild_choose_INSERT INSTEAD OF INSERT ON rebuild_canonical BEGIN
        DELETE FROM rebuild_deleted WHERE segment_id=new.segment_id;
        DELETE FROM rebuild_diagnostics WHERE segment_id=new.segment_id;
        INSERT OR REPLACE INTO rebuild_selected({fields}) VALUES({values}); END''')
    db.execute('''CREATE TRIGGER rebuild_choose_UPDATE INSTEAD OF UPDATE ON rebuild_canonical BEGIN
        INSERT OR REPLACE INTO rebuild_diagnostics VALUES(new.segment_id,new.last_active,new.diagnostic,new.project_id,new.project_label); END''')
    db.execute('''CREATE TRIGGER rebuild_choose_DELETE INSTEAD OF DELETE ON rebuild_canonical BEGIN
        DELETE FROM rebuild_selected WHERE segment_id=old.segment_id;
        DELETE FROM rebuild_diagnostics WHERE segment_id=old.segment_id;
        INSERT OR IGNORE INTO rebuild_deleted VALUES(old.segment_id); END''')
    from .hot_metadata import COLUMNS
    db.execute('CREATE VIEW rebuild_metadata AS SELECT ' + COLUMNS + ' FROM rebuild_canonical')
    from .project_groups import SCHEMA
    sql = SCHEMA[SCHEMA.index('CREATE VIEW'):].strip().rstrip(';')
    db.execute(PATTERN.sub(lambda m: NAMES[m[0]], sql))


def catch_up(db):
    previous = db.execute('SELECT revision FROM rebuild_state').fetchone()[0]
    revision = db.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0]
    changed = [r[0] for r in db.execute('SELECT segment_id FROM canonical_changes WHERE revision>?', (previous,))]
    for segment in changed:
        db.execute('DELETE FROM rebuild_selected WHERE segment_id=?', (segment,))
        db.execute('DELETE FROM rebuild_diagnostics WHERE segment_id=?', (segment,))
        db.execute('DELETE FROM rebuild_deleted WHERE segment_id=?', (segment,))
        db.execute('INSERT INTO rebuild_work VALUES(?,0) ON CONFLICT(segment_id) DO UPDATE SET phase=0', (segment,))
        db.execute('DELETE FROM rebuild_response_claims WHERE segment_id=?', (segment,))
        db.execute('INSERT INTO rebuild_response_claims SELECT * FROM response_claims WHERE segment_id=?', (segment,))
        db.execute('DELETE FROM rebuild_projection_dependencies WHERE segment_id=?', (segment,))
        db.execute('INSERT INTO rebuild_projection_dependencies SELECT * FROM projection_dependencies WHERE segment_id=?', (segment,))
    db.execute('UPDATE rebuild_state SET revision=?', (revision,))


def rebuild(store, project, version, progress=None):
    from .projection_state import request
    previous = getattr(store, '_staging_projection', False)
    store._staging_projection = True
    try:
        with store.lock, store.connect() as db:
            request(db)
        result = _rebuild(store, project, version, progress)
        from .projection_state import activate
        activate(store)
        return result
    finally:
        store._staging_projection = previous


def _rebuild(store, project, version, progress=None):
    from .projection_state import ProjectionStore, target
    with store.lock, store.connect() as db:
        prepare(db, version)
    while True:
        cancelled(store)
        checkpoint(store)
        with store.lock, store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT signature FROM rebuild_state').fetchone()[0] != signature(db, version):
                reset(db)
                prepare(db, version)
            catch_up(db)
            # Complete canonical selection before projecting parent/owner relations.
            row = db.execute('SELECT segment_id,phase FROM rebuild_work WHERE phase<2 ORDER BY phase,segment_id LIMIT 1').fetchone()
            if row is None:
                publish(db, version)
                break
            segment, phase = row
            overlay = Overlay(db)
            if phase == 0:
                store.choose_canonical(overlay, segment)
            else:
                project(ProjectionStore(store, target(db)), overlay, [segment])
            db.execute('UPDATE rebuild_work SET phase=? WHERE segment_id=?', (phase + 1, segment))
            done = db.execute('SELECT count(*) FROM rebuild_work WHERE phase=2').fetchone()[0]
            total = db.execute('SELECT count(*) FROM rebuild_work').fetchone()[0]
        if progress:
            progress({'phase': 'Building usage index in background', 'sessions': done, 'total_sessions': total})


def publish(db, version):
    """Table renames publish complete metric generations in one transaction."""
    # Retired tables are dropped at the next staging preparation, outside the
    # publication transaction, so freeing a large index cannot delay live reads.
    for original in ('records', 'metric_buckets'):
        retired = 'retired_' + original
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (retired,)).fetchone():
            db.execute('DROP TABLE ' + retired)
        db.execute('ALTER TABLE ' + original + ' RENAME TO ' + retired)
        db.execute('ALTER TABLE ' + NAMES[original] + ' RENAME TO ' + original)
    # Copy only changed selections; unchanged large facts are not rewritten.
    db.execute('DELETE FROM canonical WHERE segment_id IN (SELECT segment_id FROM rebuild_deleted)')
    db.execute('INSERT OR REPLACE INTO canonical SELECT n.* FROM rebuild_selected n LEFT JOIN canonical c '
               'ON c.segment_id=n.segment_id WHERE c.segment_id IS NULL OR c.fact!=n.fact OR c.source_id!=n.source_id')
    db.execute('UPDATE canonical SET (last_active,diagnostic,project_id,project_label)=(SELECT '
               'last_active,diagnostic,project_id,project_label FROM rebuild_diagnostics n WHERE n.segment_id=canonical.segment_id) '
               'WHERE EXISTS(SELECT 1 FROM rebuild_diagnostics n WHERE n.segment_id=canonical.segment_id AND ('
               + ' OR '.join('n.' + name + ' IS NOT canonical.' + name for name in DETAILS) + '))')
    for original in ('session_projects', 'project_memberships', 'response_claims', 'overlap_summary'):
        db.execute('DELETE FROM ' + original)
        db.execute('INSERT INTO ' + original + ' SELECT * FROM ' + NAMES[original])
    db.execute('DELETE FROM projection_queue')
    db.execute('DELETE FROM projection_dependencies')
    row = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
    db.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',
        [('data_revision', json.dumps((json.loads(row[0]) if row else 0) + 1)), ('projection_version', json.dumps(version)), ('bucket_version', '1')])
    from .projection_state import publish as accept_configuration
    accept_configuration(db)
    reset(db)
