"""Closing the app, relaunching it, and retrying failed work stay bounded."""
import os
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from codex_insights.backup_retention import prune_upgrade_backups
from codex_insights.claude_recovery_store import save_report
from codex_insights.claude_usage import ClaudeUsage
from codex_insights.deferred_engine import DeferredEngine
from codex_insights.desktop_controller import DesktopController
from codex_insights.desktop_preferences import DesktopPreferences
from codex_insights.jobs import Jobs
from codex_insights.service import Engine
from codex_insights.storage import Store, tracked
from test_desktop import Native

ENDLESS = ('WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<300000000) '
           'SELECT count(*) FROM n')


def drain(jobs):
    jobs.executor.submit(lambda: None).result(timeout=5)


def test_failing_automatic_work_backs_off_and_success_resets():
    clock = [100.0]
    jobs = Jobs(clock=lambda: clock[0], cooldown=5, max_backoff=30)
    def full():
        raise sqlite3.OperationalError('database or disk is full')
    try:
        for delay in (10, 20, 30, 30):
            clock[0] = jobs.next_automatic
            assert jobs.submit('Scan', full, origin='automatic', key='automatic-refresh')['status'] == 'started'
            drain(jobs)
            assert jobs.next_automatic - clock[0] == delay
        # A user's own failing action never postpones automatic work further.
        jobs.submit('Save', full)
        drain(jobs)
        assert jobs.automatic_failures == 4
        clock[0] = jobs.next_automatic
        jobs.submit('Scan', lambda: None, origin='automatic', key='automatic-refresh')
        drain(jobs)
        assert jobs.automatic_failures == 0 and jobs.next_automatic - clock[0] == 5
    finally:
        jobs.close()


def test_job_close_can_stop_waiting_for_running_work():
    jobs = Jobs()
    release = threading.Event()
    jobs.submit('Slow', lambda: release.wait(10))
    started = time.monotonic()
    assert jobs.close(timeout=.2) is False
    assert time.monotonic() - started < 2
    release.set()
    assert jobs.close(timeout=5) is True
    assert jobs.submit('Late', lambda: None) == {'status': 'stopping'}


def test_engine_close_interrupts_a_report_within_its_deadline(tmp_path):
    engine = Engine(tmp_path / 'demo', demo=True, defer_projection=True)
    engine.start()
    entered = threading.Event()
    def report():
        with engine.store.connect() as db, tracked(engine.store, db):
            entered.set()
            db.execute(ENDLESS).fetchone()
    engine.submit('Exporting HTML report', report)
    assert entered.wait(5)
    started = time.monotonic()
    engine.close(timeout=6)
    assert time.monotonic() - started < 5
    assert engine.jobs.future.done()


def test_quit_starts_engine_shutdown_before_the_window_loop_ends(tmp_path):
    calls = []

    class Started:
        window = desktop = None
        def start(self): calls.append('start')
        def begin_close(self): calls.append('begin_close')
        def close(self, timeout=None): calls.append('close')

    engine = DeferredEngine(tmp_path, factory=lambda *args, **kwargs: Started())
    engine.start()
    assert engine.ready.wait(5)
    controller = DesktopController(SimpleNamespace(store=Store(tmp_path), begin_close=engine.begin_close),
                                   DesktopPreferences(Store(tmp_path)))
    controller.attach(Native())
    controller.command('quit')
    assert calls == ['start', 'begin_close'] and engine.stop.is_set()
    engine.close()
    assert calls[-1] == 'close'


