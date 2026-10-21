"""Prepare and compare recovery copies. Never replace a live index implicitly."""
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .codec import unpack
from .copy_reconciliation import covers


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def integrity(path):
    try:
        with closing(readonly(path)) as db:
            errors = [r[0] for r in db.execute('PRAGMA integrity_check(20)')]
        return {'ok': errors == ['ok'], 'diagnostics': errors}
    except sqlite3.DatabaseError as error:
        return {'ok': False, 'diagnostics': [str(error)]}


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def prepare(evidence, destination):
    """Evidence must be a quiescent preserved directory, not the live data folder."""
    evidence, destination = Path(evidence).resolve(), Path(destination).resolve()
    if destination.exists() or destination == evidence or destination.is_relative_to(evidence):
        raise ValueError('Use a new recovery directory outside the preserved evidence')
    checks, candidates = {}, []
    for path in evidence.glob('insights*.sqlite3'):
        checks[path.name] = integrity(path)
        if not checks[path.name]['ok']:
            continue
        with closing(readonly(path)) as db:
            if not {'sources', 'canonical', 'settings'} <= tables(db):
                continue
            at = db.execute('SELECT max(updated) FROM sources').fetchone()[0] or ''
            candidates.append((at, path.name, path))
    if not candidates:
        raise ValueError('No integrity-checked recovery base is available; original evidence was retained')
    _, _, base = max(candidates)
    destination.mkdir(parents=True)
    # backup() includes committed WAL pages if the evidence includes a WAL.
    try:
        with closing(readonly(base)) as source, closing(sqlite3.connect(destination / 'insights.sqlite3')) as target:
            source.backup(target, pages=1024)
        if (evidence / 'imports').is_dir():
            shutil.copytree(evidence / 'imports', destination / 'imports')
        for path in evidence.glob('*.json'):
            shutil.copy2(path, destination / path.name)
        report = {'base': base.name, 'checks': checks, 'state': 'prepared', 'promotion_allowed': False,
                  'note': 'This is a separate candidate. Validate history and metadata before any promotion.'}
        (destination / 'recovery-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report
    except BaseException:
        (destination / 'RECOVERY_INCOMPLETE').write_text('Preparation interrupted; do not promote.', encoding='utf-8')
        raise


def compare(baseline, candidate):
    """Verify retained facts by prefix proofs, not aggregate token equality."""
    result = {'baseline': Path(baseline).name, 'facts_checked': 0, 'missing_facts': 0,
              'unverified_examples': [], 'metadata_changes': []}
    with closing(readonly(baseline)) as old, closing(readonly(candidate)) as new:
        old_tables, new_tables = tables(old), tables(new)
        table = 'history_variants' if 'history_variants' in old_tables else 'canonical'
        source_map = {}
        for row in old.execute('SELECT id,root,kind FROM sources'):
            match = new.execute('SELECT id FROM sources WHERE id=? OR (root=? AND kind=?) ORDER BY id=? DESC LIMIT 1',
                                (row['id'], row['root'], row['kind'], row['id'])).fetchone()
            if match:
                source_map[row['id']] = match[0]
        for row in old.execute(f'SELECT source_id,segment_id,fact FROM {table}'):
            result['facts_checked'] += 1
            sid = source_map.get(row['source_id'], row['source_id'])
            facts = new.execute('SELECT fact FROM history_variants WHERE source_id=? AND segment_id=?',
                                (sid, row['segment_id'])).fetchall() if 'history_variants' in new_tables else new.execute(
                                    'SELECT fact FROM canonical WHERE source_id=? AND segment_id=?', (sid, row['segment_id'])).fetchall()
            if any(r[0] == row['fact'] for r in facts):
                continue
            original = unpack(row['fact'])
            if any(covers(unpack(r[0]), original) for r in facts):
                continue
            # Proven Claude rekeys retain an explicit mapping of the physical history.
            mapped = new.execute('SELECT fact FROM claude_recovery_variants WHERE source_id=? AND old_segment=? AND pending=0',
                                 (sid, row['segment_id'])).fetchall() if 'claude_recovery_variants' in new_tables else []
            from .claude_recovery_publish import physical_cover
            if not any(physical_cover(unpack(r[0]), original) for r in mapped):
                result['missing_facts'] += 1
                if len(result['unverified_examples']) < 50:
                    result['unverified_examples'].append({'source_id': sid, 'segment_id': row['segment_id']})
        for table in ('history_choices', 'project_memberships'):
            if table in old_tables:
                old_rows = set(tuple(r) for r in old.execute(f'SELECT * FROM {table}'))
                new_rows = set(tuple(r) for r in new.execute(f'SELECT * FROM {table}')) if table in new_tables else set()
                if not old_rows <= new_rows:
                    result['metadata_changes'].append(table)
        for key in ('exporter_id', 'export_revision', 'device_label', 'timezone', 'assumed_fast_percent', 'pricing_catalog',
                    'project_aliases', 'last_project_merge', 'desktop_preferences', 'widget_position',
                    'live_usage_enabled', 'claude_usage_enabled', 'antigravity_usage_enabled'):
            value = old.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            current = new.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            if value is not None and (current is None or value[0] != current[0]):
                result['metadata_changes'].append(key)
    result['preserved'] = not result['missing_facts'] and not result['metadata_changes']
    return result
