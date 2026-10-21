"""Window-scoped coverage, independent of the rate's token/cost arithmetic."""
import math

LABELS = {
    'indexing_delayed': 'Indexing delayed', 'source_offline': 'Source offline',
    'discovery_error': 'Source discovery failed', 'file_error': 'File unreadable',
    'parse_gap': 'Log records could not be interpreted', 'incomplete_tail': 'Waiting for a complete log record',
    'history_conflict': 'History needs verification', 'unpriced_usage': 'Prices missing',
    'index_error': 'Local index unavailable', 'coverage_unverified': 'Waiting for source verification',
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
    cutoff = math.floor(at) - window
    reasons, fresh, checked = [], [], []
    historical_pending = live_pending = 0
    expirations = []
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
        good = (source['status'] == 'Ready' and health is not None and not health['error']
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
        if live:
            pending.update(path for source_id, path in live.pending() if source_id == sid)
        if pending:
            reasons.append(reason('indexing_delayed', sid, len(pending)))
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
        conflicts = db.execute("SELECT count(*) FROM session_metadata WHERE source_id=? AND "
                               "json_extract(diagnostic,'$.copy_state') IN ('needs_review','awaiting_verification')",
                               (sid,)).fetchone()[0]
        if conflicts:
            reasons.append(reason('history_conflict', sid, conflicts))
    queued = db.execute('SELECT DISTINCT c.source_id FROM projection_queue p JOIN session_metadata c '
                        'ON c.segment_id=p.segment_id').fetchall()
    for row in queued:
        if row[0] in enabled:
            reasons.append(reason('indexing_delayed', row[0]))
    coverage = {'state': 'partial' if reasons else 'complete',
                'checked_at': min(checked) if checked and all(v is not None for v in checked) else None,
                'reasons': reasons, 'historical_pending_files': historical_pending, 'live_pending_files': live_pending,
                '_expires_at': min(expirations) if expirations else float('inf')}
    return coverage, fresh
