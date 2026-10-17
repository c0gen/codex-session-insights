"""Stable ownership of response snapshots across copied local/imported histories."""
from ..codec import unpack


def accounting_segments(db):
    groups = {}
    for row in db.execute("SELECT segment_id,fact FROM canonical WHERE provider!='codex'"):
        fact = unpack(row['fact'])
        groups.setdefault((fact['provider'], fact['id']), []).append((row['segment_id'], fact))
    suppressed = set()
    for entries in groups.values():
        legacy = [sid for sid, fact in entries if fact.get('snapshot_mode') == 'complete_binary']
        other = [sid for sid, fact in entries if fact.get('snapshot_mode') != 'complete_binary']
        if legacy and other:
            # The verified conversation identity overlaps, but message/edit
            # identities across formats may not align. Accept one accounting
            # format and expose the unresolved overlap; do not add both.
            suppressed.update(other)
    return suppressed


def completeness(item):
    values = item['last_usage'].values()
    creation = item.get('cache_creation')
    cache_known = bool(creation and sum(creation.values()) == item['last_usage'].get('cache_write_input_tokens'))
    metadata = sum(item.get(k) not in (None, 'unknown', 'not_available')
                   for k in ('service_tier', 'speed', 'inference_geo'))
    return sum(v is not None for v in values), sum(v or 0 for v in values), cache_known, metadata


def response_owners(db):
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
