"""Cheap current source health decoration, separate from cached analytics."""
from .index_health import summary
from .providers.history_coverage import source_states


def decorate(store, data):
    with store.connect() as db:
        current = {r['id']: dict(r) for r in db.execute('SELECT * FROM sources')}
        for source in data.get('sources', []):
            if source['id'] in current:
                source.update(current[source['id']])
                if source['kind'] == 'folder' and source.get('provider') == 'codex':
                    source['index_health'] = summary(db, source['id'])
        data['source_states'] = source_states(db, data.get('filters'))
    return data