def test_claude_usage_retries_no_faster_than_a_healthy_check(tmp_path):
    provider = SimpleNamespace(fetch=lambda changed=None: {}, close=lambda: None)
    assert ClaudeUsage(tmp_path, provider=provider).backoff_base == 300


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows kernel objects')
def test_launch_during_shutdown_waits_for_the_closing_window(tmp_path):
    from codex_insights.single_instance import SingleInstance
    closing = SingleInstance(tmp_path)  # Its activation listener has already stopped.
    assert closing.owner
    result = {}
    def launch(**timeouts):
        later = SingleInstance(tmp_path, ack_timeout=200, **timeouts)
        result.update(owner=later.owner, handed_over=later.handed_over, acknowledged=later.acknowledged)
        later.close()
    try:
        # Still closing after the handoff timeout: report it instead of vanishing.
        # (Mutexes are re-entrant per thread; a real launch is another process.)
        timed_out = threading.Thread(target=launch, kwargs={'handoff_timeout': 200})
        timed_out.start()
        timed_out.join(10)
        assert result == {'owner': False, 'handed_over': False, 'acknowledged': False}
        waiting = threading.Thread(target=launch, kwargs={'handoff_timeout': 10000})
        waiting.start()
        time.sleep(.6)  # Past the acknowledgement timeout, now waiting for the mutex.
    finally:
        closing.close()
    waiting.join(10)
    assert result == {'owner': True, 'handed_over': True, 'acknowledged': False}


@pytest.mark.skipif(sys.platform != 'win32', reason='WinForms desktop integration')
def test_reloading_the_page_never_duplicates_tray_widget_or_listener(tmp_path, monkeypatch):
    from codex_insights import desktop, windows_desktop

    class Event(list):
        def __iadd__(self, handler):
            self.append(handler)
            return self

    window = SimpleNamespace(events=SimpleNamespace(loaded=Event(), shown=Event(), closed=Event(), before_show=Event()),
                             native=SimpleNamespace(BeginInvoke=lambda action: action()))
    created = []

    class FakeDesktop(Native):
        def __init__(self, *args):
            super().__init__()
            created.append(self)

    def start(**_):
        for _ in range(2):  # First load, then "Try again" after a startup error.
            for handler in list(window.events.loaded):
                handler()

    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(create_window=lambda *a, **k: window, start=start))
    monkeypatch.setitem(sys.modules, 'System', SimpleNamespace(Action=lambda fn: fn))
    monkeypatch.setattr(windows_desktop, 'WindowsDesktop', FakeDesktop)
    store = Store(tmp_path)
    starts = []
    engine = SimpleNamespace(store=store, exporter=False, stop=threading.Event(), cancel=threading.Event(),
                             window=None, desktop=None, start=lambda: starts.append(1), when_ready=lambda callback: callback())
    listeners = []
    instance = SimpleNamespace(listen=listeners.append, stopped=threading.Event())
    desktop.run_desktop(engine, 'http://127.0.0.1:1', instance=instance)
    assert len(created) == 1 and len(listeners) == 1 and len(starts) == 1


def test_finished_upgrade_backups_are_removed_after_two_weeks(tmp_path):
    store = Store(tmp_path)
    now = time.time()
    names = ('insights.before-copy-review.sqlite3', 'insights.before-claude-identity-v1.sqlite3',
             'insights.before-copy-review.tmp')
    for name in names:
        (tmp_path / name).write_bytes(b'backup')
        os.utime(tmp_path / name, (now - 13 * 86400, now - 13 * 86400))
    # Interrupted copies go after a day; finished backups stay for two weeks.
    assert prune_upgrade_backups(store, now) == ['insights.before-copy-review.tmp']
    store._claude_identity_backup_verified = True
    assert sorted(prune_upgrade_backups(store, now + 2 * 86400)) == sorted(names[:2])
    assert not any((tmp_path / name).exists() for name in names)
    assert not store._claude_identity_backup_verified


@pytest.mark.parametrize('unfinished', ['copy_review', 'claude_recovery'])
def test_unfinished_upgrades_keep_their_backups(tmp_path, unfinished):
    store = Store(tmp_path)
    with store.connect() as db:
        if unfinished == 'copy_review':
            db.execute("DELETE FROM settings WHERE key='copy_history_version'")
            name = 'insights.before-copy-review.sqlite3'
        else:
            save_report(db, 'source', 'pending', {})
            name = 'insights.before-claude-identity-v1.sqlite3'
    old = time.time() - 30 * 86400
    (tmp_path / name).write_bytes(b'backup')
    os.utime(tmp_path / name, (old, old))
    assert prune_upgrade_backups(store) == []
    assert (tmp_path / name).exists()
