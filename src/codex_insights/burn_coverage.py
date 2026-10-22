"""Window-scoped coverage, independent of the rate's token/cost arithmetic."""
import math

LABELS = {
    'indexing_delayed': 'Indexing delayed', 'source_offline': 'Source offline',
    'discovery_error': 'Source discovery failed', 'file_error': 'File unreadable',
    'parse_gap': 'Log records could not be interpreted', 'incomplete_tail': 'Waiting for a complete log record',
    'history_conflict': 'History needs verification', 'unpriced_usage': 'Prices missing',
    'index_error': 'Local index unavailable', 'coverage_unverified': 'Waiting for source verification',
    'pending_usage': 'New usage is being indexed',
}


def reason(code, source_id=None, count=1, retry_at=None):
    result = {'code': code, 'label': LABELS[code], 'count': count}
    if source_id is not None:
        result['source_id'] = source_id
    if retry_at is not None:
        result['retry_at'] = retry_at
    return result


def describe(coverage):
    labels = list(dict.fromkeys(r['label'] for r in coverage['reasons']))
    return '. '.join(labels) + '. This rate uses indexed records and may be incomplete. Check Sources.' if labels else ''


def evaluate(db, sources, at, window=300, stale=60, live=None):
    from .burn_freshness import pending_age, relevant_history
    cutoff = math.floor(at) - window
    reasons, fresh, checked = [], [], []
    historical_pending = live_pending = 0
    pending_projections = 0
    expirations = []
    source_freshness = []
    enabled = {s['id'] for s in sources}
    for source in sources:
        sid = source['id']
        health = db.execute('SELECT * FROM index_health WHERE source_id=?', (sid,)).fetchone()
        check = health['discovered_at'] if health else None
        if check is not None and check + stale >= at:
            expirations.append(check + stale + 1)
        for row in db.execute('SELECT min(affected_until) FROM (SELECT affected_until FROM file_coverage '
            'WHERE source_id=? AND issue_count>0 UNION ALL SELECT affected_until FROM pending_time_evidence WHERE source_id=?) '
            'WHERE affected_until>?', (sid, sid, cutoff)):
            if row[0] is not None:
                expirations.append(row[0] + window + 1)
        good = (source['status'] not in {'Offline', 'Unavailable'} and health is not None and not health['error']
                and check is not None and 0 <= at - check <= stale)
        fresh.append(good)
        checked.append(check)
        if source['status'] == 'Offline':
            reasons.append(reason('source_offline', sid))
        elif health and health['error']:
            reasons.append(reason(health['error'], sid))
        elif not good:
            reasons.append(reason('coverage_unverified' if check is None else 'indexing_delayed', sid))
        all_pending = {r[0] for r in db.execute('SELECT path FROM index_pending WHERE source_id=?', (sid,))}
        historical = {r[0] for r in db.execute('SELECT p.path FROM index_pending p JOIN pending_time_evidence e '
            'ON e.source_id=p.source_id AND e.path=p.path WHERE p.source_id=? AND e.affected_until<=?', (sid, cutoff))}
        pending = all_pending - historical
        historical_pending += len(historical)
        # Watchers report hints. Only signature-checked index_pending rows are
        # confirmed work; access-only and unchanged hints never change coverage.
        age, oldest, last_progress, overdue, deadline = pending_age(db, sid, pending, at, live)
        state = 'current' if good else 'delayed'
        if pending:
            state = 'delayed' if not good or deadline is None or at >= deadline else 'updating'
            if state == 'delayed':
                reasons.append(reason('indexing_delayed', sid, len(pending)))
            elif oldest is not None:
                expirations.append(deadline)
        source_freshness.append({'source_id': sid, 'source_label': dict(source).get('label', sid), 'state': state, 'pending_files': len(pending),
            'pending_projections': 0,
            'oldest_pending_at': oldest, 'pending_age_seconds': age, 'last_progress_at': last_progress,
            'checked_at': check, 'overdue_seconds': overdue, 'overdue_at': deadline})
        live_pending += len(pending)
        failures = db.execute('SELECT f.path,c.affected_until,r.next_retry_at FROM file_failures f '
                              'LEFT JOIN file_coverage c ON c.source_id=f.source_id AND c.path=f.path '
                              'LEFT JOIN index_retries r ON r.source_id=f.source_id AND r.path=f.path '
                              'WHERE f.source_id=?', (sid,)).fetchall()
        relevant = [r for r in failures if r['affected_until'] is None or r['affected_until'] > cutoff]
        if relevant:
            retries = [r['next_retry_at'] for r in relevant if r['next_retry_at'] is not None]
            reasons.append(reason('file_error', sid, len(relevant), min(retries) if retries else None))
        for row in db.execute("SELECT reason,count(*) AS n FROM file_coverage WHERE source_id=? "
                              "AND issue_count>0 AND reason!='file_error' "
                              'AND (affected_until IS NULL OR affected_until>?) GROUP BY reason', (sid, cutoff)):
            reasons.append(reason(row['reason'], sid, row['n']))
        conflicts = sum(relevant_history(db, row[0], cutoff, expirations, window) for row in db.execute("SELECT segment_id FROM session_metadata WHERE source_id=? AND "
                               "json_extract(diagnostic,'$.copy_state') IN ('needs_review','awaiting_verification')",
                               (sid,)))
        if conflicts:
            reasons.append(reason('history_conflict', sid, conflicts))
    queued = db.execute('SELECT DISTINCT c.source_id,c.segment_id FROM projection_queue p JOIN session_metadata c '
                        'ON c.segment_id=p.segment_id').fetchall()
    for row in queued:
        if row[0] in enabled and relevant_history(db, row[1], cutoff, expirations, window):
            pending_projections += 1
            began = db.execute('SELECT oldest_pending_at FROM projection_progress WHERE segment_id=?', (row[1],)).fetchone()
            budget = 10 if live and getattr(live, 'watcher_available', False) else 35
            source_state = next(s for s in source_freshness if s['source_id'] == row[0])
            source_state['pending_projections'] += 1
            if began:
                oldest = source_state['oldest_pending_at']
                if source_state['overdue_at'] is None or began[0] + budget < source_state['overdue_at']:
                    source_state['overdue_seconds'] = budget
                    source_state['overdue_at'] = began[0] + budget
                source_state['oldest_pending_at'] = min(oldest, began[0]) if oldest is not None else began[0]
                source_state['pending_age_seconds'] = max(0, at - source_state['oldest_pending_at'])
            if not began or at >= began[0] + budget:
                reasons.append(reason('indexing_delayed', row[0]))
                source_state['state'] = 'delayed'
            else:
                expirations.append(began[0] + budget)
                if source_state['state'] == 'current':
                    source_state['state'] = 'updating'
    coverage = {'state': 'partial' if reasons else 'complete',
                'checked_at': min(checked) if checked and all(v is not None for v in checked) else None,
                'reasons': reasons, 'historical_pending_files': historical_pending, 'live_pending_files': live_pending,
                'live_pending_projections': pending_projections,
                'freshness': {'state': 'delayed' if any(s['state'] == 'delayed' for s in source_freshness) else 'updating' if any(s['state'] == 'updating' for s in source_freshness) else 'current',
                              'sources': source_freshness},
                '_expires_at': min(expirations) if expirations else float('inf')}
    return coverage, fresh
