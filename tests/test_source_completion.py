"""Per-source completion stays conservative while maintenance continues."""
import threading
import time

import pytest

from codex_insights.index_scan import Scan
from codex_insights.local_token_burn import LocalTokenBurn
from conftest import T, log, token
from test_review_regressions import seed


def scan_for(store, cancel=None):
    return Scan(store, store.sources(), dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0), cancel=cancel)


def offline(store):
    with store.connect() as db:
        db.execute("UPDATE sources SET status='Offline'")


def test_completed_source_does_not_wait_for_another_sources_tasks(indexed):
    store, root, sid = seed(indexed)
    other = root.with_name('other')
    other.mkdir()
    store.add_source(other)
    (other / 'large.jsonl').write_bytes(log('large') + b''.join(token(i, i) for i in range(1, 800)))
    offline(store)
    scan = scan_for(store)
    try:
        scan.inventory()
        assert scan.tasks
        while scan.finalize():
            pass
        assert next(s for s in store.sources() if s['id'] == sid)['status'] == 'Ready'
        assert scan.tasks
    finally:
        scan.close()


@pytest.mark.parametrize('interrupt', ['cancel', 'offline', 'newer_error'])
def test_stale_or_interrupted_inventory_cannot_mark_ready(indexed, interrupt):
    from codex_insights.index_health import source_checked
    store, root, sid = seed(indexed)
    offline(store)
    cancel = threading.Event()
    scan = scan_for(store, cancel)
    try:
        scan.inventory()
        if interrupt == 'cancel':
            cancel.set()
        elif interrupt == 'offline':
            root.rename(root.with_name('gone'))
        else:
            with store.connect() as db:
                source_checked(db, sid, error='discovery_error')
        scan.finalize()
        assert store.sources()[0]['status'] == 'Offline'
    finally:
        scan.close()


def test_ready_source_keeps_incomplete_tail_partial(indexed):
    store, root, sid = seed(indexed)
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(b'{"unfinished":')
    offline(store)
    scan = scan_for(store)
    try:
        scan.inventory()
        while scan.tasks:
            scan.step()
        while scan.finalize():
            pass
        assert store.sources()[0]['status'] == 'Ready'
        now = T.timestamp() + 10
        with store.connect() as db:
            db.execute('UPDATE index_health SET discovered_at=?,checked_at=?', (now, now))
        rate = LocalTokenBurn(store, clock=lambda: now).read()
        assert rate['status'] == 'available' and rate['partial']
        assert 'incomplete_tail' in {r['code'] for r in rate['coverage']['reasons']}
    finally:
        scan.close()


def test_verification_is_batched_and_idle_finalization_never_deserializes_history(indexed, monkeypatch):
    from codex_insights import copy_store
    store, root, sid = seed(indexed)
    with store.connect() as db:
        db.executemany('INSERT INTO history_pending VALUES(?,?,?)',
                       [(sid, f'session-{n:03}', 'legacy_conflict') for n in range(40)])
    sizes = []
    real = copy_store.finish_verification
    def verify(db, source, segments=None):
        sizes.append(len(segments))
        return real(db, source, segments)
    monkeypatch.setattr(copy_store, 'finish_verification', verify)
    scan = scan_for(store)
    try:
        scan.inventory()
        while scan.finalize():
            pass
        assert sizes == [16, 16, 8]
        monkeypatch.setattr(copy_store, 'finish_verification', lambda *args: pytest.fail('idle verification'))
        for _ in range(3):
            assert not scan.finalize()
    finally:
        scan.close()
