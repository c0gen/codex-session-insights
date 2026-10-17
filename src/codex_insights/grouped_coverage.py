"""Coverage and token totals for many groups in one aggregate query."""
from collections import defaultdict

METRICS = ('total', 'input', 'cached', 'writes', 'output', 'reasoning')


def coverage_groups(db, table, where, params, group):
    """Return the existing coverage shape plus total_tokens for each group.

    Provider totals retain unjoined metric rows, as the individual queries did;
    only canonical sessions count towards session coverage. Project groups use
    current membership, including metadata-only merges, in the caller's snapshot.
    """
    if table not in ('records', 'metric_buckets'):
        raise ValueError('Unsupported metric table')
    if group == 'project':
        key = 'g.project_id'
        joins = ' JOIN canonical c ON c.segment_id=r.segment_id JOIN project_sessions g ON g.segment_id=r.segment_id'
    elif group == 'provider':
        key = 'r.provider'
        joins = ' LEFT JOIN canonical c ON c.segment_id=r.segment_id'
    else:
        raise ValueError('Unsupported coverage group')
    count = 'r.event_count' if table == 'metric_buckets' else '1'
    columns = ','.join("coalesce(sum(CASE WHEN r.kind='usage' THEN r.known_" + name + ' ELSE 0 END),0) ' + name
                       for name in METRICS)
    rows = db.execute(
        'SELECT ' + key + ' group_id,r.provider,'
        'count(DISTINCT CASE WHEN c.segment_id IS NOT NULL THEN r.session_id END) sessions,'
        'count(DISTINCT CASE WHEN c.segment_id IS NOT NULL AND r.known_total>0 THEN r.session_id END) recorded_sessions,'
        "coalesce(sum(CASE WHEN r.kind='usage' THEN " + count + ' ELSE 0 END),0) observations,'
        'coalesce(sum(r.total),0) total_tokens,' + columns + ' FROM ' + table + ' r' + joins +
        ' WHERE ' + where + ' GROUP BY ' + key + ',r.provider', params)
    groups = defaultdict(list)
    for row in rows:
        groups[row['group_id']].append(row)
    return {key: _combine(rows) for key, rows in groups.items()}


def _combine(rows):
    sessions = sum(row['sessions'] for row in rows)
    recorded = sum(row['recorded_sessions'] for row in rows)
    observations = sum(row['observations'] for row in rows)
    metrics = {}
    for name in METRICS:
        available = sum(row[name] for row in rows)
        state = 'unavailable' if not available else 'complete' if available == observations else 'partial'
        metrics[name] = {'state': state, 'available': available, 'observations': observations}
    state = metrics['total']['state']
    if state == 'complete' and recorded < sessions:
        state = 'partial'
    return {'state': state, 'sessions': sessions, 'recorded_sessions': recorded,
            'providers': [{k: row[k] for k in ('provider', 'sessions', 'recorded_sessions')} for row in rows],
            'metrics': metrics, 'total_tokens': sum(row['total_tokens'] for row in rows)}
