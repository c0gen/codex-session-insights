"""Rebuild intent survives failures without mixing accepted preferences."""
import threading
import json
from copy import deepcopy

import pytest

from codex_insights import projection, projection_state, staged_projection
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from conftest import token
from test_review_regressions import seed


@pytest.mark.parametrize('point', ['prepare', 'midway', 'publish'])
def test_configuration_and_live_updates_survive_restart(indexed, monkeypatch, point):
    store, root, _ = seed(indexed)
    before = dashboard(store)
    with store.connect() as db:
        projection_state.request(db, {'timezone': 'Pacific/Auckland', 'assumed_fast_percent': 50})
    injected = []
    def cooperate():
        assert store.setting('timezone') == 'America/New_York'
        assert dashboard(store)['timezone'] == 'America/New_York'
        if not injected:
            injected.append(True)
            with (root / '0.jsonl').open('ab') as stream:
                stream.write(token(300, 5))
            refresh(store)  # Must not recursively start the active rebuild.
    store.cooperate = cooperate
    stop = store.maintenance_cancel = threading.Event()
    def progress(value):
        if point == 'midway' and value['sessions'] == 1:
            stop.set()
    def fail(*args):
        raise RuntimeError('simulated process interruption')
    with monkeypatch.context() as patch:
        if point != 'midway':
            patch.setattr(staged_projection, point, fail)
        with pytest.raises((RuntimeError, InterruptedError)):
            projection.ensure_projection(store, progress)
    assert store.setting('timezone') == 'America/New_York'
    assert projection_state.needs_rebuild(store, projection.PROJECTION_VERSION)
    resumed = Store(store.directory)
    assert refresh(resumed)['changed_files'] == 0
    result = dashboard(resumed)
    assert result['timezone'] == 'Pacific/Auckland'
    assert result['timeline'][0]['day'] == '2026-10-02'
    assert result['summary']['total_tokens'] == (440 if injected else 220)
    assert result['revision'] > before['revision']
    with resumed.connect() as db:
        assert not projection_state.status(db)['pending']
    assert not projection.ensure_projection(resumed)


def test_resume_reuses_completed_sessions_and_restarts_incompatible_configuration(indexed):
    store, _, _ = seed(indexed)
    with store.connect() as db:
        projection_state.request(db, {'timezone': 'Pacific/Auckland'})
    store.cooperate = lambda: None
    stop = store.maintenance_cancel = threading.Event()
    def interrupt(value):
        if value['sessions'] == 1:
            stop.set()
    with pytest.raises(InterruptedError):
        projection.ensure_projection(store, interrupt)
    with store.connect() as db:
        completed = db.execute('SELECT count(*) FROM rebuild_work WHERE phase=2').fetchone()[0]
        staged_projection.prepare(db, projection.PROJECTION_VERSION)
        assert db.execute('SELECT count(*) FROM rebuild_work WHERE phase=2').fetchone()[0] == completed == 1
        projection_state.request(db, {'timezone': 'UTC'})
        staged_projection.prepare(db, projection.PROJECTION_VERSION)
        assert db.execute('SELECT count(*) FROM rebuild_work WHERE phase=2').fetchone()[0] == 0
    assert projection.ensure_projection(Store(store.directory))
    assert dashboard(store)['timezone'] == 'UTC'


def test_pending_catalog_is_used_only_by_shadow_projection(indexed, monkeypatch):
    from codex_insights.accounting import pricing
    from codex_insights.pricing_catalog import catalog
    monkeypatch.setattr(pricing, 'MODEL_RATE_RECORDS', deepcopy(pricing.MODEL_RATE_RECORDS))
    store, root, _ = seed(indexed)
    previous = dashboard(store)['summary']['cost']
    value = json.loads(json.dumps(catalog()))
    for record in value['models']['gpt-5.3-codex']:
        for key in ('input', 'cached_input', 'output'):
            record['rates'][key] *= 2
    with store.connect() as db:
        projection_state.request(db, {'pricing_catalog': value})
    store.cooperate = lambda: None
    stop = store.maintenance_cancel = threading.Event()
    def interrupt(value):
        if value['sessions'] == 1:
            stop.set()
    with pytest.raises(InterruptedError):
        projection.ensure_projection(store, interrupt)
    assert store.setting('pricing_catalog') is None
    assert dashboard(store)['summary']['cost'] == previous
    projection.ensure_projection(Store(store.directory))
    assert dashboard(store)['summary']['cost'] == pytest.approx(previous * 2)
    assert store.setting('pricing_catalog') == value


def test_legacy_stage_is_not_presented_as_verified_configuration(indexed):
    from codex_insights.dashboard_cache import OverviewSnapshot
    store, _, _ = seed(indexed)
    with store.connect() as db:
        staged_projection.prepare(db, projection.PROJECTION_VERSION)
    with store.connect() as db:
        assert projection_state.status(db) == {'pending': True, 'readable': False}
    with pytest.raises(ValueError, match='Waiting for the accepted configuration'):
        dashboard(store)
    assert OverviewSnapshot(store.directory).load({}) is None
    assert projection.ensure_projection(Store(store.directory))
    assert dashboard(store)['summary']['total_tokens'] == 220


def test_deferred_start_resumes_current_version_request(indexed, monkeypatch):
    from codex_insights.service import Engine
    from test_projection_upgrade import NoLiveProvider
    store, _, _ = seed(indexed)
    store.set_setting('live_usage_enabled', False)
    with store.connect() as db:
        projection_state.request(db, {'timezone': 'Pacific/Auckland'})
    engine = Engine(store.directory, allowance_provider=NoLiveProvider(), defer_projection=True)
    monkeypatch.setattr(engine, 'configure_watchers', lambda: None)
    try:
        assert engine.call('bootstrap')['projection'] == {'pending': True, 'readable': True}
        engine.start()
        engine.executor.submit(lambda: None).result(timeout=15)
        assert engine.call('dashboard')['timezone'] == 'Pacific/Auckland'
        assert not engine.call('live_status')['projection']['pending']
    finally:
        engine.close()


@pytest.mark.parametrize('remove', [False, True])
def test_source_mutation_and_rebuild_intent_commit_together(indexed, monkeypatch, remove):
    from codex_insights import service
    from test_projection_upgrade import NoLiveProvider
    store, _, sid = seed(indexed)
    store.set_setting('live_usage_enabled', False)
    engine = service.Engine(store.directory, allowance_provider=NoLiveProvider())
    def fail(*args):
        raise RuntimeError('crash before stage')
    monkeypatch.setattr(service, 'rebuild_projection', fail)
    try:
        engine.call('forget_source' if remove else 'source_enabled', {'id': sid, 'enabled': False})
        engine.executor.submit(lambda: None).result(timeout=10)
        assert engine.jobs.snapshot()['error'] == 'crash before stage'
        assert projection_state.needs_rebuild(store, projection.PROJECTION_VERSION)
    finally:
        engine.close()
    projection.ensure_projection(Store(store.directory))
    assert dashboard(store)['summary']['total_tokens'] == 0
