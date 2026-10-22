"""Completed snapshots remain useful during concurrent indexing."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from codex_insights import queries
from codex_insights.dashboard_cache import DashboardCache
from codex_insights.ingestion import refresh
from conftest import token
from test_review_regressions import seed


def append(store, root, amount):
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(token(amount, amount))
    refresh(store)


def test_background_queries_publish_progress_before_writers_stop(indexed, monkeypatch):
    store, root, _ = seed(indexed)
    # Publication order, not the recompute throttle, is under test here.
    cache = DashboardCache(store, min_interval=0)
    filters = {'_view': 'overview'}
    previous = cache.read(filters)
    real = queries.dashboard
    amount = [200]
    def query(*args):
        result = real(*args)
        amount[0] += 100
        append(store, root, amount[0])
        return result
    append(store, root, amount[0])
    monkeypatch.setattr(queries, 'dashboard', query)
    try:
        for _ in range(3):
            shown = cache.read({**filters, '_background': True})
            assert shown['analytics_refreshing']
            assert shown['revision'] == previous['revision']
            cache.executor.submit(lambda: None).result(timeout=5)
            previous = next(iter(cache.latest.values()))
            assert previous['revision'] > shown['revision']
            assert cache.snapshot.load({})['revision'] == previous['revision']
        monkeypatch.setattr(queries, 'dashboard', real)
        final = cache.read(filters)
        assert not final.get('analytics_refreshing')
        assert final['summary'] == real(store, filters)['summary']
    finally:
        cache.close()


def test_background_recompute_is_throttled_under_constant_churn(indexed, monkeypatch):
    store, root, _ = seed(indexed)
    clock = [100.0]
    cache = DashboardCache(store, min_interval=15, clock=lambda: clock[0])
    filters = {'_view': 'overview'}
    real = queries.dashboard
    calls = []
    def counted(*args):
        calls.append(1)
        return real(*args)
    monkeypatch.setattr(queries, 'dashboard', counted)
    try:
        first = cache.read(filters)
        generation = cache.generation
        append(store, root, 300)
        # Indexing just changed the identity, but a compute just finished.
        shown = cache.read({**filters, '_background': True})
        cache.executor.submit(lambda: None).result(timeout=5)
        assert shown['analytics_refreshing'] and shown['revision'] == first['revision']
        assert len(calls) == 1 and cache.generation == generation
        # A refresh the user asked for is not throttled.
        cache.read({**filters, '_background': True, '_retry': True})
        cache.executor.submit(lambda: None).result(timeout=5)
        assert len(calls) == 2 and cache.generation == generation + 1
        generation = cache.generation
        calls.clear()
        calls.append(1)
        append(store, root, 400)
        cache.read({**filters, '_background': True})
        cache.executor.submit(lambda: None).result(timeout=5)
        assert len(calls) == 1 and cache.generation == generation
        clock[0] += 15
        cache.read({**filters, '_background': True})
        cache.executor.submit(lambda: None).result(timeout=5)
        assert len(calls) == 2 and cache.generation == generation + 1
        latest = cache.read(filters)
        assert latest['revision'] > first['revision'] and not latest.get('analytics_refreshing')
        assert len(calls) == 2
    finally:
        cache.close()


def test_closing_interrupts_a_running_aggregate_without_reporting_it(indexed, monkeypatch):
    import time
    from codex_insights.storage import tracked
    store, root, _ = seed(indexed)
    cache = DashboardCache(store, min_interval=0)
    filters = {'_view': 'overview'}
    cache.read(filters)
    entered = threading.Event()
    def endless(store, filters=None):
        with store.connect() as db, tracked(store, db):
            entered.set()
            # Bounded so a regression fails the timing assertion instead of hanging the run.
            db.execute('WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<300000000) '
                       'SELECT count(*) FROM n').fetchone()
            db.execute('SELECT count(*) FROM records').fetchone()
    monkeypatch.setattr(queries, 'dashboard', endless)
    append(store, root, 300)
    cache.read({**filters, '_background': True})
    assert entered.wait(5)
    started = time.monotonic()
    cache.close(timeout=10)
    assert time.monotonic() - started < 5
    assert not cache.errors and not cache.pending


def test_older_concurrent_completion_cannot_replace_newer_snapshot(indexed, monkeypatch):
    store, root, _ = seed(indexed)
    cache = DashboardCache(store)
    filters = {'_view': 'overview'}
    real = queries.dashboard
    captured, release = threading.Event(), threading.Event()
    def query(*args):
        result = real(*args)
        if not captured.is_set():
            captured.set()
            assert release.wait(10)
        return result
    monkeypatch.setattr(queries, 'dashboard', query)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            older = pool.submit(cache.read, filters)
            assert captured.wait(3)
            append(store, root, 300)
            newer = cache.read(filters)
            release.set()
            assert older.result(timeout=5)['revision'] < newer['revision']
        assert next(iter(cache.latest.values()))['revision'] == newer['revision']
        assert cache.snapshot.load({})['revision'] == newer['revision']
    finally:
        release.set()
        cache.close()


@pytest.mark.parametrize('change', ['timezone', 'pricing', 'source'])
def test_incompatible_completion_never_populates_current_cache(indexed, monkeypatch, change):
    store, root, sid = seed(indexed)
    cache = DashboardCache(store)
    real = queries.dashboard
    def query(*args):
        result = real(*args)
        if change == 'timezone':
            store.set_setting('timezone', 'Pacific/Auckland')
        elif change == 'pricing':
            store.set_setting('assumed_fast_percent', 50)
        else:
            with store.connect() as db:
                db.execute('UPDATE sources SET enabled=0 WHERE id=?', (sid,))
        return result
    monkeypatch.setattr(queries, 'dashboard', query)
    try:
        cache.read({'_view': 'overview'})
        assert not cache.latest
        assert cache.snapshot.load({}) is None
    finally:
        cache.close()


def test_query_identity_matches_transaction_even_when_write_follows_capture(indexed, monkeypatch):
    from codex_insights import query_snapshot
    store, root, _ = seed(indexed)
    original = query_snapshot.identity
    changed = []
    def identity(db, filters, at=None):
        key = original(db, filters, at)
        if not changed:
            changed.append(True)
            append(store, root, 300)
        return key
    monkeypatch.setattr(query_snapshot, 'identity', identity)
    result = queries.dashboard(store)
    assert result['revision'] == result.snapshot_key[1]
    assert result['summary']['total_tokens'] == 220
    assert queries.dashboard(store)['summary']['total_tokens'] == 440


def test_completion_priority_bypasses_duration_cooldown(indexed):
    store, root, _ = seed(indexed)
    clock = [100.0]
    cache = DashboardCache(store, clock=lambda: clock[0])
    filters = {'_view': 'overview'}
    try:
        previous = cache.read(filters)
        view_key = next(iter(cache.finished))
        cache.durations[view_key] = 4  # Adaptive background cooldown is 8s.
        append(store, root, 300)
        assert cache.read({**filters, '_background': True})['revision'] == previous['revision']
        priority = cache.read({**filters, '_background': True, '_retry': True})
        assert priority['revision'] > previous['revision']
        assert not priority.get('analytics_refreshing')
    finally:
        cache.close()
