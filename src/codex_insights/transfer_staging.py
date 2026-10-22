"""Sparse accounting workspaces for atomic source-record replacements."""
import json

from .codec import unpack
from .projection import PROJECTION_VERSION, project_segments
from .staged_projection import signature
from .sqlite_copy import insert_from

FACT_TABLES = ('canonical', 'candidates', 'history_variants', 'variant_locations', 'history_pending')
METRIC_TABLES = ('records', 'metric_buckets', 'session_projects', 'projection_dependencies')


def copy_rows(db, table, where='', args=()):
    insert_from(db, table, 'accepted', where, args, 'OR REPLACE')


def changed_rows(incoming, source, segments):
    for segment in sorted(segments):
        row = incoming.execute('SELECT * FROM transfer_fingerprints WHERE source_id=? AND segment_id=?', (source, segment)).fetchone()
        if row:
            yield row


def closure(db, seeds, facts=(), cooperate=None):
    """Accounting competitors, same-session creation, ancestry and descendants."""
    result = set(seeds)
    sessions, parents, responses = set(), set(), set()
    for fact in facts:
        sessions.add(fact['id'])
        if fact.get('parent_session_id'):
            parents.add(fact['parent_session_id'])
        for entry in fact.get('raw_token_trace', []):
            if entry.get('response_id'):
                responses.add((fact.get('provider', 'codex'), entry['response_id']))
    for provider, response in responses:
        result.update(r[0] for r in db.execute('SELECT segment_id FROM response_claims WHERE provider=? AND response_id=?', (provider, response)))
    while True:
        before = len(result)
        for index, segment in enumerate(tuple(result)):
            if cooperate and index % 32 == 0:
                cooperate()
            for row in db.execute('SELECT session_id,parent_id FROM session_metadata WHERE segment_id=?', (segment,)):
                sessions.add(row['session_id'])
                if row['parent_id']:
                    parents.add(row['parent_id'])
        for index, sid in enumerate(sessions | parents):
            if cooperate and index % 32 == 0:
                cooperate()
            result.update(r[0] for r in db.execute('SELECT segment_id FROM session_metadata WHERE session_id=?', (sid,)))
        for index, sid in enumerate(sessions):
            if cooperate and index % 32 == 0:
                cooperate()
            result.update(r[0] for r in db.execute('SELECT segment_id FROM session_metadata WHERE parent_id=?', (sid,)))
        from .hot_metadata import accounting_dependencies
        result.update(accounting_dependencies(db, result))
        if len(result) == before:
            return result


