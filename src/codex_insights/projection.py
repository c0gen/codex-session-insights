"""Convert canonical session facts to indexed, date-filterable metric records."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .accounting.change_accounting import event_signature
from .accounting.pricing import estimate_token_cost
from .accounting.token_reconciliation import reconcile_sessions
from .codec import digest, unpack
from .copy_store import variants
from .copy_reconciliation import compatible
from .buckets import update_segment
from .project_groups import register_session
from .session_presence import SessionPresence

MIN = datetime.min.replace(tzinfo=timezone.utc)
MAX = datetime.max.replace(tzinfo=timezone.utc)
# Separate from parser/bucket versions: imported and offline facts also need
# replay reconciliation rerun when its rules change.
PROJECTION_VERSION = 6
COLUMNS = ("event_id segment_id session_id source_id project_id kind ts day hour weekday model effort tier total input cached writes output reasoning cost priced prompts added removed unknown unsupported unknown_size resolved_at cache_discount cache_priced provider").split()
KNOWN_COLUMNS = ['known_' + name for name in ('total', 'input', 'cached', 'writes', 'output', 'reasoning')]
COLUMNS += KNOWN_COLUMNS + ['completion_unavailable']


class Lineage:
    def __init__(self, db):
        self.db, self.cache = db, {}

    def get(self, sid, default=None):
        if sid not in self.cache:
            row = self.db.execute("SELECT fact FROM canonical WHERE session_id=? ORDER BY trace_count DESC,segment_id LIMIT 1", (sid,)).fetchone()
            self.cache[sid] = unpack(row[0]) if row else None
            if row:
                fact = self.cache[sid]
                fact['_boundary_variants'] = [v['fact'] for v in variants(self.db, fact['segment_id'])
                                               if compatible(fact, v['fact'])]
        return self.cache[sid] or default


def project_segments(store, db, segments, progress=None):
    segments = sorted(segments)
    timezone_name = store.setting("timezone", "America/New_York")
    zone = ZoneInfo(timezone_name)
    fast = store.setting("assumed_fast_percent", 0) / 100
    from .pricing_catalog import parse_catalog
    catalog = store.setting('pricing_catalog')
    rate_records = parse_catalog(catalog) if catalog is not None else None
    lineage = Lineage(db)
    presence = SessionPresence(db)
    from .providers.reconciliation import accounting_segments, response_owners, slices
    from .providers.pricing import estimate
    from .history_overlaps import groups as overlap_groups
    from .hot_metadata import accounting_dependencies, update_overlaps
    context_segments = accounting_dependencies(db, segments)
    provider_sessions = {row[0] for sid in context_segments for row in db.execute(
        "SELECT session_id FROM session_metadata WHERE segment_id=? AND provider!='codex'", (sid,))}
    overlaps = overlap_groups(db, session_ids=provider_sessions)
    update_overlaps(db, provider_sessions, overlaps)
    suppressed = set().union(*(g['suppressed'] for g in overlaps))
    owners = response_owners(db, segments, suppressed)
    overlap_states = {sid: g['state'] for g in overlaps for sid in g['suppressed']}
    for index, segment_id in enumerate(segments):
        if progress and index % 100 == 0:
            progress({"phase": "Correcting stored usage", "sessions": index, "total_sessions": len(segments)})
        row = db.execute("SELECT * FROM canonical WHERE segment_id=?", (segment_id,)).fetchone()
        if not row:
            continue
        fact = unpack(row["fact"])
        register_session(db, segment_id, fact)
        db.execute("UPDATE canonical SET project_id=?,project_label=? WHERE segment_id=?", (fact["project_id"], fact["project_label"], segment_id))
        db.execute("DELETE FROM records WHERE segment_id=?", (segment_id,))
        if segment_id in suppressed:
            update_segment(db, segment_id)
            diagnostic = json.loads(row['diagnostic'] or '{}')
            diagnostic['accounting_overlap'] = 'legacy_identity_overlap'
            diagnostic['accounting_overlap_state'] = overlap_states[segment_id]
            db.execute('UPDATE canonical SET diagnostic=? WHERE segment_id=?', (json.dumps(diagnostic), segment_id))
            continue
        provider = fact.get("provider", "codex")
        if provider == "codex":
            reconcile_sessions([fact], lineage, MIN, MAX)
        else:
            fact["token_slices"] = slices(fact, owners)
            fact["token_reconciliation_method"] = "stable_response_identity"
        records = []

        def add(kind, t, key, **values):
            if t is None:
                return
            local = t.astimezone(zone)
            rec = {"event_id": digest(key), "segment_id": segment_id, "session_id": fact["id"],
                "provider": provider, "source_id": row["source_id"], "project_id": fact["project_id"], "kind": kind,
                "ts": t.isoformat(), "day": local.date().isoformat(), "hour": local.hour, "weekday": local.weekday(),
                "model": values.pop("model", None), **values}
            records.append(tuple(rec.get(k, 0 if k in COLUMNS[13:19] + KNOWN_COLUMNS + ["priced", "prompts", "added", "removed", "unknown", "unsupported", "unknown_size", 'completion_unavailable'] else None) for k in COLUMNS))

        for index, item in enumerate(fact.get("token_slices", [])):
            usage = item["usage"]
            price = estimate_token_cost(item.get("model"), usage, service_tier=item.get("service_tier"),
                service_tier_logged=bool(item.get("service_tier")), assumed_fast_share=fast,
                at=item["timestamp"], request_input_tokens=item.get("request_input_tokens"),
                rate_records=rate_records) if provider == 'codex' else estimate(item)
            if fact.get('snapshot_mode') == 'complete_binary':
                from .providers.legacy.pricing import estimate as legacy_estimate
                price = legacy_estimate(item)
            add("usage", item["timestamp"], [segment_id, "usage", index], model=item.get("model") or "Unknown",
                effort=item.get("effort") or "Unknown", tier=item.get("service_tier") or "Not logged",
                total=usage["total_tokens"], input=usage["input_tokens"], cached=usage["cached_input_tokens"],
                writes=usage.get("cache_write_input_tokens", 0), output=usage["output_tokens"], reasoning=usage["reasoning_output_tokens"],
                cost=price["usd"] if price else None, priced=int(bool(price)),
                cache_discount=price["cache_discount_usd"] if price else None,
                cache_priced=usage["cached_input_tokens"] if price else 0,
                **{'known_' + column: int(usage.get(component) is not None and (column != 'reasoning' or provider == 'codex' or fact.get('snapshot_mode') == 'complete_binary' or fact.get('history_mode') == 'antigravity_steps'))
                    for column, component in zip(('total','input','cached','writes','output','reasoning'),
                        ('total_tokens','input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens'))})
        # These timestamps/counts contain no text. Duplicate message envelopes were removed at parsing.
        seen = set()
        parent, spawn = fact.get("parent_session_id"), fact.get("spawn_timestamp")
        inherited = set()
        inherited_messages = set()
        visited = {fact["id"]}
        while parent and parent not in visited:
            visited.add(parent)
            ancestor = lineage.get(parent)
            if not ancestor:
                break
            inherited.update(event_signature(e) for e in ancestor.get("change_events", []) if e.get("call_id") and spawn and e["timestamp"] < spawn)
            inherited_messages.update(m['signature'] for m in ancestor.get('messages',[]) if spawn and m['timestamp'] < spawn)
            parent = ancestor.get("parent_session_id")
        for message in fact.get("messages", []):
            if message['role'] == 'user' and message['signature'] not in inherited_messages:
                add("message", message["timestamp"], [segment_id, message["signature"]],
                    model=message.get("model") or "Unknown", prompts=1)
        for index, edit in enumerate(fact.get("change_events", [])):
            sig = event_signature(edit)
            if sig in seen or sig in inherited:
                continue
            seen.add(sig)
            confirmed = edit["outcome"] == "confirmed" and bool(edit.get("call_id"))
            add("edit", edit["timestamp"], [fact["id"], "edit", sig if edit.get("call_id") else [segment_id, index]],
                model=edit.get("model") or "Unknown", added=edit["added"] if confirmed else 0, removed=edit["removed"] if confirmed else 0,
                unknown=int(edit["outcome"] == "unknown"), unsupported=int(not edit["supported"]),
                unknown_size=int(edit["unknown_size"] and edit["outcome"] != "failed"),
                resolved_at=edit.get("resolved_at").isoformat() if edit.get("resolved_at") else None,
                completion_unavailable=int(confirmed and edit.get('resolved_at') is None))
        for child in fact.get('subagent_relationships', []):
            add('subagent_presence', child['timestamp'], [segment_id,'subagent',child['id']],
                session_id=child['id'], model='Unknown')
        # Date filters have whole-day precision. One presence marker per local
        # day/model supports filtered counts without indexing every tool log.
        # A paginated segment is still the same session. Use its earliest
        # observed creation boundary, never a parent's inherited timestamps.
        active_days = presence.days(fact, zone)
        for (_, model), t in active_days.items():
            add("presence", t, [segment_id, "presence", model, t], model=model)
        # Preserve the compact existing activity contract (one row per day).
        daily_activity = {}
        for (day, _), t in active_days.items():
            daily_activity[day] = max(t, daily_activity.get(day, t))
        for t in daily_activity.values():
            add("activity", t, [segment_id, "activity", t], model="Unknown")
        db.executemany("INSERT OR IGNORE INTO records(" + ",".join(COLUMNS) + ") VALUES(" + ",".join("?" for _ in COLUMNS) + ")", records)
        update_segment(db,segment_id)
        last = max(fact.get("activity", []) or [fact["metadata_timestamp"]])
        diagnostic = json.loads(row["diagnostic"] or "{}")
        diagnostic.pop('accounting_overlap', None)
        diagnostic.pop('accounting_overlap_state', None)
        diagnostic.update(accounting=fact.get("token_reconciliation_method"),
                          replay_tokens=fact.get("verified_replay_usage", {}).get("total_tokens", 0))
        diagnostic['edit_completion_time_unavailable'] = sum(e['outcome'] == 'confirmed' and e.get('resolved_at') is None for e in fact.get('change_events', []))
        if fact.get('provenance'):
            diagnostic['provenance'] = fact['provenance']
        db.execute("UPDATE canonical SET last_active=?,diagnostic=? WHERE segment_id=?", (last.isoformat(), json.dumps(diagnostic), segment_id))
    db.executemany('DELETE FROM projection_queue WHERE segment_id=?', [(sid,) for sid in segments])
    db.executemany('DELETE FROM projection_dependencies WHERE segment_id=?', [(sid,) for sid in segments])


def rebuild_projection(store, progress=None):
    if getattr(store, '_staging_projection', False):
        return
    from . import projection_state
    with store.lock, store.connect() as db:
        staged = bool(getattr(store, 'cooperate', None) or projection_state.status(db)['pending'])
        projection_state.request(db)
    if staged:
        from .staged_projection import rebuild
        store._staging_projection = True
        try:
            return rebuild(store, project_segments, PROJECTION_VERSION, progress)
        finally:
            store._staging_projection = False
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        segments = [r[0] for r in db.execute("SELECT segment_id FROM candidates UNION SELECT segment_id FROM canonical")]
        db.execute("DELETE FROM records")
        db.execute("DELETE FROM metric_buckets")
        for sid in segments:
            store.choose_canonical(db, sid)
        if progress:
            project_segments(store, db, segments, progress)
        else:
            project_segments(store, db, segments)
        db.execute("INSERT OR REPLACE INTO settings VALUES('bucket_version','2')")
        revision = store.setting("data_revision", 0) + 1
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(revision),))
        db.execute("DELETE FROM projection_queue")
        db.execute("INSERT OR REPLACE INTO settings VALUES('projection_version',?)", (json.dumps(PROJECTION_VERSION),))
        projection_state.publish(db)
    projection_state.activate(store)


def ensure_projection(store, progress=None):
    """Upgrade stored facts atomically, retrying after an interrupted rebuild."""
    from .projection_state import needs_rebuild
    if not needs_rebuild(store, PROJECTION_VERSION):
        return False
    rebuild_projection(store, progress)
    return True
