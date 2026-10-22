"""Time-series counters and ratios whose components need matching coverage."""
from .metric_queries import source as metric_source
from .usage_metrics import subset_percent


def query_cache_rates(db, table, where, params):
    count = 'r.event_count' if table == 'metric_buckets' else '1'
    return [dict(row) for row in db.execute(
        'SELECT r.day,coalesce(sum(r.input),0) input_tokens,'
        'coalesce(sum(r.cached),0) cached_tokens,sum(' + count + ') observations,'
        'sum(r.known_input) input_available,sum(r.known_cached) cached_available '
        'FROM ' + metric_source(table, where) + " WHERE r.kind='usage' AND " + where +
        ' GROUP BY r.day ORDER BY r.day', params)]


def apply_reasoning_basis(db, where, params, summary, coverage, metrics, table='records', paired_totals=None):
    """Never dilute recorded reasoning with output from unrecorded responses.

    Paired bucket counters retain the same response intersection as records.
    """
    known = coverage['metrics']
    observations = known['output']['observations']
    if all(known[name]['state'] == 'complete' for name in ('reasoning', 'output')):
        basis = dict(reasoning_tokens=summary['reasoning_tokens'],
                     output_tokens=summary['output_tokens'],
                     included_responses=observations, total_responses=observations)
    elif not known['reasoning']['available'] or not known['output']['available']:
        basis = dict(reasoning_tokens=0, output_tokens=0,
                     included_responses=0, total_responses=observations)
    else:
        if table == 'metric_buckets' and paired_totals is not None:
            basis = dict(reasoning_tokens=paired_totals['paired_reasoning'], output_tokens=paired_totals['paired_output'],
                included_responses=paired_totals['paired_responses'], total_responses=paired_totals['usage_observations'])
        elif table == 'metric_buckets':
            basis = dict(db.execute('SELECT coalesce(sum(r.paired_reasoning),0) reasoning_tokens,'
                'coalesce(sum(r.paired_output),0) output_tokens,'
                'coalesce(sum(r.paired_responses),0) included_responses,'
                'coalesce(sum(r.event_count),0) total_responses FROM metric_buckets r '
                "WHERE r.kind='usage' AND " + where, params).fetchone())
        else:
            paired = 'r.known_reasoning=1 AND r.known_output=1'
            basis = dict(db.execute(
            'SELECT coalesce(sum(CASE WHEN ' + paired + ' THEN r.reasoning END),0) reasoning_tokens,'
            'coalesce(sum(CASE WHEN ' + paired + ' THEN r.output END),0) output_tokens,'
            'coalesce(sum(CASE WHEN ' + paired + ' THEN 1 ELSE 0 END),0) included_responses,'
            'count(*) total_responses FROM records r WHERE r.kind=\'usage\' AND ' + where,
                params).fetchone())
    metrics['reasoning_share_basis'] = basis
    metrics['reasoning_share_percent'] = subset_percent(basis['reasoning_tokens'], basis['output_tokens'])
