"""Prepare large source mutations privately while the main writer services live work.

Only the target source and affected accounting dependencies are published. Metric
tables are copied in session units and swapped atomically after catching up live
Codex changes. Publication preserves unrelated settings and account credentials.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

from .cooperative import checkpoint, cancelled
from .staged_projection import clone_table


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def preparation_context(db):
    """Paused work is reusable only while accounting preferences still match."""
    from .projection import PROJECTION_VERSION
    from .staged_projection import signature
    sources = [tuple(r) for r in db.execute('SELECT id,provider,kind,format,root,enabled,revision,label FROM sources ORDER BY id')]
    return hashlib.sha256(json.dumps([signature(db, PROJECTION_VERSION), sources]).encode()).hexdigest()


def reusable(store, state):
    with store.connect() as db:
        if state.get('context') != preparation_context(db):
            return False
        # During preparation only local Codex appends are interleaved. An
        # unrelated import/review accepted after a restart requires a new base.
        return not db.execute("SELECT 1 FROM canonical_changes c WHERE c.revision>? AND NOT EXISTS("
            "SELECT 1 FROM session_metadata m JOIN sources s ON s.id=m.source_id "
            "WHERE m.segment_id=c.segment_id AND m.provider='codex' AND s.kind='folder') LIMIT 1",
            (state['since'],)).fetchone()


def backup(store, destination):
    last = [0.0]
    def progress(*_):
        cancelled(store)
        if time.monotonic() - last[0] >= 1:
            last[0] = time.monotonic()
            checkpoint(store)
    with closing(sqlite3.connect(store.path)) as source, closing(sqlite3.connect(destination)) as target:
        source.execute('BEGIN')
        source.execute('SELECT revision FROM performance_state').fetchone()
        source.backup(target, pages=256, progress=progress)


def sync_live(main, shadow, since):
    """Bring current local Codex inputs into the private accounting generation."""
    from .projection import project_segments
    with main.connect() as live:
        revision = live.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0]
        changed = {r[0] for r in live.execute('SELECT segment_id FROM canonical_changes WHERE revision>?', (since,))}
    if not changed:
        return revision, set()
    with shadow.lock, shadow.connect() as db:
        db.execute('ATTACH DATABASE ? AS live', (str(main.path),))
        local = {r[0] for r in db.execute("SELECT id FROM live.sources WHERE provider='codex' AND kind='folder'")}
        for sid in local:
            db.execute('INSERT OR REPLACE INTO sources SELECT * FROM live.sources WHERE id=?', (sid,))
            for segment in changed:
                for table in ('candidates', 'history_variants', 'variant_locations', 'history_pending'):
                    db.execute(f'DELETE FROM {table} WHERE source_id=? AND segment_id=?', (sid, segment))
                    db.execute(f'INSERT INTO {table} SELECT * FROM live.{table} WHERE source_id=? AND segment_id=?', (sid, segment))
        # Live appends can extend an existing manual choice. Import-owned scopes
        # remain private to the incoming source; user-owned local choices win.
        for segment in changed:
            provider = db.execute('SELECT provider FROM live.session_metadata WHERE segment_id=?', (segment,)).fetchone()
            if provider and provider[0] == 'codex':
                group = 'copy:' + segment
                db.execute("DELETE FROM history_choices WHERE group_id=? AND scope=''", (group,))
                db.execute("INSERT INTO history_choices SELECT * FROM live.history_choices WHERE group_id=? AND scope=''", (group,))
        for segment in changed:
            shadow.choose_canonical(db, segment)
        affected = shadow.related_segments(db, changed)
        project_segments(shadow, db, affected)
    return revision, affected


def run(store, source_id, action, progress=None, before_publish=None, job_key=None):
    from .storage import Store
    root = store.directory / 'work'
    root.mkdir(exist_ok=True)
    directory = root / ('source-' + hashlib.sha256((source_id + ':' + str(job_key)).encode()).hexdigest()[:24])
    directory.mkdir(exist_ok=True)
    state_path = directory / 'work-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state and not reusable(store, state):
        cleanup(root, directory)
        directory.mkdir(exist_ok=True)
        state = {}
    if not state:
        backup(store, directory / 'insights.sqlite3')
        with closing(sqlite3.connect(directory / 'insights.sqlite3')) as db:
            state = {'phase': 'preparing', 'since': db.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0],
                     'context': preparation_context(db)}
        save_state(state_path, state)
    shadow = Store(directory)
    since = state['since']
    def yield_live(value=None):
        cancelled(store)
        checkpoint(store)
        if progress and value is not None:
            progress(value)
    shadow.cooperate = yield_live
    shadow.maintenance_cancel = getattr(store, 'maintenance_cancel', None)
    shadow.isolated = True
    if state['phase'] == 'prepared':
        result = state['result']
    else:
        result = action(shadow, yield_live)
        if isinstance(result, dict) and result.get('status') == 'unchanged':
            cleanup(root, directory)
            return result
        state.update(phase='prepared', result=result)
        save_state(state_path, state)
    cancelled(store)
    if isinstance(result, dict) and result.get('status') == 'imported':
        with store.connect() as db:
            accepted = db.execute("SELECT revision FROM sources WHERE id=? AND kind='import'", (source_id,)).fetchone()
        if accepted and accepted[0] >= result['revision']:
            cleanup(root, directory)
            return {'status': 'unchanged', 'revision': accepted[0]}
    with shadow.connect() as db:
        affected = {r[0] for r in db.execute('SELECT segment_id FROM canonical_changes WHERE revision>?', (since,))}
    since, changed = sync_live(store, shadow, since)
    affected.update(changed)
    if before_publish:
        before_publish(result, shadow)
    publish(store, shadow, source_id, affected, since, yield_live)
    cleanup(root, directory)
    return result


def save_state(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(path)


def cleanup(root, directory):
    root, directory = root.resolve(), directory.resolve()
    if directory.parent == root and directory.name.startswith('source-'):
        try:
            shutil.rmtree(directory)
        except OSError:
            pass  # An interrupted cleanup is harmless; accepted data is committed.


def publish(store, shadow, source_id, affected, since, yield_live):
    with store.lock, store.connect() as db:
        for table in ('records', 'metric_buckets'):
            db.execute('DROP TABLE IF EXISTS mutation_' + table)
            db.execute('DROP TABLE IF EXISTS retired_' + table)
            clone_table(db, table, 'mutation_' + table)
    with shadow.connect() as db:
        pending = {r[0] for r in db.execute('SELECT DISTINCT segment_id FROM records UNION SELECT segment_id FROM canonical')}
    while True:
        yield_live()
        since, changed = sync_live(store, shadow, since)
        pending.update(changed)
        affected.update(changed)
        if pending:
            batch = sorted(pending)[:16]
            with store.lock, store.connect() as db:
                db.execute('ATTACH DATABASE ? AS prepared', (str(shadow.path),))
                for segment in batch:
                    for table in ('records', 'metric_buckets'):
                        db.execute('DELETE FROM mutation_' + table + ' WHERE segment_id=?', (segment,))
                        db.execute('INSERT INTO mutation_' + table + ' SELECT * FROM prepared.' + table + ' WHERE segment_id=?', (segment,))
            pending.difference_update(batch)
            continue
        with store.lock, store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0] != since:
                continue
            db.execute('ATTACH DATABASE ? AS prepared', (str(shadow.path),))
            source = db.execute('SELECT * FROM prepared.sources WHERE id=?', (source_id,)).fetchone()
            if source:
                db.execute('INSERT OR REPLACE INTO sources SELECT * FROM prepared.sources WHERE id=?', (source_id,))
            # All source-scoped recovery/checkpoint evidence advances together.
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                if table.startswith(('rebuild_', 'retired_', 'mutation_')):
                    continue
                columns = {r['name'] for r in db.execute('PRAGMA table_info(' + quote(table) + ')')}
                if 'source_id' in columns and table not in ('canonical', 'session_metadata', 'records', 'metric_buckets'):
                    db.execute('DELETE FROM ' + quote(table) + ' WHERE source_id=?', (source_id,))
                    db.execute('INSERT INTO ' + quote(table) + ' SELECT * FROM prepared.' + quote(table) + ' WHERE source_id=?', (source_id,))
            db.execute('DELETE FROM history_choices WHERE scope=?', (source_id,))
            db.execute('INSERT INTO history_choices SELECT * FROM prepared.history_choices WHERE scope=?', (source_id,))
            for segment in affected:
                row = db.execute('SELECT * FROM prepared.canonical WHERE segment_id=?', (segment,)).fetchone()
                if row:
                    db.execute('INSERT OR REPLACE INTO canonical SELECT * FROM prepared.canonical WHERE segment_id=?', (segment,))
                else:
                    db.execute('DELETE FROM canonical WHERE segment_id=?', (segment,))
                for table in ('session_projects', 'response_claims', 'projection_dependencies'):
                    db.execute('DELETE FROM ' + table + ' WHERE segment_id=?', (segment,))
                    db.execute('INSERT INTO ' + table + ' SELECT * FROM prepared.' + table + ' WHERE segment_id=?', (segment,))
                db.execute("DELETE FROM history_choices WHERE group_id=? AND scope=''", ('copy:' + segment,))
                db.execute("INSERT INTO history_choices SELECT * FROM prepared.history_choices WHERE group_id=? AND scope=''", ('copy:' + segment,))
            db.execute('INSERT OR IGNORE INTO project_memberships SELECT * FROM prepared.project_memberships')
            db.execute('DELETE FROM overlap_summary')
            db.execute('INSERT INTO overlap_summary SELECT * FROM prepared.overlap_summary')
            db.execute("INSERT OR REPLACE INTO settings SELECT * FROM prepared.settings WHERE key=?", ('claude_import_format:' + source_id,))
            for table in ('records', 'metric_buckets'):
                db.execute('ALTER TABLE ' + table + ' RENAME TO retired_' + table)
                db.execute('ALTER TABLE mutation_' + table + ' RENAME TO ' + table)
            db.execute('DELETE FROM projection_queue')
            db.execute('INSERT INTO projection_queue SELECT * FROM prepared.projection_queue')
            saved_revision = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
            revision = (json.loads(saved_revision[0]) if saved_revision else 0) + 1
            db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(revision),))
            break
