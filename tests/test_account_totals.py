from codex_insights.account_totals import account_token_total
from codex_insights.account_identity import AccountIdentity
from codex_insights.account_data import normalize_history
from codex_insights.service import Engine


def connection(identifier, tokens, *, identity=None, enabled=True, stale=False, updated=10):
    return {"id": identifier, "identity": AccountIdentity(identity, identity) if identity else None, "enabled": enabled, "history": {
        "summary": {"lifetime_tokens": tokens}, "daily": [{"day": "2026-10-08", "tokens": 999}],
        "last_success_at": updated, "stale": stale, "refreshing": False}}


def test_lifetime_sum_keeps_missing_zero_and_stale_distinct():
    total = account_token_total([connection("a", 123), connection("b", 0, stale=True),
                                 connection("c", None), connection("paused", 999, enabled=False)])
    assert total == {"total_tokens": 123, "accounts": 3, "reported_accounts": 2,
                     "identity_complete": False, "unresolved_connections": 3,
                     "stale": True, "refreshing": False, "last_success_at": 10}
    assert account_token_total([connection("a", 0)])["total_tokens"] == 0
    assert account_token_total([connection("a", None)])["total_tokens"] is None
    assert account_token_total([])["total_tokens"] is None


def test_duplicate_signins_count_the_freshest_available_counter_once():
    total = account_token_total([connection("current", 100, identity="same", stale=True),
                                connection("alias", 120, identity="same", updated=20),
                                connection("missing-alias", None, identity="same", updated=30),
                                connection("work", 80, identity="other")])
    assert total["total_tokens"] == 200
    assert total["accounts"] == total["reported_accounts"] == 2
    assert not total["stale"]
    assert total["last_success_at"] == 10


def test_disabled_or_disallowed_fetches_do_not_masquerade_as_zero():
    for switches in ({"enabled": False}, {"allowed": False}):
        total = account_token_total([connection("a", 123)], **switches)
        assert total["total_tokens"] is None and total["accounts"] == 0


def test_dashboard_exposes_api_total_without_replacing_analyzed_widget_data(tmp_path):
    engine = Engine(tmp_path, demo=True)
    try:
        # Seed the account cache directly: this integration check never connects.
        engine.accounts.allowed = engine.accounts.enabled = True
        history = engine.accounts.monitors["current"].history
        with history.lock:
            history.payload = normalize_history({"summary": {"lifetimeTokens": 987654321}})
            history.account = "synthetic"
            history.last_success = history.clock()
        dashboard = engine.call("dashboard")
        assert dashboard["account_token_total"]["total_tokens"] == 987654321
        assert engine.call("accounts")["token_total"] == dashboard["account_token_total"]
        widget = engine.call("widget_summary")
        assert widget["all_time"]["total_tokens"] == dashboard["summary"]["total_tokens"]
        assert widget["all_time"]["total_tokens"] != 987654321
        assert "identity" not in engine.call("accounts")["accounts"][0]
    finally:
        engine.close()
