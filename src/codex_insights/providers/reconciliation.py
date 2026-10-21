"""Stable ownership of response snapshots across copied local/imported histories."""
from ..codec import unpack


def accounting_segments(db):
    from ..history_overlaps import groups
    return set().union(*(g['suppressed'] for g in groups(db)))


def completeness(item):
    values = item['last_usage'].values()
    creation = item.get('cache_creation')
    cache_known = bool(creation and sum(creation.values()) == item['last_usage'].get('cache_write_input_tokens'))
    metadata = sum(item.get(k) not in (None, 'unknown', 'not_available')
                   for k in ('service_tier', 'speed', 'inference_geo'))
    return sum(v is not None for v in values), sum(v or 0 for v in values), cache_known, metadata


def response_owners(db, segments=None, suppressed=None):
    if segments is not None:
        import json
        owners = {}
        suppressed = suppressed or set()
        for segment in segments:
            for row in db.execute('SELECT b.* FROM response_claims a JOIN response_claims b '
                    'ON b.provider=a.provider AND b.response_id=a.response_id WHERE a.segment_id=? ORDER BY b.segment_id', (segment,)):
                if row['segment_id'] in suppressed:
                    continue
                key, quality = (row['provider'], row['response_id']), tuple(json.loads(row['quality']))
                previous = owners.get(key)
                if previous is None or quality > previous[1] or (quality == previous[1] and row['segment_id'] < previous[0]):
                    owners[key] = (row['segment_id'], quality)
        return owners
    owners = {}
    suppressed = accounting_segments(db)
    for row in db.execute("SELECT segment_id,fact FROM canonical WHERE provider!='codex' ORDER BY segment_id"):
        if row['segment_id'] in suppressed:
            continue
        fact = unpack(row["fact"])
        for item in fact.get("raw_token_trace", []):
            rid = item.get("response_id")
            if not rid:
                continue
            key = (fact["provider"], rid)
            previous = owners.get(key)
            # Prefer the most complete fragment, then a deterministic segment.
            if previous is None or completeness(item) > previous[1]:
                owners[key] = (row["segment_id"], completeness(item))
    return owners


def slices(fact, owners):
    return [{**item, "usage": item["last_usage"],
             "request_input_tokens": item["last_usage"]["input_tokens"]}
            for item in fact.get("raw_token_trace", [])
            if owners.get((fact["provider"], item.get("response_id")), (None,))[0] == fact["segment_id"]]
