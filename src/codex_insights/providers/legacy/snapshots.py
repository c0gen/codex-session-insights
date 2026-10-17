"""Complete binary replacement and compatibility, separate from JSONL prefixes."""
from ...codec import pack, unpack


def compatible(left, right):
    if left['id'] != right['id']:
        return False
    for name, identity in (('raw_token_trace', 'response_id'), ('messages', 'signature'), ('change_events', 'call_id')):
        a = {v[identity]: v for v in left.get(name, [])}
        b = {v[identity]: v for v in right.get(name, [])}
        if not (set(a) <= set(b) or set(b) <= set(a)):
            return False
        for key in set(a) & set(b):
            x, y = dict(a[key]), dict(b[key])
            for entry in (x, y):
                entry.pop('ordinal', None)
                entry.pop('end_byte_offset', None)
            if x != y:
                return False
    return True


def put_snapshot(db, source_id, fact, version):
    # Called only after authenticated decoding and stability checks. The file
    # checkpoint and accepted snapshot commit in the same transaction.
    db.execute('INSERT OR REPLACE INTO candidates(source_id,segment_id,session_id,parent_id,record_count,trace_count,byte_count,prefix_hash,fact,parser_version,same_source_conflict,provider) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)',
        (source_id, fact['segment_id'], fact['id'], fact.get('parent_session_id'), fact['record_count'],
         len(fact['raw_token_trace']), fact['byte_count'], fact['prefix_hash'], pack(fact), version, 'antigravity'))
