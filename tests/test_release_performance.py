"""User-visible contracts for cached startup, scoped work and atomic rebuilds."""
import json
import threading
import sqlite3
from contextlib import contextmanager

import pytest

from codex_insights.dashboard_cache import DashboardCache, OverviewSnapshot
from codex_insights.deferred_engine import DeferredEngine
from codex_insights.ingestion import refresh
from codex_insights.local_token_burn import LocalTokenBurn
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.staged_projection import rebuild
from codex_insights.storage import Store
from conftest import T, log, token


def seed(indexed, count=3):
    store, root, _ = indexed
    for i in range(count):
        (root / f'{i}.jsonl').write_bytes(log(f'chat-{i}') + token(100, 590))
    refresh(store)
    return store, root


def test_overview_defers_detail_and_cache_returns_independent_values(indexed, monkeypatch):
    store, _ = seed(indexed)
    cache = DashboardCache(store)
    full = dashboard(store)
    value = cache.read({'_view': 'overview'})
    assert value['summary'] == full['summary']
    assert value['timeline'] == full['timeline']
    assert value['projects'] == value['models'] == value['daily_sessions'] == []
    monkeypatch.setattr('codex_insights.queries.dashboard', lambda *args: pytest.fail('cache should avoid analytics query'))
    value['summary']['total_tokens'] = -1
    assert cache.read({'_view': 'overview'})['summary'] == full['summary']


def test_cache_invalidation_and_startup_privacy(indexed):
    store, root = seed(indexed)
    cache = DashboardCache(store)
    value = cache.read({'_view': 'overview'})
    boot = OverviewSnapshot(store.directory)
    assert boot.load({})['cached_at'] == value['generated_at']
    saved = json.loads(boot.path.read_text())['data']
    assert not {'accounts', 'usage_limits', 'account_token_total', 'provider_setup'} & saved.keys()
    assert all(source['root'] is None and not source['detail'] for source in saved['sources'])
    assert boot.load({'range': 'today'}) is None
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(token(300, 595))
    refresh(store)
    assert cache.read({'_view': 'overview'})['summary']['total_tokens'] > value['summary']['total_tokens']
    store.set_setting('assumed_fast_percent', 30)
    assert boot.load({}) is None


def test_active_view_refresh_returns_previous_results_without_waiting(indexed, monkeypatch):
    from codex_insights import queries
    store, root = seed(indexed)
    cache = DashboardCache(store)
    original = cache.read({'_view': 'overview'})
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(token(500, 595))
    refresh(store)
    entered, release = threading.Event(), threading.Event()
    real_query = queries.dashboard
    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return real_query(*args)
    monkeypatch.setattr(queries, 'dashboard', blocked)
    try:
        result = cache.read({'_view': 'overview', '_background': True})
        assert result['analytics_refreshing'] and result['summary'] == original['summary']
        assert entered.wait(1)
        release.set()
        cache.close()
        updated = cache.read({'_view': 'overview'})
        assert updated['revision'] > result['revision']
        assert updated['summary']['total_tokens'] > result['summary']['total_tokens']
    finally:
        release.set()


def test_rebuild_keeps_accepted_rows_until_publish_and_catches_live_changes(indexed):
    store, root = seed(indexed)
    original = dashboard(store)['summary']['total_tokens']
    from codex_insights.projection import project_segments, PROJECTION_VERSION
    visits, injected = [], []
    def cooperate():
        visits.append(dashboard(store)['summary']['total_tokens'])
        if len(visits) == 5:
            with (root / '0.jsonl').open('ab') as stream:
                stream.write(token(400, 595))
            refresh(store)
            injected.append(dashboard(store)['summary']['total_tokens'])
    store.cooperate = cooperate
    rebuild(store, project_segments, PROJECTION_VERSION)
    assert visits[:4] == [original] * 4
    assert injected and dashboard(store)['summary']['total_tokens'] == injected[0]
    # Source inclusion is recomputed against the staged selection too.
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0')
    store.cooperate = lambda: None
    rebuild_projection(store)
    assert dashboard(store)['summary']['total_tokens'] == 0


