"""Fast dashboard queries against indexed metric records."""
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

from .codec import unpack


def filter_clause(filters, zone):
    today = datetime.now(zone).date()
    selected = filters.get("range", "all")
    start = None
    end = today + timedelta(days=1)
    if selected in {"today", "7", "30", "90"}:
        start = today - timedelta(days=(1 if selected == "today" else int(selected)) - 1)
    if selected == "custom":
        start = date.fromisoformat(filters["start"])
        end = date.fromisoformat(filters["end"]) + timedelta(days=1)
        if start >= end:
            raise ValueError("Start date must not follow end date")
    to_utc = lambda day: datetime.combine(day, datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
    clauses, params = ["r.ts < ?"], [to_utc(end)]
    if start:
        clauses.append("r.ts >= ?"); params.append(to_utc(start))
    for field in ("project_id", "model", "source_id"):
        if filters.get(field):
            clauses.append("r." + field + " = ?"); params.append(filters[field])
    return " AND ".join(clauses), params, to_utc(end)


def equivalents(total, output):
    def convert(tokens):
        words = tokens * .75
        pages = math.ceil(words / 500)
        return {"words": round(words), "novels": words / 90000, "pages": pages,
                "stack_meters": pages * .004 * .0254, "reading_years": words / 150 / 60 / 24 / 365.25,
                "typing_years": words / 60 / 60 / 24 / 365.25, "floppy_disks": tokens * 4 / 1440000}
    return {"total": convert(total), "output": convert(output)}


def streaks(days, today):
    dates = sorted(date.fromisoformat(d) for d in days)
    longest = run = 0
    previous = None
    for day in dates:
        run = run + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, run); previous = day
    current = 0
    day = today if today in dates else today - timedelta(days=1)
    active = set(dates)
    while day in active:
        current += 1; day -= timedelta(days=1)
    return {"current": current, "longest": longest}


