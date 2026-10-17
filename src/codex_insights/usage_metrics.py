"""Additive cache estimates and distinct daily presence from indexed facts."""


def subset_percent(numerator, denominator):
    return 100 * numerator / denominator if denominator > 0 and 0 <= numerator <= denominator else None


def query_usage_metrics(db, table, where, params, summary):
    row = db.execute(
        "SELECT sum(r.cache_discount) discount,sum(r.cache_priced) priced FROM "
        + table + " r WHERE r.kind='usage' AND " + where, params).fetchone()
    cached = summary["cached_tokens"]
    priced = int(row["priced"] or 0)
    return {
        "cache_reuse_percent": subset_percent(cached, summary["input_tokens"]),
        "reasoning_share_percent": subset_percent(summary["reasoning_tokens"], summary["output_tokens"]),
        "cache_discount_usd": (row["discount"] or 0) if priced or not cached else None,
        "cache_discount_priced_tokens": priced,
        "cache_discount_total_tokens": cached,
        "cache_discount_coverage_percent": subset_percent(priced, cached),
    }


def query_daily_sessions(db, table, where, params):
    return [dict(row) for row in db.execute(
        "SELECT r.day,"
        "count(DISTINCT CASE WHEN c.category='top_level' AND r.kind='presence' THEN r.session_id END) chats,"
        "count(DISTINCT CASE WHEN c.category='spawned_subagent' OR r.kind='subagent_presence' THEN r.session_id END) subagents,"
        "count(DISTINCT CASE WHEN c.category='system_subagent' THEN r.session_id END) system_agents "
        "FROM " + table + " r JOIN canonical c ON c.segment_id=r.segment_id "
        "WHERE r.kind IN ('presence','subagent_presence') AND " + where + " GROUP BY r.day ORDER BY r.day", params)]
