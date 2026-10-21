"""Regressions for the independent public-release review."""
import threading

import pytest

from codex_insights import projection, queries
from codex_insights.dashboard_cache import DashboardCache
from codex_insights.ingestion import refresh
from codex_insights.storage import Store
from conftest import log, token


def seed(indexed):
    store, root, sid = indexed
    for n in range(2):
        (root / f'{n}.jsonl').write_bytes(log(str(n)) + token(100))
    refresh(store)
    return store, root, sid


def test_current_version_interrupted_stage_resumes_through_normal_refresh(indexed):
    from codex_insights.staged_projection import rebuild
    store, root, _ = seed(indexed)
    store.set_setting('timezone', 'Pacific/Auckland')
    stop = store.maintenance_cancel = threading.Event()
    def interrupt(value):
        if value['sessions'] == 1:
            stop.set()
    with pytest.raises(InterruptedError):
        rebuild(store, projection.project_segments, projection.PROJECTION_VERSION, interrupt)
    resumed = Store(store.directory)
    result = refresh(resumed)
    assert result['changed_files'] == 0
    assert queries.dashboard(resumed)['timeline'][0]['day'] == '2026-10-02'
    with resumed.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='rebuild_state'").fetchone()


def test_cache_advances_when_every_query_overlaps_a_write(indexed, monkeypatch):
    store, root, _ = seed(indexed)
    cache = DashboardCache(store)
    filters = {'_view': 'overview'}
    initial = cache.read(filters)
    real = queries.dashboard
    amounts = iter((300, 400, 500))
    def overlap(*args, **kwargs):
        value = real(*args, **kwargs)
        with (root / '0.jsonl').open('ab') as stream:
            stream.write(token(next(amounts), 10))
        refresh(store)
        return value
    try:
        with (root / '0.jsonl').open('ab') as stream:
            stream.write(token(200, 5))
        refresh(store)
        monkeypatch.setattr(queries, 'dashboard', overlap)
        for _ in range(3):
            completed = cache.read(filters)
            latest = next(iter(cache.latest.values()))
            assert latest['revision'] == completed['revision']
            assert latest['revision'] > initial['revision']
        monkeypatch.setattr(queries, 'dashboard', real)
        assert cache.read(filters)['summary'] == real(store, filters)['summary']
    finally:
        cache.close()


def test_cooperative_discovery_restores_reconnected_source(indexed):
    from codex_insights.cooperative import LiveMaintenance
    from codex_insights.live_index import LivePaths
    store, root, sid = seed(indexed)
    offline = root.with_name('disconnected')
    root.rename(offline)
    refresh(store)
    assert store.sources()[0]['status'] == 'Offline'
    offline.rename(root)
    store.live_paths = LivePaths()
    worker = LiveMaintenance(store)
    try:
        for _ in range(10):
            worker()
        assert store.sources()[0]['status'] == 'Ready'
        with store.connect() as db:
            before = db.execute('SELECT revision FROM coverage_state').fetchone()[0]
        worker()
        with store.connect() as db:
            assert db.execute('SELECT revision FROM coverage_state').fetchone()[0] == before
    finally:
        worker.close()
