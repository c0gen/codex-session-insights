"""Materialize one accepted accounting history without discarding alternatives."""
import json

from . import project_groups
from .codec import unpack
from .copy_reconciliation import compatible, evidence_revision, select, variant_id
from .copy_store import effective_choice, pending_sources, retain, variants


def choose(db, segment_id):
    candidates = db.execute("SELECT c.* FROM candidates c JOIN sources s ON s.id=c.source_id "
                            "WHERE c.segment_id=? AND s.enabled=1 ORDER BY c.record_count DESC,c.parser_version DESC,c.source_id",
                            (segment_id,)).fetchall()
    old = db.execute("SELECT * FROM canonical WHERE segment_id=?", (segment_id,)).fetchone()
    if not candidates:
        from .hot_metadata import update_claims
        update_claims(db, segment_id)
        for table in ("canonical", "session_projects", "records", "metric_buckets"):
            db.execute("DELETE FROM " + table + " WHERE segment_id=?", (segment_id,))
        return bool(old)
    # Also supports legacy fixtures and previously stored provider facts.
    for row in candidates:
        if not db.execute("SELECT 1 FROM history_variants WHERE source_id=? AND segment_id=? AND variant_id=?",
                          (row["source_id"], segment_id, variant_id(unpack(row["fact"])))).fetchone():
            retain(db, row["source_id"], unpack(row["fact"]), row["parser_version"])
    items = variants(db, segment_id)
    old_fact = unpack(old["fact"]) if old else None
    previous = {"source_id": old["source_id"], "variant_id": variant_id(old_fact), "fact": old_fact} if old else None
    if previous is None:
        accepted = unpack(candidates[0]['fact'])
        previous = {'source_id': candidates[0]['source_id'], 'variant_id': variant_id(accepted), 'fact': accepted}
    if old_fact and (old_fact.get("snapshot_mode") == "complete_binary" or old_fact.get("history_mode") == "antigravity_steps"):
        current = next((r for r in candidates if r["source_id"] == old["source_id"]), None)
        if current:
            previous = {"source_id": current["source_id"], "variant_id": variant_id(unpack(current["fact"]))}
    preferred = old["source_id"] if old else candidates[0]["source_id"]
    decision = effective_choice(db, "copy:" + segment_id, preferred)
    pending = pending_sources(db, segment_id)
    winner, state = select(items, previous, decision, bool(pending))
    fact = winner["fact"]
    previous_diagnostic = json.loads(old["diagnostic"] or "{}") if old else {}
    conflicts = sorted({v["source_id"] for v in items if not compatible(v["fact"], fact)}) if state == "needs_review" else []
    diagnostic = {**previous_diagnostic, "conflicts": conflicts, "copy_state": state,
                  "copy_revision": evidence_revision(items, pending), "copy_accepted": winner["variant_id"],
                  "copy_variant_count": len(items), "parse_errors": fact.get("parse_errors", 0)}
    project_groups.register_session(db, segment_id, fact)
    from .codec import pack
    packed = pack(fact)
    changed = not old or old["fact"] != packed or old["source_id"] != winner["source_id"]
    if not changed:
        db.execute("UPDATE canonical SET diagnostic=? WHERE segment_id=?", (json.dumps(diagnostic), segment_id))
        return diagnostic != previous_diagnostic
    db.execute("INSERT OR REPLACE INTO canonical(segment_id,source_id,session_id,parent_id,project_id,project_label,"
               "category,last_active,trace_count,fact,diagnostic,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
        segment_id, winner["source_id"], fact["id"], fact.get("parent_session_id"), fact["project_id"], fact["project_label"],
        fact["session_source"], None, len(fact["raw_token_trace"]), packed, json.dumps(diagnostic), fact.get("provider", "codex")))
    from .hot_metadata import update_claims
    update_claims(db, segment_id, fact)
    return True
