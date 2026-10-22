"""Project totals and matching coverage from one joined metric scan."""
from .metric_queries import source as metric_source
from .grouped_coverage import METRICS


def query_projects(db, table, where, params, added, removed):
    count = 'r.event_count' if table == 'metric_buckets' else '1'
    available = ','.join("sum(CASE WHEN r.kind='usage' THEN r.known_" + name + ' ELSE 0 END) known_' + name for name in METRICS)
    rows = db.execute("WITH memberships AS MATERIALIZED (SELECT * FROM project_sessions) "
        "SELECT g.project_id,g.name,count(DISTINCT r.session_id) sessions,"
        "count(DISTINCT CASE WHEN c.trace_count>0 THEN r.session_id END) token_sessions,"
        "count(DISTINCT CASE WHEN c.category='top_level' THEN r.session_id END) chats,"
        'sum(r.total) tokens,sum(r.cost) cost,sum(' + added + ') added,sum(' + removed + ') removed,max(r.day) last_active,'
        "count(DISTINCT r.provider||char(0)||r.session_id) coverage_sessions,"
        "count(DISTINCT CASE WHEN r.known_total>0 THEN r.provider||char(0)||r.session_id END) recorded_sessions,"
        "sum(CASE WHEN r.kind='usage' THEN " + count + ' ELSE 0 END) observations,' + available +
        ' FROM ' + metric_source(table, where) + ' JOIN session_metadata c ON c.segment_id=r.segment_id '
        'JOIN memberships g ON g.segment_id=r.segment_id WHERE ' + where + ' GROUP BY g.project_id ORDER BY tokens DESC', params)
    result = []
    for value in rows:
        row = dict(value)
        observations, sessions, recorded = row.pop('observations'), row.pop('coverage_sessions'), row.pop('recorded_sessions')
        metrics = {}
        for name in METRICS:
            known = row.pop('known_' + name) or 0
            metrics[name] = {'state': 'unavailable' if not known else 'complete' if known == observations else 'partial',
                             'available': known, 'observations': observations}
        state = metrics['total']['state']
        if state == 'complete' and recorded < sessions:
            state = 'partial'
        row.update(token_coverage=state, metric_coverage=metrics,
                   analyzed_tokens=row['tokens'] if recorded else None, estimated_cost=row['cost'])
        result.append(row)
    return result
