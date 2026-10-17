import json

from codex_insights.account_groups import connection_groups, display_ids
from codex_insights.account_identity import AccountIdentity
from codex_insights.accounts import Accounts


def connection(identifier, identity=None, enabled=True, **extra):
    return {"id": identifier, "enabled": enabled,
            "identity": AccountIdentity("life-" + identifier, identity), **extra}


def test_confirmed_groups_prefer_current_then_enabled_and_keep_registry_order():
    connections = [connection("saved", "same"), connection("work", "other"),
                   connection("current", "same"), connection("saved-again", "same")]
    assert [[entry["id"] for entry in group] for group in connection_groups(connections)] == [
        ["saved", "current", "saved-again"], ["work"]]
    assert display_ids(connections) == {"saved": "current", "current": "current", "saved-again": "current", "work": "work"}
    connections[2]["enabled"] = False
    assert display_ids(connections)["current"] == "saved"
    connections[0]["removing"] = True
    assert display_ids(connections)["current"] == "saved-again"
    connections[0]["removing"] = False
    connections[0]["enabled"] = connections[3]["enabled"] = False
    assert display_ids(connections)["saved"] == "current"


def test_unconfirmed_identity_and_matching_metadata_never_hide_connections():
    connections = [connection("current", label="same", email="same@example.test"),
                   connection("saved", label="same", email="same@example.test"),
                   connection("workspace-one", "one", email="same@example.test"),
                   connection("workspace-two", "two", email="same@example.test")]
    connections[0]["identity"] = connections[1]["identity"] = "same-legacy-marker"
    assert display_ids(connections) == {entry["id"]: entry["id"] for entry in connections}


class UnusedProvider:
    def fetch(self, changed):
        raise AssertionError("No real account reads in these tests")

    def close(self):
        pass


def test_account_snapshot_switch_and_identity_loss_preserve_connections_and_privacy(tmp_path):
    saved = "a" * 32
    entries = [{"id": "current", "label": "Current Codex", "enabled": True},
               {"id": saved, "label": "Saved", "enabled": True}]
    registry = tmp_path / "account-connections.json"
    registry.write_text(json.dumps(entries), encoding="utf-8")
    accounts = Accounts(tmp_path, provider_factory=lambda **_: UnusedProvider())
    try:
        for identifier, monitor in accounts.monitors.items():
            monitor.history.account = AccountIdentity("private-life-" + identifier, "private-proof")
        assert [entry["display_id"] for entry in accounts.read()["accounts"]] == ["current", "current"]
        serialized = json.dumps(accounts.read())
        assert "private-proof" not in serialized and "private-life" not in serialized
        accounts.entries["current"]["enabled"] = False
        assert [entry["display_id"] for entry in accounts.read()["accounts"]] == [saved, saved]
        accounts.entries["current"]["enabled"] = True
        accounts.monitors["current"].history.account = AccountIdentity("switched", "other-proof")
        assert [entry["display_id"] for entry in accounts.read()["accounts"]] == ["current", saved]
        accounts.monitors["current"].history.account = None
        assert [entry["display_id"] for entry in accounts.read()["accounts"]] == ["current", saved]
        assert json.loads(registry.read_text(encoding="utf-8")) == entries
    finally:
        accounts.close()
