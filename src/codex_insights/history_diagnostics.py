"""Read-only conflict inventories. Never initialize Store or run migrations."""
import json
import sqlite3
import shutil
import tempfile
from contextlib import closing, contextmanager, ExitStack
from pathlib import Path

from .codec import unpack
from .claude_history_stats import alternative_usage


def fingerprint(path):
    values = []
    for item in (path, path.with_name(path.name + '-wal')):
        try:
            stat = item.stat()
            values.append((stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            values.append(None)
    return values


@contextmanager
def readonly_index(path):
    """Never create or update WAL/SHM files beside the user's database."""
    before = fingerprint(path)
    with ExitStack() as stack:
        wal = path.with_name(path.name + '-wal')
        if before[1] and before[1][0]:
            # SQLite mode=ro may still write shared-memory sidecars. Rebuild
            # the WAL index only in a bounded-memory private file copy instead.
            temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='insights-readonly-audit-')))
            target = temporary / path.name
            shutil.copyfile(path, target)
            shutil.copyfile(wal, target.with_name(target.name + '-wal'))
            if fingerprint(path) != before:
                raise ValueError('Index changed during the read-only audit. Close the app and retry.')
            uri = target.as_uri() + '?mode=ro'
        else:
            uri = path.as_uri() + '?mode=ro&immutable=1'
        db = stack.enter_context(closing(sqlite3.connect(uri, uri=True)))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        yield db
        if fingerprint(path) != before:
            raise ValueError('Index changed during the read-only audit. Close the app and retry.')


def diagnose(directory):
    path = Path(directory).resolve() / 'insights.sqlite3'
    if not path.is_file():
        return {'status': 'not_found', 'sources': [], 'conflicts': [], 'recovery': None}
    with readonly_index(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'canonical', 'sources'} <= tables:
            return {'status': 'unsupported_index', 'sources': [], 'conflicts': [], 'recovery': None}
        sources = [dict(r) for r in db.execute('SELECT * FROM sources ORDER BY id')]
        inventory = []
        for source in sources:
            sid = source['id']
            checkpoints = db.execute('SELECT count(*) FROM files WHERE source_id=?', (sid,)).fetchone()[0] if 'files' in tables else 0
            readable = 0
            if 'files' in tables:
                for row in db.execute('SELECT path FROM files WHERE source_id=?', (sid,)):
                    try:
                        with Path(row[0]).open('rb'):
                            readable += 1
                    except OSError:
                        pass
            inventory.append({'source_id': sid, 'provider': source.get('provider', 'codex'), 'kind': source['kind'],
                              'enabled': bool(source['enabled']), 'checkpoints': checkpoints, 'readable_originals': readable,
                              'retained_versions': db.execute('SELECT count(*) FROM history_variants WHERE source_id=?', (sid,)).fetchone()[0] if 'history_variants' in tables else None})
        conflicts = []
        providers = {}
        for row in db.execute("SELECT * FROM canonical WHERE json_extract(diagnostic,'$.copy_state') IN ('needs_review','awaiting_verification') "
                              "OR json_array_length(json_extract(diagnostic,'$.conflicts'))>0 ORDER BY segment_id"):
            diag = json.loads(row['diagnostic'] or '{}')
            if diag.get('copy_state') not in {'needs_review', 'awaiting_verification'} and not diag.get('conflicts'):
                continue
            fact = unpack(row['fact'])
            provider = fact.get('provider', 'codex')
            providers[provider] = providers.get(provider, 0) + 1
            items, locations = [], []
            if 'history_variants' in tables:
                items = [{'fact': unpack(r[0])} for r in db.execute('SELECT fact FROM history_variants WHERE segment_id=?', (row['segment_id'],))]
                locations = [r[0] for r in db.execute('SELECT DISTINCT path FROM variant_locations WHERE segment_id=?', (row['segment_id'],))]
            identity_problem = 'claude_identity_issues' in tables and db.execute('SELECT 1 FROM claude_identity_issues WHERE segment_id=?', (row['segment_id'],)).fetchone()
            entry = {'provider': provider, 'session_id': fact['id'], 'parent_session_id': fact.get('parent_session_id'),
                     'classification': fact['session_source'], 'state': diag.get('copy_state', 'needs_review'),
                     'cause': 'claude_identity_unverified' if identity_problem else 'unverified_evidence' if diag.get('copy_state') == 'awaiting_verification' else 'divergent_history',
                     'retained_versions': len(items), 'local_locations': locations}
            if provider == 'claude_code':
                entry.update(alternative_usage(items, fact))
            conflicts.append(entry)
        recovery = None
        if 'claude_recovery_sources' in tables:
            from .claude_recovery_store import status
            recovery = status(db)
        return {'status': 'ok', 'sources': inventory, 'conflicts_by_provider': providers,
                'conflicts': conflicts, 'recovery': recovery,
                'note': 'Version counters overlap. Alternative-only tokens are potential excluded usage, not verified recoverable totals.'}