def test_cancelled_rebuild_resumes_and_failure_preserves_accepted_generation(indexed):
    store, _ = seed(indexed, 5)
    from codex_insights.projection import project_segments, PROJECTION_VERSION
    before = dashboard(store)
    cancel = store.maintenance_cancel = threading.Event()
    store.cooperate = lambda: None
    def cancel_after_first(value):
        if value['sessions'] == 1:
            cancel.set()
    with pytest.raises(InterruptedError):
        rebuild(store, project_segments, PROJECTION_VERSION, cancel_after_first)
    assert dashboard(store)['summary'] == before['summary']
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM rebuild_work WHERE phase=2').fetchone()[0] == 1
    cancel.clear()
    def fail(*args):
        raise RuntimeError('projection failed')
    with pytest.raises(RuntimeError):
        rebuild(store, fail, PROJECTION_VERSION)
    assert dashboard(store)['summary'] == before['summary']
    resumed = Store(store.directory)
    resumed.cooperate = lambda: None
    rebuild(resumed, project_segments, PROJECTION_VERSION)
    assert dashboard(resumed)['summary'] == before['summary']


def test_shell_bootstrap_does_not_wait_for_store_initialization(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class SlowEngine:
        def __init__(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)
        def start(self): pass
        def close(self): pass
        def call(self, action, args): return {'ok': True}
    engine = DeferredEngine(tmp_path, factory=SlowEngine)
    try:
        boot = engine.call('bootstrap')
        assert entered.wait(1)
        assert boot['ready'] is False and boot['cached_overview'] is None
        assert engine.call('live_status') == {'ready': False}
        release.set()
        assert engine.ready.wait(2)
        assert engine.call('dashboard') == {'ok': True}
    finally:
        release.set()
        engine.close()


def test_demo_maintenance_does_not_discover_placeholder_source_paths(tmp_path):
    from codex_insights.service import Engine
    engine = Engine(tmp_path / 'demo', demo=True, defer_projection=True)
    try:
        engine.start()
        engine.executor.submit(lambda: None).result(timeout=10)
        from codex_insights.cooperative import live_work
        with live_work(engine.store) as work:
            work()
        assert engine.call('status')['error'] is None
        assert engine.call('widget_summary')['all_time']['total_tokens'] > 0
    finally:
        engine.close()


def test_verified_old_pending_file_does_not_hide_live_freshness(indexed):
    store, root = seed(indexed, 1)
    from codex_insights.index_scan import Scan
    from codex_insights.burn_coverage import evaluate
    now = T.timestamp() + 1000
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
    report = dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0)
    scan = Scan(store, store.sources(), report)
    scan.enqueue(indexed[2], root / '0.jsonl')
    rate = LocalTokenBurn(store, clock=lambda: now).read()
    assert rate['coverage']['state'] == 'complete'
    assert rate['indexing']['historical_pending_files'] == 1
    # The same path after an append loses its old evidence, even with old mtime.
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(token(500, 999))
    scan.enqueue(indexed[2], root / '0.jsonl', urgent=True)
    partial = LocalTokenBurn(store, clock=lambda: now).read()
    assert partial['partial']
    assert partial['indexing']['live_pending_files'] == 1


def test_periodic_inventory_does_not_restart_completed_historical_rebuild_work(indexed):
    from codex_insights.index_scan import Scan
    store, root = seed(indexed, 2)
    report = dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0)
    scan = Scan(store, store.sources(), report, rebuild=True)
    try:
        scan.inventory()
        while scan.tasks:
            scan.step()
        assert report['changed_files'] == 2
        scan.inventory()
        assert not scan.tasks
        with (root / '0.jsonl').open('ab') as stream:
            stream.write(token(400, 595))
        scan.inventory()
        while scan.tasks:
            scan.step()
        assert report['changed_files'] == 3
    finally:
        scan.close()


def test_live_append_is_serviced_between_discovery_queue_batches(indexed, monkeypatch):
    from codex_insights.index_scan import Scan
    from codex_insights.live_index import LivePaths
    store, root = seed(indexed, 66)
    store.live_paths = LivePaths()
    report = dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0)
    scan = Scan(store, store.sources(), report, rebuild=True)
    enqueue = scan._enqueue
    queued = []
    def inject(db, sid, path, urgent=False):
        enqueue(db, sid, path, urgent)
        queued.append(path)
        if len(queued) == 64:
            with (root / '0.jsonl').open('ab') as stream:
                stream.write(token(500, 595))
            store.live_paths.requeue([(indexed[2], str(root / '0.jsonl'))])
        elif len(queued) == 66:
            assert db.execute("SELECT sum(total) FROM records WHERE session_id='chat-0'").fetchone()[0] == 550
    monkeypatch.setattr(scan, '_enqueue', inject)
    try:
        scan.inventory()
        assert len(queued) >= 66
    finally:
        scan.close()


