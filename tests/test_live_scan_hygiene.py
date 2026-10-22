"""Watcher hints, cooperative discovery and re-walks cannot starve indexing."""
import json
import os
import time
from types import SimpleNamespace

from codex_insights import cooperative, index_scan
from codex_insights.codec import timestamp
from codex_insights.cooperative import LiveMaintenance
from codex_insights.index_scan import Scan, owning_live_work
from codex_insights.ingestion import refresh
from codex_insights.live_index import LivePaths
from codex_insights.parser import SessionParser
from codex_insights.providers import Adapter
from codex_insights.providers.transcripts import TranscriptParser
from conftest import T, event, log, token


def report():
    return dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0)


class Clock:
    """Monotonic time that only moves when the test says work took time."""
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    @staticmethod
    def time():
        return time.time()


def slow_walk(monkeypatch, clock, seconds):
    original = Adapter.discover
    def walk(self, root, kind='folder'):
        for path in original(self, root, kind):
            clock.now += seconds
            yield path
    monkeypatch.setattr(Adapter, 'discover', walk)


def test_cooperative_work_is_idle_while_a_scan_owns_live_hints(indexed):
    store, root, _ = indexed
    (root / 'a.jsonl').write_bytes(log('a') + token(100, 590))
    store.live_paths = LivePaths()
    worker = LiveMaintenance(store)
    try:
        with owning_live_work(store):
            worker()
        # Nothing walked or parsed underneath the scan that owns the hints.
        assert worker.scan is None
        worker()
        assert worker.scan is not None
    finally:
        worker.close()


def test_cooperative_discovery_is_sliced_and_resumes(indexed, monkeypatch):
    store, root, sid = indexed
    for i in range(70):
        (root / f'{i}.jsonl').write_bytes(log(f'chat-{i}') + token(100, 590))
    refresh(store)
    clock = Clock()
    monkeypatch.setattr(index_scan, 'time', clock)
    monkeypatch.setattr(cooperative, 'time', clock)
    slow_walk(monkeypatch, clock, .01)
    store.live_paths = LivePaths(clock=clock.monotonic)
    worker = LiveMaintenance(store)
    try:
        started = clock.now
        worker()
        # One 64-file chunk may overshoot the slice; the rest of the walk waits.
        assert worker.scan.walk is not None
        assert clock.now - started <= .25 + 64 * .01 + 1e-9
        for _ in range(10):
            if worker.scan.walk is None:
                break
            worker()
        assert worker.scan.walk is None
        assert sid in worker.scan.complete | worker.scan.finalized
    finally:
        worker.close()


def test_slow_inventory_cannot_starve_queued_work(indexed, monkeypatch):
    store, root, _ = indexed
    for i in range(20):
        (root / f'{i}.jsonl').write_bytes(log(f'chat-{i}') + token(100, 590))
    clock = Clock()
    monkeypatch.setattr(index_scan, 'time', clock)
    # Each walk takes longer than the interval. Measured from its start, every
    # loop iteration used to begin another walk and parse a single slice.
    slow_walk(monkeypatch, clock, 2)
    walks = []
    original = Scan.inventory
    def counted(self, primary_only=False):
        walks.append(primary_only)
        return original(self, primary_only)
    monkeypatch.setattr(Scan, 'inventory', counted)
    store.live_paths = LivePaths(clock=clock.monotonic)
    totals = report()
    Scan(store, store.sources(), totals, automatic=True).run()
    assert totals['changed_files'] == 20
    assert walks == [True]


def test_repeat_inventory_does_not_rewrite_unchanged_queued_backlog(indexed):
    store, root, _ = indexed
    old = time.time() - 3600
    for i in range(5):
        path = root / f'{i}.jsonl'
        path.write_bytes(log(f'chat-{i}') + token(100, 590))
        os.utime(path, (old, old))
    refresh(store)
    scan = Scan(store, store.sources(), report())
    for failures in scan.failures.values():
        failures.parser_version = 999  # The historical backlog a parser upgrade creates.
    try:
        scan.inventory()
        assert len(scan.tasks) == 5 and not scan.urgent
        with store.connect() as db:
            before = db.execute('SELECT rowid,path FROM pending_time_evidence ORDER BY path').fetchall()
        assert len(before) == 5
        scan.inventory()
        with store.connect() as db:
            assert db.execute('SELECT rowid,path FROM pending_time_evidence ORDER BY path').fetchall() == before
        # Changed bytes still lose their historical bound on the next walk.
        with (root / '0.jsonl').open('ab') as stream:
            stream.write(token(200, 595))
        os.utime(root / '0.jsonl', (old, old + 1))
        scan.inventory()
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM pending_time_evidence WHERE path=?",
                              (str(root / '0.jsonl'),)).fetchone()[0] == 0
    finally:
        scan.close()


def test_directory_access_events_do_not_force_rediscovery(indexed):
    _, root, sid = indexed
    folder = root / '2026' / '10'
    folder.mkdir(parents=True)
    live = LivePaths(clock=lambda: 0)
    live.begin_discovery()
    live.event(sid, root, SimpleNamespace(src_path=str(folder), event_type='modified', is_directory=True))
    assert not live.discovery_due()
    live.event(sid, root, SimpleNamespace(src_path=str(folder), event_type='created', is_directory=True))
    assert live.discovery_due()


