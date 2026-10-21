"""Resume per-file recovery while the accepted accounting remains available."""
import json
from pathlib import Path

from .codec import digest, pack, unpack
from .parser import portable_fact
from .providers import adapter
from .providers.claude_identity import PARSER_VERSION, IdentityError, cached_identity, rekey, path_identity
from .claude_recovery_store import VERSION, backup, save_report
from .claude_history_stats import accounted_tokens, baseline


def stamp(path):
    try:
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None


def cached_fact(row, source):
    if row is None:
        return None, None
    state = unpack(row['state'])
    parser = adapter('claude_code').parser(state, row['path'], source['kind'])
    return portable_fact(parser.fact()) if parser.fact() else None, state


def stage_file(store, source, path, signature, cancel):
    from .ingestion import anchor
    with store.connect() as db:
        old = db.execute('SELECT * FROM files WHERE source_id=? AND path=?', (source['id'], str(path))).fetchone()
        existing = db.execute('SELECT * FROM claude_recovery_stage WHERE source_id=? AND path=?', (source['id'], str(path))).fetchone()
    if existing and existing['stamp'] == signature:
        return {'files': 0, 'changed_files': 0, 'bytes_read': 0}
    fact, state = None, None
    metadata, error = {}, None
    parser = adapter('claude_code').parser(path=path, kind=source['kind'])
    try:
        before = stamp(path)
        if before is None:
            raise FileNotFoundError()
        if old and old['parser_version'] == PARSER_VERSION:
            saved_state = unpack(old['state'])
            evidence = saved_state.get('claude_identity')
            if (evidence and evidence.get('id') == (saved_state.get('fact') or {}).get('id')
                    and before[0] >= old['offset'] and anchor(path, old['offset']) == old['anchor']
                    and not (before[0] == old['size'] and before[1] != old['mtime'])):
                parser = adapter('claude_code').parser(saved_state, path, source['kind'])
        start_offset = parser.state['offset']
        with path.open('rb') as stream:
            stream.seek(start_offset)
            while not cancel or not cancel.is_set():
                line = stream.readline()
                if not line or not line.endswith(b'\n'):
                    break
                parser.consume(line, stream.tell())
                if parser.state.get('ordinal', 0) % 256 == 0:
                    from .cooperative import checkpoint
                    checkpoint(store)
        if cancel and cancel.is_set():
            raise InterruptedError('Claude history recovery cancelled')
        if before != stamp(path):
            raise OSError('Transcript changed during recovery')
        fact, state = parser.fact(), parser.checkpoint()
        if fact:
            fact = portable_fact(fact)
        metadata = {'size': before[0], 'mtime': before[1], 'offset': state['offset'],
                    'anchor': anchor(path, state['offset']), 'verified': True}
    except IdentityError as exc:
        error = 'identity:' + exc.reason
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, InterruptedError):
            raise
        error = 'unavailable:' + type(exc).__name__
        try:
            fact, state = cached_fact(old, source)
        except (ValueError, TypeError, KeyError, AttributeError):
            fact, state = None, None
            error = 'unavailable:invalid_checkpoint'
        if fact:
            try:
                resolved = cached_identity(fact, path, state.get('claude_identity'))
                fact = rekey(fact, resolved, parser.bridge)
            except IdentityError:
                error = 'identity:cached_identity_disagrees_with_location'
    with store.lock, store.connect() as db:
        if fact and not error:
            from .copy_reconciliation import variant_id
            db.execute('INSERT OR REPLACE INTO claude_recovery_observations VALUES(?,?,?,?)',
                       (source['id'], str(path), variant_id(fact), pack(fact)))
        db.execute('INSERT OR REPLACE INTO claude_recovery_stage VALUES(?,?,?,?,?,?,?)',
                   (source['id'], str(path), signature, pack(fact) if fact else None,
                    pack(state) if state else None, json.dumps(metadata), error))
    changed = bool(not error and (not old or old['parser_version'] != PARSER_VERSION
                                  or [old['size'], old['mtime']] != before or old['offset'] != metadata['offset']))
    return {'files': 1, 'changed_files': int(changed),
            'bytes_read': metadata.get('offset', 0) - start_offset if not error else 0}


def import_format(store, source):
    saved = store.setting('claude_import_format:' + source['id'])
    if saved is not None:
        return saved
    import zipfile
    path = store.directory / 'imports' / (source['id'].removeprefix('import:') + '-' + str(source['revision']) + '.codex-insights')
    try:
        with zipfile.ZipFile(path) as bundle:
            return json.loads(bundle.read('manifest.json')).get('format_version')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