def test_idle_rate_polling_reuses_coverage_but_expires_time_evidence(indexed, monkeypatch):
    store, _ = seed(indexed, 1)
    now = [T.timestamp() + 600]
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now[0], now[0]))
    reader = LocalTokenBurn(store, clock=lambda: now[0])
    assert reader.read()['coverage']['state'] == 'complete'
    from codex_insights import local_token_burn
    original = local_token_burn.evaluate
    monkeypatch.setattr(local_token_burn, 'evaluate', lambda *args: pytest.fail('idle polling must reuse coverage'))
    for seconds in (2, 5, 10):
        now[0] = T.timestamp() + 600 + seconds
        reader.read()
    monkeypatch.setattr(local_token_burn, 'evaluate', original)
    now[0] += 60
    assert reader.read()['partial']


def test_interactive_reads_never_load_history_facts_or_parser_checkpoints(indexed, monkeypatch):
    store, _ = seed(indexed, 2)
    connect = store.connect
    forbidden = []
    def authorize(action, table, column, *_):
        if action == sqlite3.SQLITE_READ and column in {'fact', 'state'} and table in {'canonical', 'candidates', 'files', 'history_variants'}:
            forbidden.append((table, column))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    @contextmanager
    def guarded():
        with connect() as db:
            db.set_authorizer(authorize)
            yield db
    monkeypatch.setattr(store, 'connect', guarded)
    cache = DashboardCache(store)
    reader = LocalTokenBurn(store)
    try:
        for _ in range(3):
            cache.read({'_view': 'overview'})
            reader.read_rates()
        assert not forbidden
    finally:
        cache.close()


def test_waiting_rates_still_report_current_live_progress(indexed):
    store, root = seed(indexed, 1)
    now = T.timestamp() + 2000
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now - 70, now - 70))
        db.execute('INSERT INTO index_pending VALUES(?,?)', (indexed[2], str(root / 'unknown.jsonl')))
    rate = LocalTokenBurn(store, clock=lambda: now).read()
    assert rate['value'] is None and rate['status'] == 'collecting'
    assert rate['indexing'] == {'live_checked_at': now - 70, 'live_pending_files': 1, 'historical_pending_files': 0}


def test_removed_response_owner_reprojects_only_its_former_competitors(indexed):
    from codex_insights.projection import project_segments
    from test_providers import line
    store, _ = seed(indexed, 1)
    for name in ('a', 'b'):
        directory = store.directory.parent / ('claude-' + name)
        directory.mkdir()
        store.add_source(directory, provider='claude_code')
        (directory / 'chat.jsonl').write_bytes(line(sid=name))
    refresh(store)
    before = dashboard(store)['summary']['total_tokens']
    with store.connect() as db:
        owner = db.execute("SELECT source_id FROM records WHERE provider='claude_code' AND total>0").fetchone()[0]
        unrelated = db.execute("SELECT segment_id FROM canonical WHERE provider='codex'").fetchone()[0]
        db.execute('INSERT INTO projection_queue VALUES(?)', (unrelated,))
    removed = store.forget_source(owner)
    with store.connect() as db:
        for segment in removed:
            store.choose_canonical(db, segment)
        affected = store.related_segments(db, removed)
        assert len(affected) == 2 and unrelated not in affected
        project_segments(store, db, affected)
        assert [r[0] for r in db.execute('SELECT segment_id FROM projection_queue')] == [unrelated]
        assert db.execute('SELECT count(*) FROM projection_dependencies').fetchone()[0] == 0
    assert dashboard(store)['summary']['total_tokens'] == before


