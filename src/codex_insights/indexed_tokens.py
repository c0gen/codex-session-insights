"""All-time provider counters from the same canonical snapshot as analytics."""
from .providers import LABELS
from .grouped_coverage import coverage_groups


def indexed_token_totals(db, table, where, params):
    groups = coverage_groups(db, table, where, params, 'provider')
    result = {}
    for provider in LABELS:
        state = groups.get(provider, {'state': 'unavailable', 'sessions': 0})
        result[provider] = {"total_tokens": state['total_tokens'] if state["state"] != "unavailable" else None,
                            "state": state["state"], "sessions": state["sessions"]}
    return result
