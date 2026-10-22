"""Normal catch-up, overdue work and raw watcher hints have distinct lifetimes."""
from types import SimpleNamespace

import pytest

from codex_insights.ingestion import refresh
from codex_insights.live_index import LivePaths
from codex_insights.local_token_burn import LocalTokenBurn
from conftest import T, log, token


@pytest.mark.parametrize('origin,budget', [('watcher', 10), ('fallback', 35)])
def test_pending_age_survives_restart_and_expires_without_health_write(indexed, origin, budget):
    store, root, sid = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    store.live_paths = LivePaths()  # Object existence never implies a watcher.
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        db.execute('INSERT INTO index_pending VALUES(?,?)', (sid, str(path)))
        db.execute('UPDATE pending_progress SET oldest_pending_at=?', (now,))
        db.execute('INSERT INTO pending_origins VALUES(?,?,?)', (sid, str(path), origin))
    clock = [now + 1]
    reader = LocalTokenBurn(store, clock=lambda: clock[0])
    first = reader.read()
    assert first['coverage']['state'] == 'complete'
    assert first['coverage']['freshness']['state'] == 'updating'
    assert not first.get('partial')
    clock[0] += 1
    assert reader.read()['coverage']['freshness']['sources'][0]['pending_age_seconds'] == 2
    clock[0] = now + budget - 1
    assert reader.read()['coverage']['freshness']['state'] == 'updating'
    restarted = LocalTokenBurn(store, clock=lambda: clock[0]).read()
    assert restarted['coverage']['freshness']['sources'][0]['pending_age_seconds'] == budget - 1
    clock[0] += 1
    late = reader.read()
    assert late['coverage']['freshness']['state'] == 'delayed'
    assert late['partial']
    assert any(r['code'] == 'indexing_delayed' for r in late['coverage']['reasons'])


def test_raw_hint_and_unchanged_verification_never_claim_missing_usage(indexed):
    store, root, sid = indexed
    path = root / 'chat.jsonl'; path.write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        before = db.execute('SELECT last_progress_at FROM source_progress WHERE source_id=?', (sid,)).fetchone()[0]
    store.live_paths = LivePaths(cooldown=0)
    store.live_paths.begin_discovery()
    store.live_paths.event(sid, root, SimpleNamespace(src_path=str(path), event_type='modified', is_directory=False))
    rate = LocalTokenBurn(store, clock=lambda: now).read()
    assert rate['coverage']['state'] == 'complete' and rate['indexing']['live_pending_files'] == 0
    refresh(store, automatic=True)
    assert not store.live_paths.consumed
    with store.connect() as db:
        assert db.execute('SELECT last_progress_at FROM source_progress WHERE source_id=?', (sid,)).fetchone()[0] == before


@pytest.mark.parametrize('watchers,budget', [(False,35),(True,10)])
def test_projection_only_freshness_becomes_overdue_then_clears(indexed, watchers, budget):
    store, root, sid = indexed
    path = root / 'chat.jsonl'; path.write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        segment = db.execute('SELECT segment_id FROM canonical').fetchone()[0]
        db.execute('INSERT INTO projection_queue VALUES(?)', (segment,))
        db.execute('UPDATE projection_progress SET oldest_pending_at=?', (now,))
    store.live_paths = LivePaths()
    store.live_paths.watcher_available = watchers
    clock = [now + 1]
    reader = LocalTokenBurn(store, clock=lambda: clock[0])
    first = reader.read()
    assert first['coverage']['freshness']['state'] == 'updating'
    assert first['coverage']['freshness']['sources'][0]['pending_projections'] == 1
    assert first['coverage']['live_pending_projections'] == 1 and not first.get('partial')
    assert first['coverage']['freshness']['sources'][0]['overdue_seconds'] == budget
    clock[0] = now + budget
    assert reader.read()['coverage']['freshness']['sources'][0]['state'] == 'delayed'
    with store.connect() as db:
        db.execute('DELETE FROM projection_queue')
    final = reader.read()
    assert final['coverage']['freshness']['state'] == 'current'
    assert final['coverage']['live_pending_projections'] == 0


def test_projection_without_prior_usage_waits_instead_of_inventing_idle_zero(indexed):
    store, root, sid = indexed
    path = root / 'chat.jsonl'; path.write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        db.execute("DELETE FROM records WHERE kind='usage'")
        segment = db.execute('SELECT segment_id FROM canonical').fetchone()[0]
        db.execute('INSERT INTO projection_queue VALUES(?)', (segment,))
        db.execute('UPDATE projection_progress SET oldest_pending_at=?', (now,))
    value = LocalTokenBurn(store, clock=lambda: now + 1).read()
    assert value['status'] == 'collecting' and value['value'] is None
    assert value['coverage']['freshness']['state'] == 'updating'


def test_collecting_normal_pending_keeps_actual_parse_gap_partial(indexed):
    store, root, sid = indexed
    path = root / 'chat.jsonl'; path.write_bytes(log() + b'{invalid}\n')
    refresh(store)
    now = T.timestamp() + 600
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        db.execute('INSERT INTO index_pending VALUES(?,?)', (sid, str(path)))
        db.execute('UPDATE pending_progress SET oldest_pending_at=?', (now,))
    value = LocalTokenBurn(store, clock=lambda: now + 1).read()
    assert value['status'] == 'collecting' and value['value'] is None
    assert value['coverage']['freshness']['state'] == 'updating'
    assert value['partial'] and any(r['code'] == 'parse_gap' for r in value['coverage']['reasons'])
