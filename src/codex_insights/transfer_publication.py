"""Publish sparse source and metric deltas in one accepted-state transaction."""
import json

from .projection import PROJECTION_VERSION
from .staged_projection import signature
from .sqlite_copy import insert_from


def publish(store, shadow, incoming_path, source, changed, removed, affected, required, context, since, providers, manifest, choice_groups=(), old_identities=(), relation_ids=()):
    """Return False if a relevant live append requires another calculation."""
    from .transfer_fingerprints import ensure_schema
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if signature(db, PROJECTION_VERSION) != context:
            return False
        db.execute('ATTACH DATABASE ? AS prepared', (str(shadow.path),))
        updates = {r[0] for r in db.execute('SELECT segment_id FROM canonical_changes WHERE revision>?', (since,))}
        if updates:
            from .transfer_staging import closure
            if closure(db, updates) & required:
                return False
            # Also compare new live relationships against incoming/removed
            # identities that were absent from the old accepted generation.
            with shadow.connect() as prepared:
                identities = set(relation_ids) | {r[0] for segment in required for r in prepared.execute('SELECT session_id FROM session_metadata WHERE segment_id=?', (segment,))}
                identities.update(r[0] for segment in affected for r in prepared.execute('SELECT session_id FROM candidates WHERE segment_id=?', (segment,)))
            for segment in updates:
                if db.execute('SELECT 1 FROM response_claims live JOIN prepared.response_claims staged '
                    'ON staged.provider=live.provider AND staged.response_id=live.response_id '
                    'JOIN prepared.canonical c ON c.segment_id=staged.segment_id WHERE live.segment_id=? LIMIT 1',
                    (segment,)).fetchone():
                    return False
                row = db.execute('SELECT session_id,parent_id FROM session_metadata WHERE segment_id=?', (segment,)).fetchone()
                if row and (row[0] in identities or row[1] in identities):
                    return False
        old = db.execute('SELECT revision FROM sources WHERE id=?', (source,)).fetchone()
        if old and old[0] >= manifest['revision']:
            return 'unchanged'
        db.execute('ATTACH DATABASE ? AS incoming', (str(incoming_path),))
        insert_from(db, 'sources', 'prepared', 'id=?', (source,), 'OR REPLACE')
        db.execute('UPDATE sources SET provider=? WHERE id=?',
            (next(iter(providers)) if len(providers) == 1 else 'mixed' if providers else 'codex', source))
        for segment in changed | removed:
            for table in ('candidates', 'history_variants', 'variant_locations', 'history_pending'):
                db.execute('DELETE FROM ' + table + ' WHERE source_id=? AND segment_id=?', (source, segment))
                insert_from(db, table, 'prepared', 'source_id=? AND segment_id=?', (source, segment))
        # Imported selections are reconstructed from the complete envelope ledger;
        # local reviews are always retained from the current accepted index.
        for group in choice_groups:
            db.execute('DELETE FROM history_choices WHERE scope=? AND group_id=?', (source, group))
            insert_from(db, 'history_choices', 'prepared', 'scope=? AND group_id=?', (source, group))
        for segment in affected:
            db.execute('DELETE FROM canonical WHERE segment_id=?', (segment,))
            insert_from(db, 'canonical', 'prepared', 'segment_id=?', (segment,))
            for table in ('records', 'metric_buckets', 'session_projects', 'response_claims', 'projection_queue', 'projection_dependencies'):
                db.execute('DELETE FROM ' + table + ' WHERE segment_id=?', (segment,))
                insert_from(db, table, 'prepared', 'segment_id=?', (segment,))
        insert_from(db, 'project_memberships', 'prepared', mode='OR IGNORE')
        for segment in affected:
            for row in db.execute('SELECT m.project_id,m.name FROM prepared.project_memberships m '
                'JOIN prepared.session_projects s ON s.original_project_id=m.project_id WHERE s.segment_id=?', (segment,)).fetchall():
                db.execute('UPDATE project_memberships SET name=? WHERE project_id=?', (row['name'], row['project_id']))
        overlap_identities = set(old_identities)
        overlap_identities.update(tuple(r) for segment in affected for r in db.execute('SELECT provider,session_id FROM prepared.session_metadata WHERE segment_id=?', (segment,)))
        for row in overlap_identities:
                db.execute('DELETE FROM overlap_summary WHERE provider=? AND session_id=?', tuple(row))
                insert_from(db, 'overlap_summary', 'prepared', 'provider=? AND session_id=?', tuple(row))
        ensure_schema(db)
        for segment in changed | removed:
            db.execute('DELETE FROM transfer_fingerprints WHERE source_id=? AND segment_id=?', (source, segment))
        for segment in changed:
            insert_from(db, 'transfer_fingerprints', 'incoming', 'source_id=? AND segment_id=?', (source, segment))
        db.execute('INSERT OR REPLACE INTO transfer_fingerprint_sources VALUES(?,?,?)', (source, manifest['revision'], manifest['fact_count']))
        if 'claude_code' in providers:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('claude_import_format:' + source, json.dumps(manifest['format_version'])))
        else:
            from .claude_recovery_store import retire_verification
            retire_verification(db, source, manifest['revision'])
        revision = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps((json.loads(revision[0]) if revision else 0) + 1),))
    return True
