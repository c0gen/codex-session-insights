"""Fast dashboard queries against indexed metric records."""
from .metric_queries import source as metric_source
from .buckets import current as current_buckets
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

from .codec import unpack
from .usage_metrics import query_usage_metrics, query_daily_sessions
from .usage_history import query_cache_rates, apply_reasoning_basis
from .projection import PROJECTION_VERSION
from .summary_queries import edit_expressions, query_summary
from .indexed_tokens import indexed_token_totals
from .project_groups import resolve_project, public_merge
from .date_ranges import date_window
from .filter_options import normalize_selections
from .grouped_coverage import coverage_groups


def filter_clause(filters, zone, today=None):
    today = today or datetime.now(zone).date()
    start, end = date_window(filters, today)
    to_utc = lambda day: datetime.combine(day, datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
    clauses, params = ["r.ts < ?"], [to_utc(end)]
    if start:
        clauses.append("r.ts >= ?"); params.append(to_utc(start))
    for field in ("project_id", "model", "source_id", "provider"):
        if field == "provider" and filters.get(field):
            from .providers import adapter
            adapter(filters[field])
        if filters.get(field):
            clauses.append("r.segment_id IN (SELECT segment_id FROM project_sessions WHERE project_id=?)" if field == "project_id" else "r." + field + " = ?")
            params.append(filters[field])
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
    filters = dict(filters or {})
    requested = dict(filters)
    view = filters.pop('_view', 'full')
    generated_at = datetime.now(timezone.utc)
    from .storage import tracked
    # Registered so app shutdown can interrupt a multi-second aggregate.
    with store.connect() as db, tracked(store, db):
        db.execute('PRAGMA cache_size=-65536')
        db.execute('PRAGMA temp_store=MEMORY')
        # Membership, aggregates and revision must come from the same snapshot;
        # a merge completing halfway through a query cannot lose filtered usage.
        db.execute("BEGIN")
        from .query_snapshot import DashboardResult, identity
        snapshot_key = identity(db, requested, generated_at)
        from .dashboard_aggregates import shared
        aggregate_cache = shared(store)
        aggregate_key = (*snapshot_key[:4], json.dumps(filters, sort_keys=True))
        def memo(name, calculate, unfiltered=False):
            key = snapshot_key[:4] if unfiltered else aggregate_key
            return aggregate_cache.get(key, name, calculate)
        settings = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM settings")}
        if filters.get("project_id"):
            filters = {**filters, "project_id": resolve_project(db, filters["project_id"])}
        table = 'metric_buckets' if current_buckets(settings.get('bucket_version')) else 'records'
        options = memo('options:' + table, lambda: {"projects": [dict(r) for r in db.execute("SELECT project_id id,name FROM project_sessions GROUP BY project_id ORDER BY name")],
                   "models": [r[0] for r in db.execute("SELECT model FROM " + table + " WHERE model IS NOT NULL AND model<>'' GROUP BY model ORDER BY model")]}, True)
        filters = normalize_selections(filters, options, (r[0] for r in db.execute('SELECT id FROM sources')))
        zone_name = settings.get("timezone", "America/New_York")
        zone = ZoneInfo(zone_name)
        today = generated_at.astimezone(zone).date()
        start_day, end_day = date_window(filters, today)
        where, params, end = filter_clause(filters, zone, today)
        responses = 'sum(event_count)' if table == 'metric_buckets' else 'count(*)'
        # Delayed confirmations cannot retroactively count at an earlier cutoff.
        added, removed, _ = edit_expressions(table, end)
        def summary_totals():
            discount = {}
            return query_summary(db, table, where, params, end, discount), discount
        summary, discount_totals = memo('summary:' + table, summary_totals)
        all_where, all_params, _ = filter_clause({"range": "all"}, zone, today)
        provider_totals = memo('provider_totals:' + table, lambda: coverage_groups(db, table, all_where, all_params, 'provider'), True)
        indexed_totals = memo('indexed_totals:' + table, lambda: indexed_token_totals(db, table, all_where, all_params, provider_totals), True)
        from .providers.history_coverage import source_states
        history_states = source_states(db, filters)
        usage_metrics = memo('usage_metrics:' + table, lambda: query_usage_metrics(db, table, where, params, summary, discount_totals))
        daily_sessions = query_daily_sessions(db, table, where, params) if view in ("full", "usage") and settings.get("projection_version") == PROJECTION_VERSION else []
        cache_rate_timeline = query_cache_rates(db, table, where, params) if view in ("full", "usage") else None
        timeline = memo('timeline:' + table, lambda: [dict(row) for row in db.execute("SELECT day,sum(total) tokens,sum(cost) cost,max(priced) cost_available,sum(prompts) prompts,sum(" + added + ")+sum(" + removed + ") lines FROM " + metric_source(table, where) + " WHERE " + where + " GROUP BY day ORDER BY day", params)])
        for row in timeline:
            row["cost"] = round(row["cost"] or 0, 4)
        projects = []
        if view in ("full", "projects"):
            from .project_totals import query_projects
            projects = query_projects(db, table, where, params, added, removed)
        models, heatmap, tiers, efforts, agents = [], [], [], [], []
        if view in ("full", "usage"):
            models = [dict(row) for row in db.execute("SELECT model name,sum(total) tokens,sum(cost) cost FROM " + metric_source(table, where) + " WHERE kind='usage' AND " + where + " GROUP BY model ORDER BY tokens DESC", params)]
            heatmap = [dict(row) for row in db.execute("SELECT weekday,hour,sum(prompts) count FROM " + metric_source(table, where) + " WHERE prompts>0 AND " + where + " GROUP BY weekday,hour", params)]
            tiers = [dict(row) for row in db.execute("SELECT tier name," + responses + " responses,sum(total) tokens FROM " + metric_source(table, where) + " WHERE kind='usage' AND " + where + " GROUP BY tier ORDER BY tokens DESC", params)]
            efforts = [dict(row) for row in db.execute("SELECT effort name," + responses + " responses FROM " + metric_source(table, where) + " WHERE kind='usage' AND " + where + " GROUP BY effort ORDER BY responses DESC", params)]
            agents = [dict(row) for row in db.execute("SELECT c.category name,count(DISTINCT r.session_id) sessions,sum(r.total) tokens FROM " + metric_source(table, where) + " JOIN session_metadata c ON c.segment_id=r.segment_id WHERE r.kind!='subagent_presence' AND " + where + " GROUP BY c.category", params)]
            embedded = db.execute("SELECT count(DISTINCT r.session_id) FROM " + metric_source(table, where) + " WHERE r.kind='subagent_presence' AND " + where, params).fetchone()[0]
            if embedded:
                agents.append({'name':'embedded_subagents','sessions':embedded,'tokens':None})
        diagnostic_rows = [r[0] or '{}' for r in db.execute('SELECT diagnostic FROM session_metadata')]
        diagnostic_values = {raw: json.loads(raw) for raw in set(diagnostic_rows)}
        diagnostics = [diagnostic_values[raw] for raw in diagnostic_rows]
        accounting_overlaps = db.execute("SELECT count(*) FROM overlap_summary WHERE state='needs_review'").fetchone()[0]
        filtered_diagnostics = [diagnostic_values[r[0] or '{}'] for r in db.execute('SELECT DISTINCT c.diagnostic FROM session_metadata c '
            'WHERE c.segment_id IN (SELECT r.segment_id FROM ' + metric_source(table, where) + ' WHERE ' + where + ')', params)]
        from .providers.schema import coverage
        from .grouped_coverage import combine_providers
        token_coverage = memo('token_coverage:' + table, lambda: combine_providers(provider_totals) if (where, params) == (all_where, all_params) else coverage(db, table, where, params))
        apply_reasoning_basis(db, where, params, summary, token_coverage, usage_metrics, table, discount_totals)
        sources = [dict(r) for r in db.execute("SELECT s.*, (SELECT count(*) FROM candidates c WHERE c.source_id=s.id) AS segments, (SELECT max(last_active) FROM session_metadata c WHERE c.source_id=s.id) AS last_activity FROM sources s ORDER BY kind,label")]
        source_diagnostics = {r[0]: json.loads(r[1]) for r in db.execute('SELECT source_id,payload FROM source_diagnostics')}
        from .index_health import summary as index_health_summary
        for source in sources:
            if source['kind'] == 'folder' and source['provider'] == 'codex':
                source['index_health'] = index_health_summary(db, source['id'])
    from .providers import adapter
    for source in sources:
        if source['id'] in source_diagnostics:
            source['legacy_diagnostics'] = source_diagnostics[source['id']]
        source["capabilities"] = adapter(source.get("provider", "codex")).capabilities if source.get("provider") != "mixed" else {}
    reasoning_state = token_coverage['metrics']['reasoning']['state']
    if token_coverage['metrics']['input']['state'] != 'complete' or token_coverage['metrics']['cached']['state'] != 'complete':
        usage_metrics['cache_reuse_percent'] = None
    if token_coverage['metrics']['cached']['state'] == 'unavailable':
        usage_metrics['cache_discount_usd'] = None
        usage_metrics['cache_discount_coverage_percent'] = None
    token_coverage["reasoning"] = 'recorded' if reasoning_state == 'complete' else reasoning_state
    summary["token_coverage"] = token_coverage["state"]
    summary['metric_coverage'] = token_coverage['metrics']
    completion_time_missing = summary['edit_completion_time_unavailable']
    summary["estimated_cost"] = summary["cost"] if summary["priced_tokens"] or (token_coverage["recorded_sessions"] and not summary["total_tokens"]) else None
    summary["analyzed_tokens"] = summary["total_tokens"] if token_coverage["recorded_sessions"] else None
    active = [row["day"] for row in timeline if row["prompts"]]
    summary.update(active_days=len(active), **streaks(active, today))
    milestone = max(1_000_000_000, (summary["total_tokens"] // 1_000_000_000 + 1) * 1_000_000_000)
    highlights = {"busiest": max(timeline, key=lambda x:x["tokens"], default=None), "expensive": max((r for r in timeline if r['cost_available']), key=lambda x:x["cost"], default=None), "milestone": milestone}
    return DashboardResult({"analytics_context": snapshot_key[0], "indexed_token_totals": indexed_totals, "usage_metrics": usage_metrics, "daily_sessions": daily_sessions, "cache_rate_timeline": cache_rate_timeline, "summary": summary, "timeline": timeline, "projects": projects, "models": models, "heatmap": heatmap,
            "tiers": tiers, "efforts": efforts, "agents": agents, "highlights": highlights,
            "equivalents": equivalents(summary["total_tokens"], summary["output_tokens"]), "options": options,
            "sources": sources, 'source_states': history_states, "filters": {"range":"all","project_id":"","model":"","source_id":"","provider":"","start":"","end":"",**filters}, "timezone": zone_name, "revision": settings.get("data_revision", 0),
            "date_bounds": {"start": start_day.isoformat() if start_day else timeline[0]["day"] if timeline else None,
                            "end": (end_day - timedelta(days=1)).isoformat()},
            "generated_at": generated_at.isoformat(), "demo": settings.get("demo", False),
            "coverage": {"tokens": token_coverage, "conflicts": sum(x.get("copy_state") == "needs_review" for x in diagnostics),
                         'edit_completion_time_unavailable': completion_time_missing,
                         'provenance': [d['provenance'] for d in filtered_diagnostics if d.get('provenance')],
                         "parse_errors": sum(x.get("parse_errors", 0) for x in diagnostics),
                         "awaiting_verification": sum(x.get("copy_state") == "awaiting_verification" for x in diagnostics),
                         "accounting_overlaps": accounting_overlaps,
                         "replay_tokens": sum(x.get("replay_tokens", 0) for x in diagnostics),
                         "unresolved": sum(x.get("accounting") in {"parent_missing", "no_parent_alignment", "raw_trace_unavailable"} for x in diagnostics)},
            "project_merge": public_merge(settings.get("last_project_merge")),
            "project_migration_pending": settings.get("project_groups_version") != 1,
            "settings": {"assumed_fast_percent": settings.get("assumed_fast_percent", 0), "device_label": settings.get("device_label", "This computer"), "live_usage_enabled": settings.get("live_usage_enabled", True)}}, snapshot_key)
