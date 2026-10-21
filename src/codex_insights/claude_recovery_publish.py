"""Replace one source's proven identities and projections in one transaction."""
import json
from contextlib import nullcontext
from datetime import datetime, timezone

from .codec import pack, unpack
from .copy_reconciliation import variant_id
from .copy_store import put, save_choice
from .providers.claude_identity import PARSER_VERSION, IdentityError, cached_identity, rekey, scoped
from .claude_recovery_store import issue, save_report
from .claude_history_stats import changes


def physical_cover(longer, shorter):
    return ((longer['byte_count'] == shorter['byte_count'] and longer['prefix_hash'] == shorter['prefix_hash'])
            or longer.get('proofs', {}).get(str(shorter['byte_count'])) == shorter['prefix_hash']
            or bool(shorter.get('record_hash') and longer.get('record_proofs', {}).get(str(shorter['record_count'])) == shorter['record_hash']))


def stage_variants(db, source):
    sid = source['id']
    db.execute('DELETE FROM claude_recovery_variants WHERE source_id=?', (sid,))
    for row in db.execute('SELECT * FROM history_variants WHERE source_id=?', (sid,)):
        original = unpack(row['fact'])
        if original.get('provider') != 'claude_code':
            continue
        paths = [r[0] for r in db.execute('SELECT path FROM variant_locations WHERE source_id=? AND segment_id=? AND variant_id=?',
                                         (sid, row['segment_id'], row['variant_id']))]
        options, uncertain = {}, False
        for path in paths:
            observation = db.execute('SELECT * FROM claude_recovery_stage WHERE source_id=? AND path=?', (sid, path)).fetchone()
            if observation and observation['error'] and observation['error'].startswith('identity:'):
                uncertain = True
                continue
            resolved = None
            try:
                if observation and observation['fact'] and not observation['error']:
                    observed = unpack(observation['fact'])
                    if physical_cover(observed, original):
                        resolved = unpack(observation['state']).get('claude_identity')
                resolved = resolved or cached_identity(original, path)
                fixed = rekey(original, resolved, source['kind'] == 'bridge')
                options[fixed['segment_id']] = fixed
                uncertain |= bool(observation is None or observation['error'])
            except IdentityError:
                uncertain = True
        if not paths:
            try:
                resolved = cached_identity(original)
                fixed = rekey(original, resolved, source['kind'] == 'bridge')
                options[fixed['segment_id']] = fixed
                # Portable main histories contain no agent evidence. A genuine
                # copy disagreement stays a disagreement, never an inferred agent.
                uncertain = source['kind'] != 'import' and not scoped(original)
            except IdentityError:
                uncertain = True
        if len(options) != 1:
            fixed, uncertain = original, True
        else:
            fixed = next(iter(options.values()))
        for path in paths or ['']:
            db.execute('INSERT OR REPLACE INTO claude_recovery_variants VALUES(?,?,?,?,?,?,?,?)',
                       (sid, row['segment_id'], row['variant_id'], fixed['segment_id'], pack(fixed), row['parser_version'], path, int(uncertain)))


def mapped_review(db, source, fact):
    rows = db.execute('SELECT DISTINCT fact FROM claude_recovery_variants WHERE source_id=? AND old_segment=? AND old_variant=? AND pending=0',
                      (source, fact['segment_id'], variant_id(fact))).fetchall()
    if len(rows) == 1:
        return unpack(rows[0][0])
    # A reviewed shorter version may already have been pruned by an extension.
    matches = {}
    for row in db.execute('SELECT fact FROM claude_recovery_variants WHERE source_id=? AND pending=0', (source,)):
        candidate = unpack(row[0])
        if physical_cover(candidate, fact):
            matches[candidate['segment_id']] = candidate
    if len(matches) == 1:
        template = next(iter(matches.values()))
        return {**fact, **{key: template.get(key) for key in ('id', 'segment_id', 'parent_session_id', 'session_source')}}
    return None