def test_access_only_file_events_do_not_requeue_verified_history(indexed):
    store, root, sid = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 580))
    refresh(store)
    clock = [0]
    store.live_paths = LivePaths(clock=lambda: clock[0])
    modified = SimpleNamespace(src_path=str(path), event_type='modified', is_directory=False)
    store.live_paths.event(sid, root, modified)
    clock[0] = 10
    scan = Scan(store, store.sources(), report())
    try:
        scan.hints()
        assert not scan.tasks
        with store.connect() as db:
            assert db.execute('SELECT count(*) FROM index_pending').fetchone()[0] == 0
        with path.open('ab') as stream:
            stream.write(token(300, 590))
        store.live_paths.event(sid, root, modified)
        clock[0] = 20
        scan.hints()
        assert (sid, str(path)) in scan.urgent
    finally:
        scan.close()


def test_continuously_written_source_still_finalizes(indexed):
    store, root, sid = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100, 580))
    refresh(store)
    with store.connect() as db:
        db.execute("UPDATE sources SET status='Pending'")

    class Writing(LivePaths):
        """A session that never stops appending always has a hint waiting."""
        def pending(self):
            return [(sid, str(path))]

        def take(self, *, force=False, exclude=()):
            return []

    store.live_paths = Writing()
    Scan(store, store.sources(), report(), automatic=True).run()
    assert store.sources()[0]['status'] == 'Ready'


def test_time_evidence_reuses_the_parser_decode(indexed, monkeypatch):
    store, root, _ = indexed
    files = {
        'valid': log('valid') + token(100, 590),
        'untimed': log('untimed') + json.dumps({'type': 'event_msg', 'payload': {}}).encode() + b'\n' + token(100, 590),
        'invalid': log('invalid') + b'not json\n' + token(100, 590),
        'array': log('array') + b'[1, 2]\n' + token(100, 590),
        'tail': log('tail') + token(100, 590) + b'{"partial":',
    }
    for name, content in files.items():
        (root / f'{name}.jsonl').write_bytes(content)

    def evidence():
        with store.connect() as db:
            return {os.path.basename(r[0])[:-6]: r[1] for r in db.execute('SELECT path,affected_until FROM file_time_evidence')}

    refresh(store)
    reused = evidence()
    assert reused['valid'] == (T.timestamp() + 590)
    assert all(reused[name] is None for name in ('untimed', 'invalid', 'array', 'tail'))
    # The independent decode used for parsers without per-line results agrees.
    consume = SessionParser.consume
    def without_result(self, raw, end_offset):
        consume(self, raw, end_offset)
        del self.line_time
    monkeypatch.setattr(SessionParser, 'consume', without_result)
    refresh(store, rebuild=True)
    assert evidence() == reused


def test_transcript_line_time_matches_an_independent_decode():
    # The base consume() is shared by every transcript provider.
    parser = TranscriptParser('antigravity')
    lines = [b'{"timestamp": "2026-10-01T14:00:00Z", "type": "note"}\n', b'{"type": "note"}\n',
             b'not json\n', b'[1]\n', b'{"timestamp": 5}\n']
    offset = 0
    for raw in lines:
        offset += len(raw)
        parser.consume(raw, offset)
        try:
            item = json.loads(raw)
            expected = timestamp(item.get('timestamp')) if isinstance(item, dict) else None
        except ValueError:
            expected = None
        assert parser.line_time == expected


def test_restart_retires_pending_for_a_matching_verified_checkpoint(indexed):
    store, root, sid = indexed
    path = root / 'crash.jsonl'; path.write_bytes(log() + token(100, 590))
    refresh(store)
    with store.connect() as db:
        db.execute('INSERT INTO index_pending VALUES(?,?)', (sid, str(path)))
        db.execute('UPDATE pending_progress SET oldest_pending_at=?', (time.time() - 80,))
        db.execute('INSERT INTO pending_origins VALUES(?,?,?)', (sid, str(path), 'watcher'))
    assert refresh(store, automatic=True)['bytes_read'] == 0
    with store.connect() as db:
        for table in ('index_pending', 'pending_progress', 'pending_origins'):
            assert db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


def test_restart_rederives_coverage_when_new_checkpoint_preceded_health_commit(indexed, monkeypatch):
    from codex_insights import index_file
    import pytest
    store, root, sid = indexed
    path = root / 'crash.jsonl'; path.write_bytes(log() + token(100, 580))
    refresh(store)
    with path.open('ab') as stream:
        stream.write(b'{invalid}\n' + token(200, 590))
    with monkeypatch.context() as patch:
        def crash(*args, **kwargs):
            raise RuntimeError('crash after checkpoint/projection before coverage')
        patch.setattr(index_file, 'file_checked', crash)
        with pytest.raises(RuntimeError):
            refresh(store)
    with store.connect() as db:
        assert db.execute('SELECT issue_count FROM file_coverage').fetchone()[0] == 0
    assert refresh(store, automatic=True)['bytes_read'] == 0
    with store.connect() as db:
        assert db.execute('SELECT reason FROM file_coverage').fetchone()[0] == 'parse_gap'
        assert db.execute('SELECT count(*) FROM index_pending').fetchone()[0] == 0
        stamp = db.execute('SELECT size,mtime FROM file_time_evidence').fetchone()
        assert tuple(stamp) == (path.stat().st_size, path.stat().st_mtime_ns)
