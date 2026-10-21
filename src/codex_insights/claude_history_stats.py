"""Response identities quantify missing activity without adding copy counters."""
from .codec import digest, unpack


def responses(fact):
    return {r['response_id']: r['last_usage'].get('total_tokens') for r in fact.get('raw_token_trace', [])
            if r.get('response_id') and isinstance(r.get('last_usage'), dict)}


def accounted_tokens(db):
    return db.execute("SELECT coalesce(sum(total),0) FROM records WHERE provider='claude_code' AND kind='usage'").fetchone()[0]


def baseline(db, source):
    db.execute('DELETE FROM claude_recovery_baseline WHERE source_id=?', (source,))
    for row in db.execute("SELECT fact FROM canonical WHERE provider='claude_code'"):
        for rid, total in responses(unpack(row[0])).items():
            db.execute('INSERT INTO claude_recovery_baseline VALUES(?,?,?) ON CONFLICT(source_id,response_id) '
                       'DO UPDATE SET total=max(total,excluded.total)', (source, rid, total or 0))


def changes(db, source):
    db.execute('CREATE TEMP TABLE IF NOT EXISTS claude_current_responses(response_id TEXT PRIMARY KEY,total INTEGER)')
    db.execute('DELETE FROM claude_current_responses')
    observations = 0
    for row in db.execute("SELECT fact FROM canonical WHERE provider='claude_code'"):
        for rid, total in responses(unpack(row[0])).items():
            observations += 1
            db.execute('INSERT INTO claude_current_responses VALUES(?,?) ON CONFLICT(response_id) '
                       'DO UPDATE SET total=max(total,excluded.total)', (rid, total or 0))
    count, total = db.execute('SELECT count(*),coalesce(sum(c.total),0) FROM claude_current_responses c '
                             'WHERE NOT EXISTS(SELECT 1 FROM claude_recovery_baseline b WHERE b.source_id=? AND b.response_id=c.response_id)', (source,)).fetchone()
    db.execute('CREATE TEMP TABLE IF NOT EXISTS claude_disputed_responses(response_id TEXT PRIMARY KEY,first_usage TEXT,disputed INTEGER)')
    db.execute('DELETE FROM claude_disputed_responses')
    for row in db.execute('SELECT fact FROM history_variants WHERE source_id=?', (source,)):
        fact = unpack(row[0])
        if fact.get('provider') != 'claude_code':
            continue
        for item in fact.get('raw_token_trace', []):
            if item.get('response_id') and item.get('last_usage'):
                db.execute('INSERT INTO claude_disputed_responses VALUES(?,?,0) ON CONFLICT(response_id) '
                           'DO UPDATE SET disputed=disputed OR first_usage!=excluded.first_usage',
                           (item['response_id'], digest(item['last_usage'])))
    disputed = db.execute('SELECT count(*) FROM claude_disputed_responses WHERE disputed=1').fetchone()[0]
    return {'newly_included_responses': count, 'newly_included_tokens': total,
            'remaining_disputed_responses': disputed,
            'duplicate_responses': observations - db.execute('SELECT count(*) FROM claude_current_responses').fetchone()[0],
            'accepted_tokens_after': accounted_tokens(db)}


def alternative_usage(items, accepted, counted=None):
    selected = responses(accepted)
    all_responses, signatures, disputed, shared = {}, {}, set(), set()
    for entry in items:
        for item in entry['fact'].get('raw_token_trace', []):
            rid = item.get('response_id')
            signature = digest(item.get('last_usage'))
            if rid in signatures and signatures[rid] != signature:
                disputed.add(rid)
            signatures[rid] = signature
        for rid, total in responses(entry['fact']).items():
            if rid in selected:
                shared.add(rid)
            all_responses[rid] = max(total or 0, all_responses.get(rid) or 0)
    excluded = {rid: total for rid, total in all_responses.items() if rid not in selected and (counted is None or rid not in counted)}
    return {'alternative_only_tokens': sum(excluded.values()), 'alternative_only_responses': len(excluded),
            'shared_responses': len(shared), 'disputed_responses': len(disputed),
            'tokens_are_potentially_excluded': True}
