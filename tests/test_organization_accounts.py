"""Shared-workspace quota regressions through the real provider and account snapshot."""
from contextlib import contextmanager
import json
import time

import pytest

from codex_insights.accounts import Accounts
from codex_insights.codex_account import AppServerProvider


PLAN = "self_serve_business_prolite"
WORKSPACE = "private-shared-organization"


class OrganizationProvider(AppServerProvider):
    def __init__(self, member, missing_email=False):
        super().__init__()
        self.member = member
        self.account = {"type": "chatgpt", "planType": PLAN,
                        "email": None if missing_email else f"private-member-{member}@example.test"}

    @contextmanager
    def session(self):
        with self.operation:
            yield self

    def request(self, method, params=None):
        if method == "account/read":
            return {"account": self.account}
        if method == "account/rateLimits/read":
            return {"accountId": WORKSPACE, "rateLimits": {"planType": PLAN,
                    "primary": {"usedPercent": self.member * 5, "windowDurationMins": 300},
                    "secondary": {"usedPercent": self.member * 3, "windowDurationMins": 10080}}}
        if method == "account/usage/read":
            return {"summary": {"lifetimeTokens": self.member * 1000}}
        raise AssertionError(method)


@contextmanager
def organization_accounts(tmp_path, members, *, missing_email=False, duplicate=False):
    providers = {"current" if i == 0 else f"{i:032x}": OrganizationProvider(i + 1, missing_email)
                 for i in range(members)}
    if duplicate:
        providers[f"{members:032x}"] = OrganizationProvider(1, missing_email)
    entries = [{"id": identifier, "label": "Shared organization", "enabled": True}
               for identifier in providers]
    (tmp_path / "account-connections.json").write_text(json.dumps(entries), encoding="utf-8")
    accounts = Accounts(tmp_path, provider_factory=lambda home=None: providers[home.name if home else "current"])
    try:
        # Exercise both RPC paths and cache normalization without starting workers.
        for monitor in accounts.monitors.values():
            for cache in (monitor.limits, monitor.history):
                cache.payload = cache.normalize(cache.fetch(monitor.changed))
                cache.last_success = time.time()
        yield accounts
    finally:
        accounts.close()


@pytest.mark.parametrize("members", [2, 4, 12])
@pytest.mark.parametrize("missing_email", [False, True])
def test_business_members_share_organization_but_keep_independent_quotas(tmp_path, members, missing_email):
    with organization_accounts(tmp_path, members, missing_email=missing_email) as accounts:
        result = accounts.read()
        rows = result["accounts"]
        assert len(rows) == members
        assert [row["display_id"] for row in rows] == [row["id"] for row in rows]
        for member, row in enumerate(rows, 1):
            assert row["plan"] == PLAN
            windows = row["allowance"]["buckets"][0]["windows"]
            assert [window["remaining_percent"] for window in windows] == [100 - member * 5, 100 - member * 3]
            assert row["history"]["summary"]["lifetime_tokens"] == member * 1000
        total = result["token_total"]
        assert total["accounts"] == total["reported_accounts"] == members
        assert total["total_tokens"] == sum(range(1, members + 1)) * 1000
        assert total["identity_complete"] is (not missing_email)
        assert total["unresolved_connections"] == (members if missing_email else 0)
        serialized = json.dumps(result)
        assert WORKSPACE not in serialized
        assert "private-member-" not in serialized


@pytest.mark.parametrize("members", [2, 4, 12])
def test_duplicate_signin_merges_only_the_same_organization_member(tmp_path, members):
    with organization_accounts(tmp_path, members, duplicate=True) as accounts:
        result = accounts.read()
        rows = result["accounts"]
        assert len({row["display_id"] for row in rows}) == members
        assert rows[0]["display_id"] == rows[-1]["display_id"] == "current"
        assert all(row["display_id"] == row["id"] for row in rows[1:-1])
        assert result["token_total"]["total_tokens"] == sum(range(1, members + 1)) * 1000
        accounts.entries["current"]["enabled"] = False
        paused = accounts.read()["accounts"]
        assert paused[0]["display_id"] == paused[-1]["id"]
        assert all(row["display_id"] == row["id"] for row in paused[1:])
