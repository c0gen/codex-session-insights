"""Convert canonical session facts to indexed, date-filterable metric records."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .accounting.change_accounting import event_signature
from .accounting.pricing import estimate_token_cost
from .accounting.token_reconciliation import reconcile_sessions
from .codec import digest, unpack

MIN = datetime.min.replace(tzinfo=timezone.utc)
MAX = datetime.max.replace(tzinfo=timezone.utc)
COLUMNS = ("event_id segment_id session_id source_id project_id kind ts day hour weekday model effort tier total input cached writes output reasoning cost priced prompts added removed unknown unsupported unknown_size resolved_at").split()


class Lineage:
    def __init__(self, db):
        self.db, self.cache = db, {}

    def get(self, sid, default=None):
        if sid not in self.cache:
            row = self.db.execute("SELECT fact FROM canonical WHERE session_id=? ORDER BY trace_count DESC,segment_id LIMIT 1", (sid,)).fetchone()
            self.cache[sid] = unpack(row[0]) if row else None
        return self.cache[sid] or default


def project_segments(store, db, segments):
    timezone_name = store.setting("timezone", "America/New_York")
    zone = ZoneInfo(timezone_name)
    fast = store.setting("assumed_fast_percent", 0) / 100
    lineage = Lineage(db)
    for segment_id in segments:
        row = db.execute("SELECT * FROM canonical WHERE segment_id=?", (segment_id,)).fetchone()
        if not row:
            continue
        fact = unpack(row["fact"])
        aliases=store.setting("project_aliases", {})
        visited_projects=set()
        while fact["project_id"] in aliases and fact["project_id"] not in visited_projects:
            visited_projects.add(fact["project_id"])
            alias=aliases[fact["project_id"]]
            fact.update(project_id=alias["id"], project_label=alias["name"])
        db.execute("UPDATE canonical SET project_id=?,project_label=? WHERE segment_id=?", (fact["project_id"], fact["project_label"], segment_id))
        db.execute("DELETE FROM records WHERE segment_id=?", (segment_id,))
        reconcile_sessions([fact], lineage, MIN, MAX)
        records = []

        def add(kind, t, key, **values):
            if t is None:
                return
            local = t.astimezone(zone)
            rec = {"event_id": digest(key), "segment_id": segment_id, "session_id": fact["id"],
                "source_id": row["source_id"], "project_id": fact["project_id"], "kind": kind,
                "ts": t.isoformat(), "day": local.date().isoformat(), "hour": local.hour, "weekday": local.weekday(),
                "model": values.pop("model", None), **values}
            records.append(tuple(rec.get(k, 0 if k in COLUMNS[13:19] + ["priced", "prompts", "added", "removed", "unknown", "unsupported", "unknown_size"] else None) for k in COLUMNS))

        for index, item in enumerate(fact.get("token_slices", [])):
            usage = item["usage"]
            price = estimate_token_cost(item.get("model"), usage, service_tier=item.get("service_tier"),
                service_tier_logged=bool(item.get("service_tier")), assumed_fast_share=fast,
                at=item["timestamp"], request_input_tokens=item.get("request_input_tokens"))
            add("usage", item["timestamp"], [segment_id, "usage", index], model=item.get("model") or "Unknown",
                effort=item.get("effort") or "Unknown", tier=item.get("service_tier") or "Not logged",
                total=usage["total_tokens"], input=usage["input_tokens"], cached=usage["cached_input_tokens"],
                writes=usage.get("cache_write_input_tokens", 0), output=usage["output_tokens"], reasoning=usage["reasoning_output_tokens"],
                cost=price["usd"] if price else None, priced=int(bool(price)))
        # These timestamps/counts contain no text. Duplicate message envelopes were removed at parsing.
        for message in fact.get("messages", []):
            add("message", message["timestamp"], [segment_id, message["signature"]],
                model=message.get("model") or "Unknown", prompts=int(message["role"] == "user"))
        seen = set()
        parent, spawn = fact.get("parent_session_id"), fact.get("spawn_timestamp")
        inherited = set()
        visited = {fact["id"]}
        while parent and parent not in visited:
            visited.add(parent)
            ancestor = lineage.get(parent)
            if not ancestor:
                break
            inherited.update(event_signature(e) for e in ancestor.get("change_events", []) if e.get("call_id") and spawn and e["timestamp"] < spawn)
            parent = ancestor.get("parent_session_id")
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
                resolved_at=edit.get("resolved_at").isoformat() if edit.get("resolved_at") else None)
        for t in set(fact.get("activity", [])):
            add("activity", t, [segment_id, "activity", t], model="Unknown")
        db.executemany("INSERT OR IGNORE INTO records(" + ",".join(COLUMNS) + ") VALUES(" + ",".join("?" for _ in COLUMNS) + ")", records)
        last = max(fact.get("activity", []) or [fact["metadata_timestamp"]])
        diagnostic = json.loads(row["diagnostic"] or "{}")
        diagnostic.update(accounting=fact.get("token_reconciliation_method"),
                          replay_tokens=fact.get("verified_replay_usage", {}).get("total_tokens", 0))
        db.execute("UPDATE canonical SET last_active=?,diagnostic=? WHERE segment_id=?", (last.isoformat(), json.dumps(diagnostic), segment_id))


def rebuild_projection(store):
    with store.lock, store.connect() as db:
        segments = [r[0] for r in db.execute("SELECT segment_id FROM candidates UNION SELECT segment_id FROM canonical")]
        db.execute("DELETE FROM records")
        for sid in segments:
            store.choose_canonical(db, sid)
        project_segments(store, db, segments)
        revision = store.setting("data_revision", 0) + 1
        db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(revision),))