def prepare(store, shadow, incoming, source_id, changed, removed, manifest, progress=None):
    """Copy compact accounting context and only facts reachable from this delta."""
    from .cooperative import checkpoint, cancelled
    def cooperate():
        cancelled(store)
        checkpoint(store)
    def units(values):
        for index, value in enumerate(values):
            if index % 16 == 0:
                cooperate()
            yield value
    facts = []
    for row in units(changed_rows(incoming, source_id, changed)):
        value = unpack(row['value'])
        fact = value['accepted'] if row['format_version'] == 6 else value
        facts.extend([fact] + (value['alternatives'] if row['format_version'] == 6 else []))
    with shadow.lock, shadow.connect() as db:
        db.execute('ATTACH DATABASE ? AS accepted', (str(store.path),))
        db.execute('BEGIN')
        # The read boundary is captured on the attached database itself.
        context = signature_attached(db)
        since = db.execute('SELECT revision FROM accepted.performance_state WHERE id=1').fetchone()[0]
        for table in ('settings', 'sources', 'session_metadata', 'response_claims', 'projection_dependencies', 'overlap_summary', 'project_memberships'):
            copy_rows(db, table)
        db.execute("INSERT INTO sources(id,label,kind,revision,status,updated) VALUES(?,?,'import',?,'Imported',?) "
            'ON CONFLICT(id) DO UPDATE SET label=excluded.label,revision=excluded.revision,status=excluded.status,updated=excluded.updated',
            (source_id, str(manifest.get('label') or 'Imported computer')[:200], manifest['revision'], manifest.get('created_at')))
        # Recompute the closure against the same snapshot used for input copying.
        required = closure(db, changed | removed, facts, cooperate)
        for segment in units(required):
            for table in FACT_TABLES:
                copy_rows(db, table, 'segment_id=?', (segment,))
            copy_rows(db, 'session_projects', 'segment_id=?', (segment,))
        groups = {'copy:' + segment for segment in required}
        groups.update('overlap:' + row[0] for segment in required for row in db.execute('SELECT session_id FROM session_metadata WHERE segment_id=?', (segment,)))
        groups.update('overlap:' + fact['id'] for fact in facts)
        for group in units(groups):
            copy_rows(db, 'history_choices', 'group_id=?', (group,))
        old_sessions = {r[0] for segment in changed | removed for r in db.execute('SELECT session_id FROM candidates WHERE source_id=? AND segment_id=?', (source_id, segment))}
        old_active = {segment: row[0] for segment in changed | removed
            for row in db.execute('SELECT session_id FROM session_metadata WHERE segment_id=?', (segment,))}
        old_identities = {tuple(r) for segment in changed | removed for r in db.execute('SELECT provider,session_id FROM session_metadata WHERE segment_id=?', (segment,))}
        relation_ids = old_sessions | {fact['id'] for fact in facts} | {fact['parent_session_id'] for fact in facts if fact.get('parent_session_id')}
        for segment in units(changed | removed):
            for table in FACT_TABLES[1:]:
                db.execute('DELETE FROM ' + table + ' WHERE source_id=? AND segment_id=?', (source_id, segment))
            db.execute('DELETE FROM history_choices WHERE scope=? AND group_id=?', (source_id, 'copy:' + segment))
        # Reconstitute affected overlap choices from all incoming envelopes. They
        # can be repeated by an unchanged same-session segment.
        overlap_groups = {'overlap:' + fact['id'] for fact in facts} | {'overlap:' + sid for sid in old_sessions}
        for group in units(overlap_groups):
            db.execute('DELETE FROM history_choices WHERE group_id=? AND scope=?', (group, source_id))
        providers = {r[0] for r in incoming.execute('SELECT DISTINCT provider FROM transfer_fingerprints WHERE source_id=?', (source_id,))}
        from .history_transfers import accept
        from .copy_store import save_choice
        for row in units(changed_rows(incoming, source_id, changed)):
            value = unpack(row['value'])
            fact = value['accepted'] if row['format_version'] == 6 else value
            if row['format_version'] == 6:
                accept(db, source_id, value)
            else:
                shadow.put_candidate(db, source_id, fact)
        for group in units(overlap_groups):
            for row in incoming.execute('SELECT segment_id,value FROM transfer_fingerprints WHERE source_id=? AND session_id=? AND format_version=6', (source_id, group[8:])):
                if row['segment_id'] in changed:
                    continue
                value = unpack(row['value'])
                if value['accounting_selection']:
                    choice = value['accounting_selection']
                    save_choice(db, group, choice['selected'], choice['reviewed'], source_id)
        selected = {segment for segment in units(changed | removed) if shadow.choose_canonical(db, segment)}
        # Presence starts at the earliest segment in a session. A changed
        # creation boundary affects the other pages of that same session too.
        affected_sessions = {old_active[segment] for segment in selected if segment in old_active}
        affected_sessions.update(r[0] for segment in selected for r in db.execute('SELECT session_id FROM session_metadata WHERE segment_id=?', (segment,)))
        selected.update(r[0] for sid in affected_sessions
            for r in db.execute('SELECT segment_id FROM session_metadata WHERE session_id=?', (sid,)))
        affected = shadow.related_segments(db, selected, affected_sessions)
        # New claims can connect a formerly unrelated accounting owner.
        extra = closure(db, affected, facts, cooperate) - required
        if extra:
            # All claim competitors were discovered from incoming facts above;
            # this guard makes future dependency rules fail safely.
            raise ValueError('Accounting dependencies changed during staging; retry the import')
        if progress:
            progress({'phase': 'Calculating changed usage', 'recalculated': len(affected)})
        # Commit sparse work between calculation units so the owning writer
        # can service watcher work and cancellation without a live DB clone.
    for index, segment in enumerate(sorted(affected)):
        from .cooperative import checkpoint, cancelled
        cancelled(store)
        checkpoint(store)
        with shadow.lock, shadow.connect() as db:
            project_segments(shadow, db, [segment])
        if progress and index % 16 == 0:
            progress({'phase': 'Calculating changed usage', 'recalculated': index + 1, 'total_sessions': len(affected)})
    with shadow.connect() as db:
        return context, since, required, affected, providers, groups | overlap_groups, old_identities, relation_ids


def signature_attached(db):
    from .isolated_jobs import quote
    class Accepted:
        def execute(self, sql, args=()):
            import re
            names = ('settings', 'sources')
            return db.execute(re.sub(r'\b(' + '|'.join(names) + r')\b', lambda m: 'accepted.' + quote(m[0]), sql), args)
    return signature(Accepted(), PROJECTION_VERSION)
