"""Dollar throughput shares the token window and the indexed API cost evaluator."""
from datetime import datetime, timezone

import pytest

from codex_insights.ingestion import refresh
from codex_insights.local_token_burn import LocalTokenBurn
from codex_insights.projection import rebuild_projection
from conftest import T, event, log


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def scanned(store, at):
    with store.connect() as db:
        db.execute("UPDATE sources SET updated=?,status='Ready' WHERE kind='folder'", (stamp(at),))


@pytest.fixture
def local_cost(indexed):
    store, root, source = indexed
    clock = [T.timestamp() + 600]
    reader = LocalTokenBurn(store, clock=lambda: clock[0])

    def add(identifier, cost, total=1000, age=20, sid=None, kind="usage", priced=None):
        with store.connect() as db:
            db.execute("""INSERT OR REPLACE INTO records(event_id,source_id,kind,ts,total,cost,priced)
                VALUES(?,?,?,?,?,?,?)""", (identifier, sid or source, kind, stamp(clock[0] - age),
                                           total, cost, int(cost is not None) if priced is None else priced))
        store.set_setting("data_revision", store.setting("data_revision", 0) + 1)

    return reader, store, root, source, clock, add


def dollars(reader):
    return reader.read_rates()["cost_burn_rate"]


def test_cost_window_uses_same_scope_boundaries_and_idle_minutes_as_tokens(local_cost):
    reader, store, root, _, clock, add = local_cost
    disabled = store.add_source(root / "disabled")
    other = store.add_source(root / "claude", provider="claude_code")
    with store.connect() as db:
        db.execute("UPDATE sources SET enabled=0 WHERE id=?", (disabled,))
        db.execute("INSERT INTO sources(id,label,kind) VALUES('remote','Imported','snapshot')")
    add("cutoff", 50, age=300)
    add("first", .9, age=299)
    add("latest", .6, age=0)
    add("future", 50, age=-5)
    add("not-usage", 50, kind="activity")
    for sid in (disabled, other, "remote"):
        add(sid, 50, sid=sid)
    with store.connect() as db:
        db.execute("UPDATE records SET provider='claude_code' WHERE source_id=?", (other,))
    scanned(store, clock[0])
    result = reader.read_rates()
    assert result["token_burn_rate"]["value"] == 400
    assert result["cost_burn_rate"] == dict(value=.3, status="available", observed_seconds=300,
                                           updated_at=clock[0], total_tokens=2000, priced_tokens=2000)
    clock[0] += 300
    scanned(store, clock[0])
    # The previously future-dated event is now in range.
    assert dollars(reader)["value"] == 10
    clock[0] += 6
    scanned(store, clock[0])
    assert dollars(reader)["value"] == 0 and dollars(reader)["total_tokens"] == 0


def test_unpriced_usage_is_unavailable_or_a_labeled_subtotal_and_zero_price_is_valid(local_cost):
    reader, store, _, _, clock, add = local_cost
    scanned(store, clock[0])
    assert dollars(reader)["value"] == 0
    add("unknown", None, total=3000)
    result = dollars(reader)
    assert result["value"] is None and result["status"] == "unavailable" and result["partial"]
    assert result["priced_tokens"] == 0 and result["total_tokens"] == 3000
    add("known", 1, total=1000)
    result = dollars(reader)
    assert result["value"] == .2 and result["partial"] and result["priced_tokens"] == 1000
    assert result["total_tokens"] == 4000 and "partial" not in reader.read()
    # Missing cost or a false priced flag is not coverage, even with other populated fields.
    add("unknown", None, total=3000, priced=1)
    assert dollars(reader) == result
    add("unknown", 50, total=3000, priced=0)
    assert dollars(reader) == result
    add("unknown", 0, total=3000)
    assert "partial" not in dollars(reader) and dollars(reader)["priced_tokens"] == 4000


@pytest.mark.parametrize("input_tokens,tier,expected", [
    (100000, "standard", .291), (100000, "fast", .582),
    (300000, "standard", .846), (300000, "fast", 1.692),
])
def test_indexed_model_cache_write_reasoning_and_context_prices_are_reused(local_cost, input_tokens, tier, expected):
    reader, store, root, _, clock, _ = local_cost
    usage = dict(input_tokens=input_tokens, cached_input_tokens=input_tokens * 6 // 10,
                 cache_write_input_tokens=input_tokens // 10, output_tokens=20000,
                 reasoning_output_tokens=5000, total_tokens=input_tokens + 20000)
    content = log() + event("turn_context", {"model": "gpt-6.1-sol", "service_tier": tier}, 2)
    content += event("event_msg", {"type": "token_count", "info": {
        "total_token_usage": usage, "last_token_usage": usage}}, 580)
    (root / "chat.jsonl").write_bytes(content)
    (root / "copy.jsonl").write_bytes(content)
    refresh(store)
    scanned(store, clock[0])
    result = dollars(reader)
    assert result["value"] == pytest.approx(expected / 5)
    assert result["total_tokens"] == result["priced_tokens"] == input_tokens + 20000
    assert result["observed_seconds"] == 300 and "partial" not in result
    # Rebuilds and restarts do not create a new burst or change the window.
    rebuild_projection(store)
    assert dollars(LocalTokenBurn(store, clock=lambda: clock[0])) == result


def test_pricing_recalculation_updates_rate_without_new_token_usage(local_cost):
    reader, store, root, _, clock, _ = local_cost
    usage = dict(input_tokens=100000, cached_input_tokens=60000, output_tokens=20000,
                 reasoning_output_tokens=5000, total_tokens=120000)
    (root / "chat.jsonl").write_bytes(log() + event("turn_context", {"model": "gpt-6.1-sol"}, 2)
        + event("event_msg", {"type": "token_count", "info": {
            "total_token_usage": usage, "last_token_usage": usage}}, 580))
    refresh(store)
    scanned(store, clock[0])
    before = dollars(reader)
    assert before["value"] == pytest.approx(.286 / 5)
    store.set_setting("assumed_fast_percent", 50)
    rebuild_projection(store)
    assert dollars(reader)["value"] == pytest.approx(before["value"] * 1.5)
    assert dollars(reader)["priced_tokens"] == before["priced_tokens"]


def test_stale_partial_and_source_changes_apply_to_both_rates(local_cost):
    reader, store, _, source, clock, add = local_cost
    assert dollars(reader)["status"] == "collecting"
    scanned(store, clock[0])
    add("recent", .5)
    with store.connect() as db:
        db.execute("INSERT INTO file_failures(source_id,path) VALUES(?,'old.jsonl')", (source,))
    expected = dollars(reader)
    assert expected["value"] == .1 and expected["partial"]
    clock[0] += 601
    result = dollars(reader)
    assert result["value"] == expected["value"] and result["status"] == "stale"
    assert result["updated_at"] == expected["updated_at"]
    with store.connect() as db:
        db.execute("UPDATE sources SET enabled=0")
    assert dollars(reader)["value"] is None and dollars(reader)["status"] == "unavailable"
    assert dollars(LocalTokenBurn(store, allowed=False))["status"] == "unavailable"
