"""Choose a sequential bucket scan only for broad all-history aggregates."""


def source(table, where):
    if table not in ('records', 'metric_buckets'):
        raise ValueError('Unsupported metric table')
    selective = ('r.ts >=', 'r.segment_id IN', 'r.project_id =', 'r.model =', 'r.source_id =', 'r.provider =')
    # On legacy large indices SQLite chooses buckets_time for an upper bound
    # matching the entire history. That random table lookup was measured at
    # 1.71s versus .029s for the same sequential sum. Keep indices for actual
    # lower bounds and applied filters, and model-option covering scans.
    full = table == 'metric_buckets' and not any(fragment in where for fragment in selective)
    return table + ' r' + (' NOT INDEXED' if full else '')
