"""Aggregate fetched lifetime counters without mixing them with analyzed logs."""
from .account_data import nonnegative
from .account_identity import confirmed_identity
from .account_groups import connection_groups


def account_token_total(connections, enabled=True, allowed=True):
    # Multiple connections can follow the same Codex sign-in. Count its freshest
    # available lifetime counter once; daily buckets are not additional tokens.
    active = [connection for connection in connections if connection["enabled"] and not connection.get("removing")] if enabled and allowed else []
    unresolved = sum(confirmed_identity(connection.get("identity")) is None for connection in active)
    grouped = [[connection["history"] for connection in group] for group in connection_groups(active)]
    reported = []
    for histories in grouped:
        available = [history for history in histories
                     if nonnegative(history["summary"].get("lifetime_tokens")) is not None]
        if available:
            reported.append(max(available, key=lambda history: history.get("last_success_at") or 0))
    timestamps = [history["last_success_at"] for history in reported if history.get("last_success_at") is not None]
    return {
        "total_tokens": sum(history["summary"]["lifetime_tokens"] for history in reported) if reported else None,
        "accounts": len(grouped), "reported_accounts": len(reported),
        # With unresolved connections this is a connection-counter sum, not a
        # verified distinct-account total: duplicates may remain in the sum.
        "identity_complete": unresolved == 0, "unresolved_connections": unresolved,
        "stale": any(history.get("stale", False) for history in reported),
        "refreshing": any(history.get("refreshing", False) for histories in grouped for history in histories),
        "last_success_at": min(timestamps) if timestamps else None,
    }
