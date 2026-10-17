"""Identity certainty regressions using only synthetic in-memory RPC sessions."""
from contextlib import contextmanager

import pytest

from codex_insights.account_totals import account_token_total
from codex_insights.account_identity import AccountIdentity
from codex_insights.account_monitor import AccountMonitor
from codex_insights.accounts import Accounts
from codex_insights.codex_account import AppServerProvider, AllowanceError


class FakeProvider(AppServerProvider):
    def __init__(self, tokens=1000, account_id=None, email="member@example.test"):
        super().__init__()
        self.account = {"type": "chatgpt", "email": email, "planType": "pro"}
        self.stable_id = account_id
        self.tokens = tokens
        self.fail_allowance = False
        self.calls = []

    @contextmanager
    def session(self):
        with self.operation:
            yield self

    def request(self, method, params=None):
        self.calls.append(method)
        if method == "account/read":
            return {"account": self.account}
        if method == "account/rateLimits/read":
            if self.fail_allowance:
                raise AllowanceError("connection", "Synthetic allowance failure")
            return {"accountId": self.stable_id, "rateLimits": {}}
        if method == "account/usage/read":
            return {"summary": {"lifetimeTokens": self.tokens}}
        raise AssertionError(method)


def snapshot(provider, identifier, updated=10):
    identities = []
    payload = provider.fetch_history(identities.append)
    return {"id": identifier, "enabled": True, "identity": identities[-1], "history": {
        "summary": {"lifetime_tokens": payload["summary"]["lifetimeTokens"]},
        "last_success_at": updated, "stale": False, "refreshing": False}}


def test_anonymous_connections_are_retained_and_not_claimed_as_distinct_accounts():
    total = account_token_total([snapshot(FakeProvider(1000, email=None), "a"),
                                 snapshot(FakeProvider(2000, email=None), "b")])
    assert total["total_tokens"] == 3000
    assert total["identity_complete"] is False
    assert total["unresolved_connections"] == 2


def test_partial_identity_resolution_does_not_claim_complete_double_count():
    first, second = FakeProvider(account_id="same"), FakeProvider(account_id="same")
    first.fetch(lambda _: None)
    second.fail_allowance = True
    with pytest.raises(AllowanceError):
        second.fetch(lambda _: None)
    total = account_token_total([snapshot(first, "a"), snapshot(second, "b")])
    assert total["total_tokens"] == 2000
    assert total["identity_complete"] is False
    assert total["unresolved_connections"] == 1
    assert "account/usage/read" in second.calls
    second.fail_allowance = False
    resolved = account_token_total([snapshot(first, "a"), snapshot(second, "b")])
    assert resolved["total_tokens"] == 1000
    assert resolved["identity_complete"] is True


def test_same_email_different_workspaces_and_same_member_different_plans():
    first = FakeProvider(account_id="workspace-one", email="same@example.test")
    second = FakeProvider(account_id="workspace-two", email="same@example.test")
    assert account_token_total([snapshot(first, "a"), snapshot(second, "b")])["total_tokens"] == 2000
    second.stable_id = "workspace-one"
    second.account["planType"] = "plus"
    second.tokens = 1500
    total = account_token_total([snapshot(first, "a"), snapshot(second, "b", updated=20)])
    assert total["total_tokens"] == 1500
    assert total["accounts"] == total["reported_accounts"] == 1


@pytest.mark.parametrize("email", [None, "", "   ", 17])
def test_workspace_without_member_identity_cannot_hide_another_connection(email):
    first = FakeProvider(account_id="shared-workspace")
    second = FakeProvider(account_id="shared-workspace", email=email)
    total = account_token_total([snapshot(first, "a"), snapshot(second, "b")])
    assert total["total_tokens"] == 2000
    assert total["accounts"] == 2
    assert not total["identity_complete"]
    assert total["unresolved_connections"] == 1
    second.account["email"] = first.account["email"]
    resolved = account_token_total([snapshot(first, "a"), snapshot(second, "b")])
    assert resolved["total_tokens"] == 1000
    assert resolved["identity_complete"]


