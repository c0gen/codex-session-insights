"""Group connections only when the provider has confirmed account identity."""
from .account_identity import confirmed_identity


def connection_groups(connections):
    grouped = {}
    for connection in connections:
        identity = confirmed_identity(connection.get("identity"))
        key = ("account", identity) if identity else ("connection", connection["id"])
        grouped.setdefault(key, []).append(connection)
    return list(grouped.values())


def display_ids(connections):
    result = {}
    for group in connection_groups(connections):
        representative = min(group, key=lambda entry: (
            bool(entry.get("removing")), not entry["enabled"], entry["id"] != "current"))
        result.update((entry["id"], representative["id"]) for entry in group)
    return result
