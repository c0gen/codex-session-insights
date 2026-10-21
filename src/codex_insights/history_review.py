"""Transcript-free review API with optimistic concurrency and atomic accounting."""
import json

from .codec import digest, pack, unpack
from .copy_reconciliation import evidence_revision, variant_id
from .copy_store import effective_choice, pending_sources, save_choice, variants
from .history_overlaps import groups as overlap_groups


def summary(db, entry, accepted):
    fact = entry['fact']
    trace = fact.get('raw_token_trace', [])
    # These are recorded counters, not a claim of reconciled/combined totals.
    if fact.get('provider', 'codex') == 'codex':
        usage = (trace[-1].get('cumulative_usage') or trace[-1].get('last_usage')) if trace else None
        tokens = usage.get('total_tokens') if usage else None
    else:
        totals = [t.get('last_usage', {}).get('total_tokens') for t in trace]
        tokens = sum(totals) if totals and all(t is not None for t in totals) else None
    locations = [r[0] for r in db.execute('SELECT path FROM variant_locations WHERE source_id=? AND segment_id=? AND variant_id=? ORDER BY path',
                                         (entry['source_id'], fact['segment_id'], entry['variant_id']))]
    return {'id': entry['variant_id'], 'source': entry.get('label', 'Stored history'), 'locations': locations,
            'segment_id': fact['segment_id'], 'records': fact['record_count'], 'recorded_tokens': tokens,
            'classification': fact['session_source'], 'parent_session_id': fact.get('parent_session_id'),
            'first_activity': min(fact.get('activity') or [fact['metadata_timestamp']]).isoformat(),
            'last_activity': max(fact.get('activity') or [fact['metadata_timestamp']]).isoformat(),
            'accepted': entry['variant_id'] == accepted,
            'format': 'Legacy stored history' if fact.get('snapshot_mode') == 'complete_binary' else 'Transcript history'}


def read(db):
    result = []
    from .claude_history_stats import alternative_usage, responses
    counted = set()
    for row in db.execute("SELECT fact FROM canonical WHERE provider='claude_code'"):
        counted.update(responses(unpack(row[0])))
    for row in db.execute("SELECT * FROM canonical c WHERE coalesce(json_extract(diagnostic,'$.copy_state'),'verified')!='verified' "
                          "OR EXISTS(SELECT 1 FROM history_choices h WHERE h.group_id='copy:'||c.segment_id) ORDER BY session_id,segment_id"):
        diag = json.loads(row['diagnostic'] or '{}')
        segment = row['segment_id']
        items = variants(db, segment)
        pending = pending_sources(db, segment)
        decision = effective_choice(db, 'copy:' + segment, row['source_id'])
        state = diag.get('copy_state', 'verified')
        if state == 'verified' and not (decision and decision.get('selected')):
            continue
        accepted = variant_id(unpack(row['fact']))
        identity_problem = db.execute('SELECT 1 FROM claude_identity_issues WHERE segment_id=?', (segment,)).fetchone()
        result.append({'id': 'copy:' + segment, 'session_id': row['session_id'], 'kind': 'copy', 'state': state,
                       'reason': ('An older conflict lacks enough evidence. Reconnect the source and refresh, or explicitly choose retained history.'
                                  if pending else 'These histories cannot be proven to be copies or extensions. Choosing one excludes the other versions from totals.'),
                       'revision': digest([evidence_revision(items, pending), decision]), 'has_selection': bool(decision and decision.get('selected')),
                       'versions': [summary(db, v, accepted) for v in items]})
        result[-1]['reason_code'] = 'claude_identity_unverified' if identity_problem else 'unverified_evidence' if pending else 'divergent_history'
        if identity_problem:
            result[-1]['reason'] = 'Claude agent identity needs verification. Reconnect the original source and refresh; an older imported snapshot may require a new export from the Mac.'
        fact = unpack(row['fact'])
        if fact.get('provider') == 'claude_code':
            result[-1].update(alternative_usage(items, fact, counted))
    for row in db.execute("SELECT i.*,s.label FROM claude_identity_issues i JOIN sources s ON s.id=i.source_id "
                          "WHERE s.enabled=1 AND (i.segment_id IS NULL OR NOT EXISTS(SELECT 1 FROM canonical c WHERE c.segment_id=i.segment_id))"):
        result.append({'id': 'identity:' + digest([row['source_id'], row['path']]),
                       'session_id': 'Unverified Claude transcript', 'kind': 'identity', 'state': 'awaiting_verification',
                       'reason_code': 'claude_identity_unverified', 'reason': 'This transcript could not be assigned one verified agent identity. Reconnect its original source and refresh. Accepted history is retained where available.',
                       'revision': digest([row['source_id'], row['path'], row['reason']]), 'has_selection': False,
                       'versions': [{'id': digest(row['path']), 'source': row['label'], 'locations': [row['path']],
                                     'records': 0, 'recorded_tokens': None, 'first_activity': '', 'last_activity': '',
                                     'accepted': False, 'format': 'Identity awaiting verification'}]})
    for group in overlap_groups(db):
        result.append({key: group[key] for key in ('id', 'session_id', 'state', 'has_selection')}
                      | {'kind': 'accounting', 'reason': 'Stored legacy and transcript accounting overlap. Choose which format contributes usage; collection remains disabled.',
                         'revision': digest([group['revision'], effective_choice(db, group['id'])]),
                         'versions': [summary(db, v, group['accepted']) for v in group['entries']]})
    return result


def resolve(store, args):
    from .projection import project_segments
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        group = next((v for v in read(db) if v['id'] == args.get('id')), None)
        if group is None or group['revision'] != args.get('revision'):
            raise ValueError('History changed. Reopen Review conflicts before choosing a version.')
        group_id = group['id']
        if group['kind'] == 'identity':
            raise ValueError('Reconnect the original source and refresh to verify agent identity.')
        if args.get('undo') is True:
            # A tombstone overrides an exporter decision until explicitly selected again.
            db.execute('INSERT OR REPLACE INTO history_choices VALUES(?,?,?)', (group_id, '', pack({'selected': None, 'reviewed': []})))
        else:
            if group.get('reason_code') == 'claude_identity_unverified':
                raise ValueError('Reconnect the original source and refresh to verify agent identity before selecting a history.')
            selected = args.get('selected')
            if selected not in {v['id'] for v in group['versions']}:
                raise ValueError('Choose one of the retained history versions.')
            if group['kind'] == 'copy':
                facts = [v['fact'] for v in variants(db, group_id[5:])]
            else:
                facts = [v['fact'] for v in next(g for g in overlap_groups(db) if g['id'] == group_id)['entries']]
            save_choice(db, group_id, selected, facts)
        if group['kind'] == 'copy':
            segments = {group_id[5:]}
        else:
            segments = {v['segment_id'] for v in group['versions']}
        for segment in segments:
            store.choose_canonical(db, segment)
        project_segments(store, db, store.related_segments(db, segments))
        current = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(json.loads(current[0]) + 1 if current else 1),))
    return {'status': 'resolved' if not args.get('undo') else 'undone'}