def migrate_choices(db, source, old_segments):
    reopened = 0
    for segment in old_segments:
        targets = {r[0] for r in db.execute('SELECT DISTINCT new_segment FROM claude_recovery_variants WHERE source_id=? AND old_segment=?', (source, segment))}
        group = 'copy:' + segment
        for row in db.execute('SELECT * FROM history_choices WHERE group_id=?', (group,)).fetchall():
            choice = unpack(row['selection'])
            reviewed = choice.get('reviewed', [])
            mapped = [mapped_review(db, source, f) for f in reviewed]
            if targets == {segment} and all(f and f['segment_id'] == segment for f in mapped):
                continue
            valid = bool(mapped and all(mapped) and len({f['segment_id'] for f in mapped}) == 1)
            db.execute('INSERT OR REPLACE INTO claude_recovery_choices VALUES(?,?,?,?)', (source, group, row['scope'], row['selection']))
            db.execute('DELETE FROM history_choices WHERE group_id=? AND scope=?', (group, row['scope']))
            selected = next((new for old, new in zip(reviewed, mapped) if variant_id(old) == choice.get('selected')), None)
            if valid and selected:
                save_choice(db, 'copy:' + selected['segment_id'], variant_id(selected), mapped, row['scope'])
            else:
                reopened += 1
    return reopened


