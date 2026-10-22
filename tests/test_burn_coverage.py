import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from codex_insights.ingestion import refresh
from codex_insights.index_failures import FileFailures
from codex_insights.index_health import event_time_bound
from codex_insights.live_index import LivePaths
from codex_insights.local_token_burn import LocalTokenBurn
from codex_insights import index_file
from conftest import T, event, log, token


def codes(rate):
    return {r['code'] for r in rate['coverage']['reasons']}


def check_time(store, at):
    with store.connect() as db:
        db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (at, at))


def test_old_valid_timestamps_bound_a_failure_but_unknown_records_do_not(indexed):
    store, root, sid = indexed
    old = root / 'old.jsonl'
    old.write_bytes(event('session_meta', {'id': 'bad', 'git': 'invalid'}, 0))
    (root / 'live.jsonl').write_bytes(log('live') + token(1000, 590))
    refresh(store)
    now = T.timestamp() + 600
    check_time(store, now)
    reader = LocalTokenBurn(store, clock=lambda: now)
    assert reader.read()['value'] == 220
    assert reader.read()['coverage']['state'] == 'complete'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM file_failures').fetchone()[0] == 1
    old.write_bytes(b'{not json}\n')
    refresh(store)
    check_time(store, now)
    assert 'parse_gap' in codes(reader.read())
    assert event_time_bound(old, old.stat().st_size) is None


def test_current_failure_ages_out_only_after_its_verified_timestamp(indexed):
    store, root, _ = indexed
    (root / 'bad.jsonl').write_bytes(event('session_meta', {'id': 'bad', 'git': 'invalid'}, 550))
    (root / 'live.jsonl').write_bytes(log() + token(1000, 590))
    refresh(store)
    clock = [T.timestamp() + 600]
    check_time(store, clock[0])
    reader = LocalTokenBurn(store, clock=lambda: clock[0])
    assert 'file_error' in codes(reader.read())
    clock[0] += 250
    check_time(store, clock[0])
    assert 'file_error' not in codes(reader.read())


def test_retry_backoff_survives_restart_and_does_not_retry_deterministic_errors(indexed):
    store, root, sid = indexed
    path = root / 'test.jsonl'
    path.write_bytes(log())
    clock = [100.0]
    for delay in (5, 30, 120, 300, 300):
        failures = FileFailures(store, sid, clock=lambda: clock[0])
        failures.record(path, path.stat(), PermissionError('private contents'))
        assert failures.skip(path, path.stat(), True)
        clock[0] += delay
        assert not FileFailures(store, sid, clock=lambda: clock[0]).skip(path, path.stat(), True)
    failures.record(path, path.stat(), ValueError('invalid shape'))
    clock[0] += 100000
    assert failures.skip(path, path.stat(), True)
    assert not failures.skip(path, path.stat(), False)
    failures.clear(path)
    with store.connect() as db:
        assert not db.execute('SELECT 1 FROM index_retries').fetchone()


def test_incomplete_tail_stays_partial_until_completed(indexed):
    store, root, _ = indexed
    path = root / 'chat.jsonl'
    tail = token(200, 590)
    path.write_bytes(log() + token(100, 580) + tail[:15])
    refresh(store)
    now = T.timestamp() + 600
    check_time(store, now)
    reader = LocalTokenBurn(store, clock=lambda: now)
    assert 'incomplete_tail' in codes(reader.read())
    refresh(store)
    check_time(store, now)
    assert 'incomplete_tail' in codes(reader.read())
    with path.open('ab') as stream:
        stream.write(tail[15:])
    refresh(store)
    check_time(store, now)
    assert reader.read()['coverage']['state'] == 'complete'
    assert reader.read()['value'] == 44


def test_index_errors_preserve_last_value_without_leaking_exception(indexed, monkeypatch):
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    check_time(store, now)
    reader = LocalTokenBurn(store, clock=lambda: now)
    previous = reader.read()
    @contextmanager
    def broken():
        raise sqlite3.DatabaseError('PRIVATE DATA')
        yield
    monkeypatch.setattr(store, 'connect', broken)
    result = reader.read()
    assert result['status'] == 'stale' and result['value'] == previous['value']
    assert codes(result) == {'index_error'}
    assert 'PRIVATE' not in json.dumps(result)
    assert LocalTokenBurn(store).read()['status'] == 'unavailable'


def test_watcher_deduplicates_continuous_changes_and_checks_move_destination(tmp_path):
    clock = [0]
    queue = LivePaths(clock=lambda: clock[0])
    root = tmp_path / 'root'
    root.mkdir()
    target = root / 'chat.jsonl'
    move = SimpleNamespace(src_path=str(tmp_path / 'outside.tmp'), dest_path=str(target),
                           is_directory=False, event_type='moved')
    queue.event('source', root, move)
    clock[0] = 4
    queue.event('source', root, move)
    assert queue.take() == []
    clock[0] = 5
    assert queue.take() == [('source', str(target.resolve()))]
    assert queue.take() == []


