"""Choose between already stored accounting formats for one provider session."""
from .codec import unpack
from .copy_reconciliation import covers, evidence_revision, variant_id
from .copy_store import effective_choice


def groups(db, local=False, session_ids=None):
    sessions = {}
    where = " AND s.kind IN ('folder','bridge')" if local else ""
    params = []
    if session_ids is not None:
        session_ids = sorted(set(session_ids))
        if not session_ids:
            return []
        where += ' AND c.session_id IN (' + ','.join('?' for _ in session_ids) + ')'
        params = session_ids
    for row in db.execute("SELECT c.*,s.kind,s.label FROM canonical c JOIN sources s ON s.id=c.source_id "
                          "WHERE c.provider!='codex' AND s.enabled=1" + where, params):
        fact = unpack(row['fact'])
        value = {**dict(row), 'fact': fact, 'variant_id': variant_id(fact)}
        sessions.setdefault((fact['provider'], fact['id']), []).append(value)
    result = []
    for (_, session_id), entries in sessions.items():
        legacy = [v for v in entries if v['fact'].get('snapshot_mode') == 'complete_binary']
        public = [v for v in entries if v not in legacy]
        if not legacy or not public:
            continue
        group_id = 'overlap:' + session_id
        decision = effective_choice(db, group_id)
        selected = next((v for v in entries if decision and v['variant_id'] == decision.get('selected')), None)
        if selected is None and decision:
            original = next((f for f in decision.get('reviewed', []) if variant_id(f) == decision.get('selected')), None)
            selected = next((v for v in entries if original and covers(v['fact'], original)), None)
        accepted = selected or sorted(legacy, key=lambda v: v['segment_id'])[0]
        chosen_legacy = accepted in legacy
        rejected = public if chosen_legacy else legacy
        resolved = bool(selected and all(any(covers(f, v['fact']) for f in decision.get('reviewed', [])) for v in rejected))
        result.append({'id': group_id, 'session_id': session_id, 'entries': entries,
                       'accepted': accepted['variant_id'], 'state': 'manually_resolved' if resolved else 'needs_review',
                       'revision': evidence_revision(entries), 'suppressed': {v['segment_id'] for v in rejected},
                       'has_selection': bool(decision and decision.get('selected'))})
    return result
