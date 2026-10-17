"""Reconcile rewritten public step logs by stable observations, without content."""
from ..codec import pack, unpack
from .antigravity import merge_usage


def compatible(left, right):
    if left['id'] != right['id']:
        return False
    for name, key in (('raw_token_trace', 'response_id'), ('messages', 'signature')):
        a = {v[key]: v for v in left[name]}
        b = {v[key]: v for v in right[name]}
        if not (set(a) <= set(b) or set(b) <= set(a)):
            return False
        for identity in set(a) & set(b):
            if a[identity]['timestamp'] != b[identity]['timestamp']:
                return False
    return True


def put_snapshot(db, source_id, fact, version):
    old = db.execute('SELECT fact FROM candidates WHERE source_id=? AND segment_id=?', (source_id, fact['segment_id'])).fetchone()
    if old:
        previous = unpack(old[0])
        # Keep already recorded steps when the official client compacts its log.
        # New observations can enrich a step; absent fields cannot erase it.
        for name, key in (('raw_token_trace', 'response_id'), ('messages', 'signature')):
            items = {item[key]: item for item in previous.get(name, [])}
            for item in fact[name]:
                existing = items.get(item[key])
                if existing and name == 'raw_token_trace':
                    values = merge_usage(item['last_usage'], existing['last_usage'])
                    item = {**item, 'last_usage': values, 'model': item.get('model') or existing.get('model')}
                items[item[key]] = item
            fact[name] = sorted(items.values(), key=lambda item: (item['timestamp'], item[key]))
        fact['activity'] = sorted(set(previous.get('activity', []) + fact['activity']))
        fact['metadata_timestamp'] = min(previous['metadata_timestamp'], fact['metadata_timestamp'])
        fact['record_count'] = max(previous['record_count'], fact['record_count'])
        if fact['project_label'] == 'Unknown workspace' and previous.get('project_label'):
            fact.update({key: previous[key] for key in ('project_id', 'project_label')})
    db.execute('INSERT OR REPLACE INTO candidates(source_id,segment_id,session_id,parent_id,record_count,trace_count,byte_count,prefix_hash,fact,parser_version,same_source_conflict,provider) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)',
        (source_id, fact['segment_id'], fact['id'], fact.get('parent_session_id'), fact['record_count'],
         len(fact['raw_token_trace']), fact['byte_count'], fact['prefix_hash'], pack(fact), version, 'antigravity'))