def test_stale_stable_id_is_detached_on_endpoint_failure_and_workspace_switch():
    provider = FakeProvider(account_id="old-workspace")
    old = snapshot(provider, "a")
    provider.stable_id = "new-workspace"
    provider.fail_allowance = True
    unknown = snapshot(provider, "a")
    assert unknown["identity"] != old["identity"]
    assert not account_token_total([unknown])["identity_complete"]
    provider.fail_allowance = False
    new = snapshot(provider, "a")
    assert new["identity"] != old["identity"]
    assert account_token_total([new])["identity_complete"]


def test_zero_missing_disabled_removing_and_freshest_stale():
    first, second = FakeProvider(0, "same"), FakeProvider(12, "same")
    zero, stale = snapshot(first, "a", 20), snapshot(second, "b", 10)
    stale["history"]["stale"] = True
    disabled = snapshot(FakeProvider(999), "disabled")
    disabled["enabled"] = False
    removing = snapshot(FakeProvider(999), "removing")
    removing["removing"] = True
    total = account_token_total([zero, stale, disabled, removing])
    assert total["total_tokens"] == 0 and not total["stale"]
    assert total["identity_complete"]
    zero["history"]["summary"]["lifetime_tokens"] = None
    assert account_token_total([zero, stale])["total_tokens"] == 12


@pytest.mark.parametrize("stable_id", [None, "", "   "])
def test_missing_or_blank_stable_ids_never_prove_identity(stable_id):
    total = account_token_total([snapshot(FakeProvider(account_id=stable_id), "a")])
    assert total["unresolved_connections"] == 1
    assert not total["identity_complete"]


def test_legacy_lifecycle_string_is_not_deduplication_evidence():
    first, second = snapshot(FakeProvider(), "a"), snapshot(FakeProvider(), "b")
    first["identity"] = second["identity"] = "same-lifecycle-hash"
    total = account_token_total([first, second])
    assert total["total_tokens"] == 2000 and not total["identity_complete"]


def test_plan_change_preserves_cache_but_workspace_and_signin_change_clear_it():
    provider = FakeProvider(account_id="workspace-one", email="a@example.test")
    monitor = AccountMonitor(provider)
    try:
        provider.fetch_history(monitor.changed)
        monitor.history.payload["summary"]["lifetime_tokens"] = 1000
        monitor.history.last_success = 10
        provider.account["planType"] = "plus"
        provider.fetch_history(monitor.changed)
        assert monitor.history.payload["summary"]["lifetime_tokens"] == 1000
        provider.stable_id = "workspace-two"
        provider.fetch_history(monitor.changed)
        assert monitor.history.payload["summary"]["lifetime_tokens"] is None
        monitor.history.payload["summary"]["lifetime_tokens"] = 2000
        provider.account["email"] = "b@example.test"
        provider.fail_allowance = True
        provider.fetch_history(monitor.changed)
        assert monitor.history.payload["summary"]["lifetime_tokens"] is None
        assert monitor.history.account.confirmed is None
        assert provider.account_id is None
    finally:
        monitor.close()


def test_private_identity_proof_does_not_reach_account_snapshot(tmp_path):
    import json
    provider = FakeProvider(account_id="private-workspace", email="private@example.test")
    accounts = Accounts(tmp_path, current_provider=provider)
    try:
        monitor = accounts.monitors["current"]
        provider.fetch_history(monitor.changed)
        assert isinstance(monitor.history.account, AccountIdentity)
        serialized = json.dumps(accounts.read())
        assert "private-workspace" not in serialized and "private@example.test" not in serialized
        assert monitor.history.account not in serialized
        assert monitor.history.account.confirmed not in serialized
    finally:
        accounts.close()