def test_staged_mixed_provider_rebuild_respects_overlapping_response_owners(indexed):
    from codex_insights.providers.legacy.accounting import facts
    from codex_insights.providers.legacy.decoder import decode
    from codex_insights.codec import digest
    from legacy_fixtures import archive, ciphertext, KEY, SID
    from test_providers import line
    store, _ = seed(indexed, 1)
    legacy = store.directory.parent / 'legacy'
    legacy.mkdir()
    source = store.add_source(legacy, provider='antigravity')
    fact = facts(decode(ciphertext(archive()), KEY, SID), SID)
    fact.update(byte_count=100, prefix_hash=digest(['synthetic']), proofs={})
    with store.connect() as db:
        db.execute("UPDATE sources SET format='antigravity_legacy' WHERE id=?", (source,))
        store.put_candidate(db, source, fact, 1002)
        store.choose_canonical(db, fact['segment_id'])
    public = store.directory.parent / 'public'
    for sid, output in ((SID, 20), ('independent-copy', 10)):
        path = public / sid / '.system_generated/logs/transcript.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(line(sid=sid, output=output))
    store.add_source(public, provider='antigravity')
    refresh(store)
    rebuild_projection(store)
    before = dashboard(store)['summary']
    assert before['total_tokens'] == 110 + 117 + 160
    store.cooperate = lambda: None
    rebuild_projection(store)
    assert dashboard(store)['summary'] == before
    assert dashboard(store, {'provider': 'codex'})['summary']['total_tokens'] == 110


def test_import_yields_live_work_and_publishes_current_local_usage(indexed, tmp_path):
    from codex_insights.transfers import export_snapshot, import_snapshot
    store, root = seed(indexed, 1)
    incoming = Store(tmp_path / 'incoming')
    incoming_root = tmp_path / 'incoming-logs'
    incoming_root.mkdir()
    incoming.add_source(incoming_root)
    for i in range(55):
        (incoming_root / f'{i}.jsonl').write_bytes(log(f'incoming-{i}') + token(200, 590))
    refresh(incoming)
    path = tmp_path / 'snapshot.codex-insights'
    export_snapshot(incoming, path)
    before = dashboard(store)['summary']['total_tokens']
    changed = []
    def cooperate():
        if not changed:
            changed.append(True)
            with (root / '0.jsonl').open('ab') as stream:
                stream.write(token(400, 595))
            refresh(store)
            assert dashboard(store)['summary']['total_tokens'] == before + 330
    store.cooperate = cooperate
    result = import_snapshot(store, path)
    assert result['status'] == 'imported'
    assert dashboard(store)['summary']['total_tokens'] == before + 330 + 55 * 220
    assert import_snapshot(store, path)['status'] == 'unchanged'


def test_prepared_import_resumes_after_failed_publication(indexed, tmp_path, monkeypatch):
    from codex_insights.transfers import export_snapshot, import_snapshot
    from codex_insights import isolated_jobs
    store, _ = seed(indexed, 1)
    path = tmp_path / 'snapshot.codex-insights'
    export_snapshot(store, path)
    destination = Store(tmp_path / 'target')
    destination.cooperate = lambda: None
    original = isolated_jobs.publish
    def fail(*args): raise RuntimeError('interrupted publication')
    monkeypatch.setattr(isolated_jobs, 'publish', fail)
    with pytest.raises(RuntimeError):
        import_snapshot(destination, path)
    assert dashboard(destination)['summary']['total_tokens'] == 0
    assert list((destination.directory / 'work').glob('source-*/work-state.json'))
    monkeypatch.setattr(isolated_jobs, 'publish', original)
    destination.set_setting('timezone', 'Pacific/Auckland')
    resumed = Store(destination.directory)
    resumed.cooperate = lambda: None
    assert import_snapshot(resumed, path)['status'] == 'imported'
    assert dashboard(resumed)['summary']['total_tokens'] == 110
    assert dashboard(resumed)['timeline'][0]['day'] == '2026-10-02'


def test_prepared_import_cannot_replace_a_newer_accepted_revision(indexed, tmp_path, monkeypatch):
    from codex_insights.transfers import export_snapshot, import_snapshot
    from codex_insights import isolated_jobs
    store, _ = seed(indexed, 1)
    path = tmp_path / 'snapshot.codex-insights'
    export_snapshot(store, path)
    destination = Store(tmp_path / 'target')
    destination.cooperate = lambda: None
    monkeypatch.setattr(isolated_jobs, 'publish', lambda *args: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError):
        import_snapshot(destination, path)
    source_id = 'import:' + store.setting('exporter_id')
    with destination.connect() as db:
        db.execute("INSERT INTO sources(id,label,kind,revision) VALUES(?,'Newer accepted snapshot','import',2)", (source_id,))
    assert import_snapshot(destination, path) == {'status': 'unchanged', 'revision': 2}
    assert dashboard(destination)['summary']['total_tokens'] == 0
