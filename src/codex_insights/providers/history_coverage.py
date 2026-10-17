"""Current source readability, independent of retained accounting coverage."""


def source_states(db, filters=None):
    filters = filters or {}
    clauses, params = ["enabled=1", "format='antigravity_legacy'"], []
    for column in ('provider', 'source_id'):
        if filters.get(column):
            clauses.append(('id' if column == 'source_id' else column) + '=?')
            params.append(filters[column])
    allowed = {'Available','Partial','Locked','Unsupported','Offline','Pending','Collection disabled'}
    return {row[0]: row[1] for row in db.execute('SELECT status,count(*) FROM sources WHERE ' +
        ' AND '.join(clauses) + ' GROUP BY status', params) if row[0] in allowed}
