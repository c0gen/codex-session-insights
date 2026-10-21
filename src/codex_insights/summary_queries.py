"""Shared headline aggregation for the dashboard and small desktop surfaces."""


def edit_expressions(table, end):
    event_count = "r.event_count" if table == "metric_buckets" else "1"
    added = "CASE WHEN r.resolved_at < '" + end + "' THEN r.added ELSE 0 END"
    removed = "CASE WHEN r.resolved_at < '" + end + "' THEN r.removed ELSE 0 END"
    unknown = "CASE WHEN r.kind='edit' AND r.resolved_at >= '" + end + "' THEN " + event_count + " ELSE r.unknown END"
    return added, removed, unknown


def query_summary(db, table, where, params, end, extras=None):
    added, removed, unknown = edit_expressions(table, end)
    fields = "sum(r.total) total_tokens,sum(r.input) input_tokens,sum(r.cached) cached_tokens,sum(r.writes) cache_write_tokens,sum(r.output) output_tokens,sum(r.reasoning) reasoning_tokens,sum(r.cost) cost,sum(CASE WHEN r.priced=1 THEN r.total ELSE 0 END) priced_tokens,sum(r.prompts) prompts,sum(" + added + ") lines_added,sum(" + removed + ") lines_removed,sum(" + unknown + ") unknown_edits,sum(r.unsupported) unsupported_edits,sum(r.unknown_size) unknown_size_edits"
    fields += ',sum(r.completion_unavailable) edit_completion_time_unavailable'
    if extras is not None:
        fields += ",sum(CASE WHEN r.kind='usage' THEN r.cache_discount ELSE 0 END) cache_discount,sum(CASE WHEN r.kind='usage' THEN r.cache_priced ELSE 0 END) cache_priced"
    summary = {k: v or 0 for k, v in dict(db.execute("SELECT " + fields + " FROM " + table + " r WHERE " + where, params).fetchone()).items()}
    if extras is not None:
        extras.update(discount=summary.pop('cache_discount'), priced=summary.pop('cache_priced'))
    summary["cost"] = round(summary["cost"], 2)
    summary["chats"] = db.execute("SELECT count(DISTINCT c.session_id) FROM session_metadata c WHERE c.category='top_level' "
        "AND c.segment_id IN (SELECT r.segment_id FROM " + table + " r WHERE " + where + ')', params).fetchone()[0]
    summary["priced_percent"] = round(summary["priced_tokens"] / summary["total_tokens"] * 100, 1) if summary["total_tokens"] else 0
    summary["change_coverage"] = "partial" if summary["unknown_edits"] or summary["unsupported_edits"] or summary["unknown_size_edits"] or summary['edit_completion_time_unavailable'] else "observed" if summary["lines_added"] or summary["lines_removed"] else "no_observed_changes"
    return summary
