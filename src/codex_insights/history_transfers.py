"""Transfer-v6 history envelopes; private provenance never enters snapshots."""
from .codec import unpack
from .copy_reconciliation import covers, select, variant_id
from .copy_store import choice, pending_sources, retain, save_choice, variants, write_candidate

STATES = {'verified', 'needs_review', 'manually_resolved', 'awaiting_verification'}


def local_selection(db, group_id, items):
    decision = choice(db, group_id)  # Never recirculate a remote exporter decision.
    if not decision or not decision.get('selected'):
        return None
    selected = next((v for v in items if v['variant_id'] == decision['selected']), None)
    original = next((f for f in decision.get('reviewed', []) if variant_id(f) == decision['selected']), None)
    if selected is None and original:
        selected = next((v for v in items if covers(v['fact'], original)), None)
    if selected is None:
        return None
    # A review applies only to evidence actually observed locally. Replace any
    # remote-only facts in its review list with corresponding local observations.
    reviewed = [v['fact'] for v in items if any(covers(f, v['fact']) for f in decision.get('reviewed', []))]
    if not any(variant_id(f) == selected['variant_id'] for f in reviewed):
        reviewed.append(selected['fact'])
    return {'selected': selected['variant_id'], 'reviewed': reviewed}


def envelope(db, segment_id):
    items = variants(db, segment_id, local=True)
    candidates = db.execute("SELECT c.* FROM candidates c JOIN sources s ON s.id=c.source_id WHERE c.segment_id=? "
                            "AND s.enabled=1 AND s.kind IN ('folder','bridge') ORDER BY c.record_count DESC,c.source_id",
                            (segment_id,)).fetchall()
    if not candidates:
        return None
    if not items:
        items = [{**dict(r), 'fact': unpack(r['fact']), 'variant_id': variant_id(unpack(r['fact']))} for r in candidates]
    canonical = db.execute('SELECT source_id,fact FROM canonical WHERE segment_id=?', (segment_id,)).fetchone()
    base = next((r for r in candidates if canonical and r['source_id'] == canonical['source_id']), candidates[0])
    previous = {'source_id': base['source_id'], 'variant_id': variant_id(unpack(base['fact'])), 'fact': unpack(base['fact'])}
    # If a local review selected an alternative that is not the per-source
    # candidate, canonical's exact variant is the accepted local history.
    if canonical and any(v['source_id'] == canonical['source_id'] and v['variant_id'] == variant_id(unpack(canonical['fact'])) for v in items):
        previous = {'source_id': canonical['source_id'], 'variant_id': variant_id(unpack(canonical['fact'])), 'fact': unpack(canonical['fact'])}
    decision = local_selection(db, 'copy:' + segment_id, items)
    pending = bool(pending_sources(db, segment_id, local=True))
    winner, state = select(items, previous, decision, pending)
    unique = {v['variant_id']: v['fact'] for v in items}
    result = {'accepted': winner['fact'], 'alternatives': [f for key, f in sorted(unique.items()) if key != winner['variant_id']],
              'state': state, 'selection': decision, 'awaiting_verification': pending}
    # Stored accounting formats may overlap across two different segment IDs.
    session_items = [{**dict(r), 'fact': unpack(r['fact']), 'variant_id': variant_id(unpack(r['fact']))}
                     for r in db.execute("SELECT v.* FROM history_variants v JOIN sources s ON s.id=v.source_id "
                                         "WHERE v.session_id=? AND s.enabled=1 AND s.kind IN ('folder','bridge')", (winner['fact']['id'],))]
    result['accounting_selection'] = local_selection(db, 'overlap:' + winner['fact']['id'], session_items)
    return result


def validate_selection(value, validate_fact, session_id, segment_id=None):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'selected', 'reviewed'}
            or not isinstance(value['selected'], str) or not isinstance(value['reviewed'], list) or not value['reviewed']):
        raise ValueError('Invalid history selection')
    for fact in value['reviewed']:
        validate_fact(fact, 6)
        if fact['id'] != session_id or segment_id is not None and fact['segment_id'] != segment_id:
            raise ValueError('History selection belongs to another session')
    if value['selected'] not in {variant_id(f) for f in value['reviewed']}:
        raise ValueError('Selected history is missing from reviewed evidence')
    return value


def validate(value, validate_fact):
    keys = {'accepted', 'alternatives', 'state', 'selection', 'awaiting_verification', 'accounting_selection'}
    if (not isinstance(value, dict) or set(value) != keys or not isinstance(value['state'], str) or value['state'] not in STATES
            or not isinstance(value['alternatives'], list) or type(value['awaiting_verification']) is not bool):
        raise ValueError('Invalid history envelope')
    accepted = validate_fact(value['accepted'], 6)
    seen = {variant_id(accepted)}
    for fact in value['alternatives']:
        validate_fact(fact, 6)
        if (fact['segment_id'] != accepted['segment_id'] or fact['id'] != accepted['id']
                or fact.get('provider', 'codex') != accepted.get('provider', 'codex') or variant_id(fact) in seen):
            raise ValueError('Invalid or duplicate alternative history')
        seen.add(variant_id(fact))
    decision = validate_selection(value['selection'], validate_fact, accepted['id'], accepted['segment_id'])
    if decision and decision['selected'] not in seen:
        raise ValueError('Selected history is not retained')
    validate_selection(value['accounting_selection'], validate_fact, accepted['id'])
    return value


def accept(db, source_id, value):
    fact = value['accepted']
    for entry in [fact] + value['alternatives']:
        retain(db, source_id, entry)
    write_candidate(db, source_id, fact)
    if value['awaiting_verification']:
        db.execute("INSERT OR REPLACE INTO history_pending VALUES(?,?,'imported_unverified')", (source_id, fact['segment_id']))
    for group_id, selection in (('copy:' + fact['segment_id'], value['selection']),
                                ('overlap:' + fact['id'], value['accounting_selection'])):
        if selection:
            save_choice(db, group_id, selection['selected'], selection['reviewed'], source_id)