def dashboard(store, filters=None):
    filters = filters or {}
    zone_name = store.setting("timezone", "America/New_York")
    zone = ZoneInfo(zone_name)
    where, params, end = filter_clause(filters, zone)
    table = 'metric_buckets' if store.setting('bucket_version') == 1 else 'records'
    responses = 'sum(event_count)' if table == 'metric_buckets' else 'count(*)'
    event_count = 'r.event_count' if table == 'metric_buckets' else '1'
    # Delayed confirmations cannot retroactively count as confirmed at an earlier cutoff.
    added = "CASE WHEN r.resolved_at < '" + end + "' THEN r.added ELSE 0 END"
    removed = "CASE WHEN r.resolved_at < '" + end + "' THEN r.removed ELSE 0 END"
    unknown = "CASE WHEN r.kind='edit' AND r.resolved_at >= '" + end + "' THEN " + event_count + " ELSE r.unknown END"
    fields = "sum(r.total) total_tokens,sum(r.input) input_tokens,sum(r.cached) cached_tokens,sum(r.writes) cache_write_tokens,sum(r.output) output_tokens,sum(r.reasoning) reasoning_tokens,sum(r.cost) cost,sum(CASE WHEN r.priced=1 THEN r.total ELSE 0 END) priced_tokens,sum(r.prompts) prompts,sum(" + added + ") lines_added,sum(" + removed + ") lines_removed,sum(" + unknown + ") unknown_edits,sum(r.unsupported) unsupported_edits,sum(r.unknown_size) unknown_size_edits"
    with store.connect() as db:
        summary = {k: v or 0 for k, v in dict(db.execute("SELECT " + fields + " FROM " + table + " r WHERE " + where, params).fetchone()).items()}
        summary["cost"] = round(summary["cost"], 2)
        chats = db.execute("SELECT count(DISTINCT c.session_id) FROM canonical c JOIN " + table + " r ON r.segment_id=c.segment_id WHERE c.category='top_level' AND " + where, params).fetchone()[0]
        summary["chats"] = chats
        timeline = [dict(row) for row in db.execute("SELECT day,sum(total) tokens,sum(cost) cost,sum(prompts) prompts,sum(" + added + ")+sum(" + removed + ") lines FROM " + table + " r WHERE " + where + " GROUP BY day ORDER BY day", params)]
        for row in timeline:
            row["cost"] = round(row["cost"] or 0, 4)
        projects = [dict(row) for row in db.execute("SELECT r.project_id,c.project_label name,count(DISTINCT CASE WHEN c.category='top_level' THEN r.session_id END) chats,sum(r.total) tokens,sum(r.cost) cost,sum(" + added + ") added,sum(" + removed + ") removed,max(r.day) last_active FROM " + table + " r JOIN canonical c ON c.segment_id=r.segment_id WHERE " + where + " GROUP BY r.project_id ORDER BY tokens DESC", params)]
        models = [dict(row) for row in db.execute("SELECT model name,sum(total) tokens,sum(cost) cost FROM " + table + " r WHERE kind='usage' AND " + where + " GROUP BY model ORDER BY tokens DESC", params)]
        heatmap = [dict(row) for row in db.execute("SELECT weekday,hour,sum(prompts) count FROM " + table + " r WHERE prompts>0 AND " + where + " GROUP BY weekday,hour", params)]
        tiers = [dict(row) for row in db.execute("SELECT tier name," + responses + " responses,sum(total) tokens FROM " + table + " r WHERE kind='usage' AND " + where + " GROUP BY tier ORDER BY tokens DESC", params)]
        efforts = [dict(row) for row in db.execute("SELECT effort name," + responses + " responses FROM " + table + " r WHERE kind='usage' AND " + where + " GROUP BY effort ORDER BY responses DESC", params)]
        agents = [dict(row) for row in db.execute("SELECT c.category name,count(DISTINCT r.session_id) sessions,sum(r.total) tokens FROM " + table + " r JOIN canonical c ON c.segment_id=r.segment_id WHERE " + where + " GROUP BY c.category", params)]
        options = {"projects": [dict(r) for r in db.execute("SELECT project_id id,project_label name FROM canonical GROUP BY project_id ORDER BY project_label")],
                   "models": [r[0] for r in db.execute("SELECT model FROM " + table + " WHERE kind='usage' GROUP BY model ORDER BY model")]}
        diagnostics = [json.loads(r[0] or "{}") for r in db.execute("SELECT diagnostic FROM canonical")]
    active = [row["day"] for row in timeline if row["prompts"]]
    summary.update(active_days=len(active), **streaks(active, datetime.now(zone).date()))
    summary["priced_percent"] = round(summary["priced_tokens"] / summary["total_tokens"] * 100, 1) if summary["total_tokens"] else 0
    summary["change_coverage"] = "partial" if summary["unknown_edits"] or summary["unsupported_edits"] or summary["unknown_size_edits"] else "observed" if summary["lines_added"] or summary["lines_removed"] else "no_observed_changes"
    milestone = max(1_000_000_000, (summary["total_tokens"] // 1_000_000_000 + 1) * 1_000_000_000)
    highlights = {"busiest": max(timeline, key=lambda x:x["tokens"], default=None), "expensive": max(timeline, key=lambda x:x["cost"], default=None), "milestone": milestone}
    return {"summary": summary, "timeline": timeline, "projects": projects, "models": models, "heatmap": heatmap,
            "tiers": tiers, "efforts": efforts, "agents": agents, "highlights": highlights,
            "equivalents": equivalents(summary["total_tokens"], summary["output_tokens"]), "options": options,
            "sources": store.sources(), "filters": {"range":"all","project_id":"","model":"","source_id":"","start":"","end":"",**filters}, "timezone": zone_name, "revision": store.setting("data_revision", 0),
            "generated_at": datetime.now(timezone.utc).isoformat(), "demo": store.setting("demo", False),
            "coverage": {"conflicts": sum(bool(x.get("conflicts")) for x in diagnostics),
                         "parse_errors": sum(x.get("parse_errors", 0) for x in diagnostics),
                         "replay_tokens": sum(x.get("replay_tokens", 0) for x in diagnostics),
                         "unresolved": sum(x.get("accounting") in {"parent_missing", "no_parent_alignment", "raw_trace_unavailable"} for x in diagnostics)},
            "settings": {"assumed_fast_percent": store.setting("assumed_fast_percent", 0), "device_label": store.setting("device_label", "This computer")}}