def publish(store, source, report, signature, cancel=None, progress=None, snapshot_format=None, connection=None):
    from .projection import project_segments
    sid = source['id']
    with store.lock, (store.connect() if connection is None else nullcontext(connection)) as db:
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        if cancel and cancel.is_set():
            raise InterruptedError('Claude history recovery cancelled')
        # A candidate can predate review storage. Preserve it before replacing
        # anything, including a source whose original files have disappeared.
        from .copy_store import retain
        for row in db.execute("SELECT * FROM candidates WHERE source_id=? AND provider='claude_code'", (sid,)):
            retain(db, sid, unpack(row['fact']), row['parser_version'])
        stage_variants(db, source)
        old_segments = {r[0] for r in db.execute("SELECT segment_id FROM candidates WHERE source_id=? AND provider='claude_code'", (sid,))}
        old_segments.update(r[0] for r in db.execute('SELECT DISTINCT old_segment FROM claude_recovery_variants WHERE source_id=?', (sid,)))
        old_segments.update(r[0] for r in db.execute("SELECT segment_id FROM canonical WHERE source_id=? AND provider='claude_code'", (sid,)))
        old_sessions = {r[0] for r in db.execute("SELECT session_id FROM candidates WHERE source_id=? AND provider='claude_code'", (sid,))}
        pending = {r['segment_id']: r['reason'] for r in db.execute('SELECT * FROM history_pending WHERE source_id=?', (sid,))}
        reopened = migrate_choices(db, sid, old_segments)
        db.execute('DELETE FROM claude_identity_issues WHERE source_id=?', (sid,))
        db.execute("DELETE FROM candidates WHERE source_id=? AND provider='claude_code'", (sid,))
        for segment in old_segments:
            for table in ('history_variants', 'variant_locations', 'history_pending'):
                db.execute('DELETE FROM ' + table + ' WHERE source_id=? AND segment_id=?', (sid, segment))
        segments = set(old_segments)
        moved = 0
        for row in db.execute('SELECT * FROM claude_recovery_variants WHERE source_id=?', (sid,)):
            if cancel and cancel.is_set():
                raise InterruptedError('Claude history recovery cancelled')
            fact = unpack(row['fact'])
            segments.add(fact['segment_id'])
            put(db, sid, fact, row['parser_version'], row['path'] or None)
            db.execute('INSERT OR REPLACE INTO claude_recovery_moves VALUES(?,?,?,?,?)',
                       (sid, row['old_segment'], row['old_variant'], fact['segment_id'], variant_id(fact)))
            moved += int(row['old_segment'] != fact['segment_id'])
            if row['pending']:
                issue(db, sid, row['path'] or 'retained:' + row['old_variant'], fact['segment_id'], 'retained_identity_needs_verification')
        for row in db.execute('SELECT * FROM claude_recovery_observations WHERE source_id=?', (sid,)):
            fact = unpack(row['fact'])
            segments.add(fact['segment_id'])
            put(db, sid, fact, PARSER_VERSION, row['path'])
        for row in db.execute('SELECT * FROM claude_recovery_stage WHERE source_id=?', (sid,)):
            fact = unpack(row['fact']) if row['fact'] else None
            if fact:
                segments.add(fact['segment_id'])
                put(db, sid, fact, PARSER_VERSION if not row['error'] else 0, row['path'])
            if row['error']:
                old = db.execute('SELECT state FROM files WHERE source_id=? AND path=?', (sid, row['path'])).fetchone()
                old_fact = unpack(old[0]).get('fact') if old else None
                issue(db, sid, row['path'], fact['segment_id'] if fact else old_fact.get('segment_id') if old_fact else None, row['error'])
            elif row['state']:
                metadata = json.loads(row['metadata'])
                db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?)',
                           (sid, row['path'], metadata['offset'], metadata['mtime'], metadata['size'], metadata['anchor'], row['state'], PARSER_VERSION))
                db.execute('DELETE FROM file_failures WHERE source_id=? AND path=?', (sid, row['path']))
        # An unexplained older warning survives. Two fully mapped versions can
        # establish whether it was an identity collision or a real copy branch.
        for segment, reason in pending.items():
            rows = db.execute('SELECT DISTINCT old_variant,new_segment,pending FROM claude_recovery_variants WHERE source_id=? AND old_segment=?', (sid, segment)).fetchall()
            proved = len({r['old_variant'] for r in rows}) >= 2 and not any(r['pending'] for r in rows)
            if reason != 'claude_identity_unverified' and not proved:
                for target in {r['new_segment'] for r in rows} or {segment}:
                    db.execute('INSERT OR REPLACE INTO history_pending VALUES(?,?,?)', (sid, target, reason))
        for segment in segments:
            store.choose_canonical(db, segment)
        related = store.related_segments(db, segments, old_sessions)
        project_segments(store, db, related, progress)
        if cancel and cancel.is_set():
            raise InterruptedError('Claude history recovery cancelled')
        unresolved = db.execute('SELECT count(*) FROM claude_identity_issues WHERE source_id=?', (sid,)).fetchone()[0]
        genuine = sum(json.loads(r[0] or '{}').get('copy_state') == 'needs_review' for r in db.execute(
            "SELECT diagnostic FROM canonical WHERE provider='claude_code'"))
        report = {**report, **changes(db, sid), 'reclassified_versions': moved,
                  'reopened_choices': report.get('reopened_choices', 0) + reopened,
                  'unresolved_groups': unresolved, 'remaining_copy_conflicts': genuine,
                  'import_revision': source['revision'] if source['kind'] == 'import' else None,
                  'legacy_snapshot_without_alternatives': bool(snapshot_format and snapshot_format < 6)}
        report['accepted_token_change'] = report['accepted_tokens_after'] - report['accepted_tokens_before']
        report['run_newly_included_tokens'] = report['newly_included_tokens']
        report['run_newly_included_responses'] = report['newly_included_responses']
        report['newly_included_tokens'] += report.get('prior_included_tokens', 0)
        report['newly_included_responses'] += report.get('prior_included_responses', 0)
        save_report(db, sid, 'pending' if unresolved or report['legacy_snapshot_without_alternatives'] else 'complete', report, signature)
        if source['kind'] in {'folder', 'bridge'}:
            db.execute('UPDATE sources SET status=?,updated=? WHERE id=?',
                       ('Identity verification pending' if unresolved else 'Ready', datetime.now(timezone.utc).isoformat(), sid))
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting('data_revision', 0) + 1),))
        db.execute('DELETE FROM claude_recovery_baseline WHERE source_id=?', (sid,))
        db.execute('DELETE FROM claude_recovery_variants WHERE source_id=?', (sid,))
        db.execute('DELETE FROM claude_recovery_observations WHERE source_id=?', (sid,))
        # Verified file checkpoints now live in files. Keep only failed stages
        # for retry signatures; avoid permanently duplicating large checkpoints.
        db.execute('DELETE FROM claude_recovery_stage WHERE source_id=? AND error IS NULL', (sid,))