def recover(store, progress=None, cancel=None, scan_report=None):
    """Return sources normal ingestion must defer until staged recovery finishes."""
    blocked = set()
    for source in store.sources():
        if not source['enabled']:
            continue
        with store.connect() as db:
            saved = db.execute('SELECT * FROM claude_recovery_sources WHERE source_id=?', (source['id'],)).fetchone()
            old_files = db.execute('SELECT count(*) FROM files WHERE source_id=? AND parser_version<?', (source['id'], PARSER_VERSION)).fetchone()[0]
            has_claude = db.execute("SELECT 1 FROM candidates WHERE source_id=? AND provider='claude_code'", (source['id'],)).fetchone()
            has_issues = db.execute('SELECT 1 FROM claude_identity_issues WHERE source_id=?', (source['id'],)).fetchone()
            old_candidate = db.execute("SELECT 1 FROM candidates WHERE source_id=? AND provider='claude_code' AND parser_version<?", (source['id'], PARSER_VERSION)).fetchone()
        local = source['provider'] == 'claude_code' and source['kind'] in {'folder', 'bridge'}
        imported = source['kind'] == 'import' and has_claude
        if not local and not imported:
            continue
        if local and not old_files and not old_candidate and not has_issues:
            continue
        if imported and not saved:
            with store.connect() as db:
                legacy_agent = db.execute("SELECT 1 FROM candidates WHERE source_id=? AND provider='claude_code' AND session_id LIKE 'claude_code:agent-%' AND parent_id IS NOT NULL", (source['id'],)).fetchone()
            if not legacy_agent and import_format(store, source) == 6:
                continue
        if saved and saved['version'] == VERSION and saved['state'] == 'complete':
            report = json.loads(saved['report'])
            if not imported or report.get('import_revision') == source['revision']:
                if not old_files and not has_issues or imported:
                    continue
        if not old_files and not has_claude and not has_issues:
            continue  # A new source uses the corrected parser directly.
        paths = set()
        if local:
            with store.connect() as db:
                paths.update(r[0] for r in db.execute('SELECT path FROM files WHERE source_id=?', (source['id'],)))
            root = Path(source['root']) if source['root'] else None
            if root and not root.is_dir() and not has_issues and not any(path_identity(p)[1] for p in paths):
                # No retained agent evidence can justify an offline identity
                # change. Keep ordinary offline repricing on its existing path.
                continue
            if root and root.is_dir():
                try:
                    paths.update(str(p) for p in adapter('claude_code').discover(root, source['kind']))
                except OSError:
                    pass
        signatures = [(p, json.dumps(stamp(Path(p)))) for p in sorted(paths)]
        signature = digest([signatures, source['revision'] if imported else None])
        if saved and saved['state'] == 'pending' and saved['signature'] == signature:
            if local:
                blocked.add(source['id'])
            continue
        if cancel and cancel.is_set():
            raise InterruptedError('Claude history recovery cancelled')
        backup(store)  # No staging or accounting changes before a valid backup.
        with store.lock, store.connect() as db:
            report = json.loads(saved['report']) if saved and saved['state'] == 'staging' else {
                'accepted_tokens_before': accounted_tokens(db), 'reopened_choices': 0}
            if not saved or saved['state'] != 'staging':
                previous = json.loads(saved['report']) if saved else {}
                report.update(prior_included_tokens=previous.get('newly_included_tokens', 0),
                              prior_included_responses=previous.get('newly_included_responses', 0),
                              reopened_choices=previous.get('reopened_choices', 0))
                baseline(db, source['id'])
            save_report(db, source['id'], 'staging', report, signature)
        try:
            for index, (path, file_signature) in enumerate(signatures):
                if cancel and cancel.is_set():
                    raise InterruptedError('Claude history recovery cancelled')
                if progress:
                    progress({'phase': 'Recovering Claude history', 'files': index,
                              'total_files': len(signatures), 'source': source['label']})
                scanned = stage_file(store, source, Path(path), file_signature, cancel)
                if scan_report is not None:
                    for key, value in scanned.items():
                        scan_report[key] += value
                from .cooperative import checkpoint
                checkpoint(store)
            # A file can change while another file is staged. Never publish a
            # mixture of observations without rechecking every input boundary.
            if signatures != [(p, json.dumps(stamp(Path(p)))) for p, _ in signatures]:
                blocked.add(source['id'])
                continue
            from .claude_recovery_publish import publish
            snapshot_format = import_format(store, source) if imported else None
            if getattr(store, 'cooperate', None) and not getattr(store, 'isolated', False):
                from .isolated_jobs import run
                run(store, source['id'], lambda private, report_progress: publish(private, source, report, signature,
                    cancel, report_progress, snapshot_format), progress, job_key=signature)
            else:
                publish(store, source, report, signature, cancel, progress, snapshot_format)
            with store.connect() as db:
                state = db.execute('SELECT state FROM claude_recovery_sources WHERE source_id=?', (source['id'],)).fetchone()[0]
            if local:
                blocked.add(source['id'])
        except InterruptedError:
            raise
    return blocked
