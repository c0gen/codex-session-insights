"""Reconcile selections with the unfiltered option catalog, never date results."""


def normalize_selections(filters, options, source_ids):
    result = dict(filters or {})
    available = {
        'project_id': {p['id'] for p in options['projects']},
        'model': set(options['models']),
        'source_id': set(source_ids),
    }
    for key, values in available.items():
        if result.get(key) and result[key] not in values:
            result[key] = ''
    return result