def test_recent_watcher_work_interrupts_large_historical_file(indexed, monkeypatch):
    store, root, sid = indexed
    store.live_paths = LivePaths(cooldown=0)
    historical = root / 'old.jsonl'
    historical.write_bytes(log('old') + b''.join(event('event_msg', {'type': 'agent_message', 'message': 'x'}, i) for i in range(1000)))
    live = root / 'live.jsonl'
    from codex_insights.parser import SessionParser
    consume = SessionParser.consume
    saw_live = []
    def observe(self, raw, end):
        consume(self, raw, end)
        if self.state['ordinal'] == 100:
            live.write_bytes(log('new') + token(1000, 590))
            store.live_paths.event(sid, root, SimpleNamespace(src_path=str(live), event_type='created', is_directory=False))
        if self.state['ordinal'] == 600:
            with store.connect() as db:
                saw_live.append(db.execute("SELECT count(*) FROM canonical WHERE session_id='new'").fetchone()[0])
    monkeypatch.setattr(SessionParser, 'consume', observe)
    refresh(store)
    assert saw_live == [1]


def test_read_boundary_does_not_follow_new_appends(indexed, monkeypatch):
    store, root, _ = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 580))
    from codex_insights.parser import SessionParser
    consume = SessionParser.consume
    appended = []
    def append(self, raw, end):
        consume(self, raw, end)
        if not appended:
            appended.append(True)
            with path.open('ab') as stream:
                stream.write(token(300, 590))
    monkeypatch.setattr(SessionParser, 'consume', append)
    refresh(store)
    with store.connect() as db:
        assert db.execute('SELECT sum(total) FROM records').fetchone()[0] == 110
    refresh(store)
    with store.connect() as db:
        assert db.execute('SELECT sum(total) FROM records').fetchone()[0] == 330


def test_discovery_error_remains_visible_and_recovery_clears_it(indexed, monkeypatch):
    from codex_insights.providers import Adapter
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100, 590))
    refresh(store)
    now = T.timestamp() + 600
    original = Adapter.discover
    def denied(*args):
        raise PermissionError('denied')
        yield
    monkeypatch.setattr(Adapter, 'discover', denied)
    refresh(store)
    reader = LocalTokenBurn(store, clock=lambda: now)
    assert 'discovery_error' in codes(reader.read())
    monkeypatch.setattr(Adapter, 'discover', original)
    refresh(store)
    check_time(store, now)
    assert reader.read()['coverage']['state'] == 'complete'


def test_old_indexes_backfill_parse_coverage_without_reparsing_unchanged_files(indexed):
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + b'{invalid}\n' + token(100, 590))
    refresh(store)
    with store.connect() as db:
        db.execute('DELETE FROM file_coverage')
        db.execute('DELETE FROM index_health')
    now = T.timestamp() + 600
    reader = LocalTokenBurn(store, clock=lambda: now)
    assert 'coverage_unverified' in codes(reader.read())
    assert refresh(store)['bytes_read'] == 0
    check_time(store, now)
    assert 'parse_gap' in codes(reader.read())


def test_stale_dollar_rate_keeps_both_pricing_and_source_reasons(indexed):
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + event('turn_context', {'model': 'not-priced'}, 1) + token(100, 590))
    refresh(store)
    clock = [T.timestamp() + 600]
    check_time(store, clock[0])
    reader = LocalTokenBurn(store, clock=lambda: clock[0])
    assert codes(reader.read_rates()['cost_burn_rate']) == {'unpriced_usage'}
    assert reader.read()['coverage']['state'] == 'complete'
    clock[0] += 601
    stale = reader.read_rates()['cost_burn_rate']
    assert stale['status'] == 'stale'
    assert codes(stale) == {'unpriced_usage', 'indexing_delayed'}


def test_watcher_fast_path_does_not_walk_history_and_does_not_postpone_discovery(indexed, monkeypatch):
    from codex_insights.providers import Adapter
    store, root, sid = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 580))
    refresh(store)
    clock = [0]
    store.live_paths = LivePaths(clock=lambda: clock[0])
    store.live_paths.begin_discovery()
    with path.open('ab') as stream:
        stream.write(token(300, 590))
    store.live_paths.event(sid, root, SimpleNamespace(src_path=str(path), event_type='modified', is_directory=False))
    original = Adapter.discover
    def must_not_walk(*args):
        raise AssertionError('Watcher updates must not walk the historical tree')
    monkeypatch.setattr(Adapter, 'discover', must_not_walk)
    clock[0] = 5
    assert refresh(store, automatic=True)['changed_files'] == 1
    assert not store.live_paths.discovery_due()
    clock[0] = 30
    assert store.live_paths.discovery_due()
    monkeypatch.setattr(Adapter, 'discover', original)
    assert refresh(store, automatic=True)['bytes_read'] == 0


def test_failed_projection_cannot_advance_file_coverage(indexed, monkeypatch):
    store, root, sid = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 590))
    def fail(*args):
        raise RuntimeError('projection unavailable')
    monkeypatch.setattr(index_file, 'project_segments', fail)
    import pytest
    with pytest.raises(RuntimeError):
        refresh(store)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM index_pending').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM projection_queue').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM file_coverage').fetchone()[0] == 0


def test_never_invent_idle_zero_when_all_sources_have_pending_work(indexed):
    store, root, sid = indexed
    refresh(store)
    now = T.timestamp() + 600
    check_time(store, now)
    with store.connect() as db:
        db.execute('INSERT INTO index_pending VALUES(?,?)', (sid, str(root / 'new.jsonl')))
    rate = LocalTokenBurn(store, clock=lambda: now).read()
    # A labeled observed subtotal can be zero; it must never be called complete.
    assert rate['status'] == 'collecting' and rate['value'] is None
    assert rate['coverage']['freshness']['state'] == 'updating'
