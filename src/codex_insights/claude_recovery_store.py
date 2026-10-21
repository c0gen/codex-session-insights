"""Durable staging, backup and status for Claude identity recovery."""
import json
import sqlite3
from contextlib import closing

VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS claude_recovery_sources(
 source_id TEXT PRIMARY KEY,version INTEGER,state TEXT,signature TEXT,report TEXT);
CREATE TABLE IF NOT EXISTS claude_recovery_stage(
 source_id TEXT,path TEXT,stamp TEXT,fact BLOB,state BLOB,metadata TEXT,error TEXT,
 PRIMARY KEY(source_id,path));
CREATE TABLE IF NOT EXISTS claude_recovery_baseline(
 source_id TEXT,response_id TEXT,total INTEGER,PRIMARY KEY(source_id,response_id));
CREATE TABLE IF NOT EXISTS claude_recovery_variants(
 source_id TEXT,old_segment TEXT,old_variant TEXT,new_segment TEXT,fact BLOB,
 parser_version INTEGER,path TEXT,pending INTEGER,
 PRIMARY KEY(source_id,old_segment,old_variant,path));
CREATE TABLE IF NOT EXISTS claude_recovery_observations(
 source_id TEXT,path TEXT,variant_id TEXT,fact BLOB,PRIMARY KEY(source_id,path,variant_id));
CREATE TABLE IF NOT EXISTS claude_recovery_moves(
 source_id TEXT,old_segment TEXT,old_variant TEXT,new_segment TEXT,new_variant TEXT,
 PRIMARY KEY(source_id,old_segment,old_variant,new_segment));
CREATE TABLE IF NOT EXISTS claude_recovery_choices(
 source_id TEXT,group_id TEXT,scope TEXT,selection BLOB,
 PRIMARY KEY(source_id,group_id,scope));
CREATE TABLE IF NOT EXISTS claude_identity_issues(
 source_id TEXT,path TEXT,segment_id TEXT,reason TEXT,PRIMARY KEY(source_id,path));
"""


def migrate(db):
    db.executescript(SCHEMA)


def backup(store):
    target = store.path.with_name('insights.before-claude-identity-v1.sqlite3')
    if getattr(store, '_claude_identity_backup_verified', False):
        return target
    if target.exists():
        with closing(sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True)) as saved:
            if saved.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Claude recovery backup is invalid; recovery has not started')
        store._claude_identity_backup_verified = True
        return target
    temporary = target.with_suffix('.tmp')
    # SQLite's backup API includes committed WAL pages and never copies a live
    # database/WAL pair at different instants.
    with store.lock, closing(sqlite3.connect(store.path)) as source:
        with closing(sqlite3.connect(temporary)) as destination:
            source.backup(destination, pages=1024)
            if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Claude recovery backup could not be verified')
        temporary.replace(target)
    store._claude_identity_backup_verified = True
    return target


def save_report(db, source, state, report, signature=''):
    db.execute('INSERT OR REPLACE INTO claude_recovery_sources VALUES(?,?,?,?,?)',
               (source, VERSION, state, signature, json.dumps(report)))


def status(db):
    rows = [dict(r) for r in db.execute('SELECT * FROM claude_recovery_sources ORDER BY source_id')]
    reports = [{**json.loads(r['report']), 'source_id': r['source_id'], 'state': r['state']} for r in rows]
    issues = db.execute('SELECT count(*) FROM claude_identity_issues').fetchone()[0]
    state = ('running' if any(r['state'] == 'staging' for r in rows) else
             'awaiting_verification' if issues or any(r['state'] == 'pending' for r in rows) else
             'complete' if rows else 'not_needed')
    return {'version': VERSION, 'state': state, 'sources': reports, 'identity_issues': issues,
            'newly_included_tokens': sum(r.get('newly_included_tokens', 0) for r in reports),
            'newly_included_responses': sum(r.get('newly_included_responses', 0) for r in reports),
            'reopened_choices': sum(r.get('reopened_choices', 0) for r in reports)}


def issue(db, source, path, segment, reason):
    db.execute('INSERT OR REPLACE INTO claude_identity_issues VALUES(?,?,?,?)', (source, str(path), segment, reason))
    if segment:
        db.execute("INSERT OR REPLACE INTO history_pending VALUES(?,?,'claude_identity_unverified')", (source, segment))


def clear_issue(db, source, path):
    row = db.execute('SELECT segment_id FROM claude_identity_issues WHERE source_id=? AND path=?', (source, str(path))).fetchone()
    db.execute('DELETE FROM claude_identity_issues WHERE source_id=? AND path=?', (source, str(path)))
    if row and row[0] and not db.execute('SELECT 1 FROM claude_identity_issues WHERE source_id=? AND segment_id=?', (source, row[0])).fetchone():
        db.execute("DELETE FROM history_pending WHERE source_id=? AND segment_id=? AND reason='claude_identity_unverified'", (source, row[0]))


def pending_segments(db, source):
    return {r[0] for r in db.execute('SELECT DISTINCT segment_id FROM claude_identity_issues WHERE source_id=? AND segment_id IS NOT NULL', (source,))}
