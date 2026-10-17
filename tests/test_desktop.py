import sys
import subprocess
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from codex_insights.desktop_controller import DesktopController
from codex_insights.desktop_preferences import DesktopPreferences, fit_rectangle
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.service import Engine
from codex_insights.storage import Store
from codex_insights.widget_queries import WidgetSummaries
from conftest import log, token, event


class Native:
    def __init__(self, fail_tray=False):
        self.fail_tray = fail_tray
        self.visible = True
        self.tray = self.widget = self.closed = False

    def setup(self, controller):
        self.controller = controller

    def dispatch(self, fn):
        fn()

    def ensure_tray(self):
        if self.fail_tray:
            raise OSError("No shell")
        self.tray = True

    def remove_tray(self): self.tray = False
    def show_dashboard(self): self.visible = True
    def hide_dashboard(self): self.visible = False
    def close_dashboard(self): self.closed = True
    def show_widget(self, _): self.widget = True
    def remove_widget(self): self.widget = False
    def update_menu(self, _): pass
    def dispose(self): self.tray = False


def controller(tmp_path, **kwargs):
    engine = SimpleNamespace(store=Store(tmp_path), stop=threading.Event(), cancel=threading.Event())
    result = DesktopController(engine, DesktopPreferences(engine.store))
    native = Native(**kwargs)
    result.attach(native)
    return result, native


def test_preferences_defaults_upgrade_and_restart(tmp_path):
    store = Store(tmp_path)
    store.set_setting("assumed_fast_percent", 17)
    prefs = DesktopPreferences(store)
    assert prefs.read() == {"tray_enabled": True, "widget_enabled": False,
                            "always_on_top": True, "metrics": ["tokens", "cost", "lines"],
                            "show_usage_remaining": False, "usage_remaining_bucket": "codex",
                            "widget_details_expanded": True, "widget_height_css_px": None,
                            "widget_account_ids": ["current"], "widget_account_buckets": {}}
    prefs.update({"widget_enabled": True, "widget_details_expanded": False, "metrics": ["chats", "tokens", "tokens"]})
    restored = DesktopPreferences(Store(tmp_path)).read()
    assert restored["widget_enabled"] and restored["metrics"] == ["tokens", "chats"]
    assert not restored["widget_details_expanded"]
    assert store.setting("assumed_fast_percent") == 17
    assert store.setting("data_revision") is None
    prefs.update({"metrics": []})
    assert prefs.read()["metrics"] == []


def test_allowance_preferences_upgrade_without_changing_selected_metrics(tmp_path):
    store = Store(tmp_path)
    store.set_setting("desktop_preferences", {"metrics": ["chats"], "widget_enabled": True})
    prefs = DesktopPreferences(store)
    assert prefs.read()["metrics"] == ["chats"] and not prefs.read()["show_usage_remaining"]
    prefs.update({"show_usage_remaining": True, "usage_remaining_bucket": "other"})
    restored = DesktopPreferences(Store(tmp_path)).read()
    assert restored["metrics"] == ["chats"] and restored["show_usage_remaining"]
    assert restored["usage_remaining_bucket"] == "other"


@pytest.mark.parametrize("height", [120, 360, 700.5, 65536, None])
def test_widget_height_persists_and_can_return_to_automatic(tmp_path, height):
    store = Store(tmp_path)
    prefs = DesktopPreferences(store)
    prefs.update({"widget_height_css_px": height})
    assert DesktopPreferences(store).read()["widget_height_css_px"] == height
    prefs.update({"widget_height_css_px": None})
    assert DesktopPreferences(store).read()["widget_height_css_px"] is None


@pytest.mark.parametrize("height", [0, 119, -1, 65537, True, "360", float("nan"), float("inf")])
def test_invalid_widget_heights_are_rejected_and_old_bad_values_ignored(tmp_path, height):
    store = Store(tmp_path)
    prefs = DesktopPreferences(store)
    with pytest.raises(ValueError): prefs.update({"widget_height_css_px": height})
    assert prefs.revision == 0
    store.set_setting("desktop_preferences", {"widget_height_css_px": height})
    assert DesktopPreferences(store).read()["widget_height_css_px"] is None


def test_account_navigation_requests_have_monotonic_sequence(tmp_path):
    host, native = controller(tmp_path)
    native.visible = False
    host.command("show_account", "current")
    assert native.visible
    assert host.state()["account_request"] == {"sequence": 1, "account_id": "current"}
    host.command("show_account", "current")
    assert host.state()["account_request"]["sequence"] == 2
    with pytest.raises(ValueError): host.command("show_account", "../bad")
    with pytest.raises(ValueError): host.command("show_account")


def test_switches_apply_while_index_holds_writer_and_persist_on_exit(tmp_path):
    store = Store(tmp_path)
    prefs = DesktopPreferences(store, background=True)
    locked, release = threading.Event(), threading.Event()
    def index_transaction():
        with store.lock:
            locked.set()
            release.wait(5)
    worker = threading.Thread(target=index_transaction)
    worker.start()
    assert locked.wait(1)
    try:
        start = time.monotonic()
        prefs.update({'widget_enabled': True})
        prefs.update({'metrics': ['chats']})
        assert time.monotonic() - start < 1
        assert prefs.read()['widget_enabled'] and prefs.read()['metrics'] == ['chats']
    finally:
        release.set()
        worker.join()
        prefs.close()
    saved = DesktopPreferences(Store(tmp_path)).read()
    assert saved['widget_enabled'] and saved['metrics'] == ['chats']


@pytest.mark.parametrize("invalid", [{"tray_enabled": "false"}, {"metrics": "tokens"},
                                    {"metrics": ["other"]}, {"unrelated": True}])
def test_invalid_preferences_do_not_write(tmp_path, invalid):
    prefs = DesktopPreferences(Store(tmp_path))
    with pytest.raises(ValueError): prefs.update(invalid)
    assert prefs.read()["tray_enabled"] is True
    assert prefs.revision == 0


@pytest.mark.parametrize("tray,widget", [(True, False), (True, True), (False, True), (False, False)])
def test_close_behavior_for_each_combination(tmp_path, tray, widget):
    host, native = controller(tmp_path)
    host.update({"tray_enabled": tray, "widget_enabled": widget})
    assert native.widget == widget
    assert host.closing_dashboard() == tray
    if tray:
        assert not native.visible and native.widget == widget
        assert not host.engine.stop.is_set()
        host.command("show_dashboard")
        assert native.visible
    else:
        assert host.engine.stop.is_set() and not native.widget and not native.tray


def test_disable_tray_restores_hidden_dashboard_and_quit_stops_everything(tmp_path):
    host, native = controller(tmp_path)
    host.update({"widget_enabled": True})
    host.closing_dashboard()
    host.update({"tray_enabled": False})
    assert native.visible and not native.tray and native.widget
    host.command("quit")
    assert native.closed and not native.widget
    assert host.engine.stop.is_set() and host.engine.cancel.is_set()


def test_failed_tray_and_system_shutdown_never_hide(tmp_path):
    host, native = controller(tmp_path, fail_tray=True)
    assert host.error and not host.tray_active
    assert not host.closing_dashboard()
    other, native = controller(tmp_path / "other")
    assert not other.closing_dashboard(user_close=False)
    assert other.quitting and not native.tray


def test_settings_command_and_widget_toggle_do_not_stop_indexing(tmp_path):
    host, native = controller(tmp_path)
    host.command("show_settings")
    assert host.state()["settings_request"] == 1
    for enabled in (True, False, True, False):
        host.update({"widget_enabled": enabled})
        assert native.widget == enabled
        assert not host.engine.stop.is_set()


def test_offscreen_position_and_negative_monitor_origin():
    assert fit_rectangle(5000, 5000, 360, 240, (0, 0, 1920, 1040)) == (1560, 800)
    assert fit_rectangle(-4000, 100, 360, 240, (-1920, 0, 0, 1040)) == (-1920, 100)
    assert fit_rectangle(0, 0, 360, 240, (0, 0, 320, 200)) == (0, 0)


@pytest.mark.parametrize("buckets", [True, False])
def test_widget_matches_dashboard_including_partial_coverage(indexed, buckets):
    store, root, _ = indexed
    content = log() + token(100)
    content += event('turn_context', {'model': 'unpriced-model'}, 4)
    content += token(200, 5, last=100)
    content += event('response_item', {'type': 'custom_tool_call', 'name': 'apply_patch', 'call_id': 'pending',
        'input': '*** Begin Patch\n*** Add File: file.txt\n+hello\n*** End Patch'}, 6)
    (root / 'chat.jsonl').write_bytes(content)
    refresh(store)
    if not buckets: store.set_setting('bucket_version', None)
    summaries = WidgetSummaries(store, lambda: datetime(2026, 10, 1, 23, tzinfo=timezone.utc)).read()
    for column, filters in [('today', {'range': 'custom', 'start': '2026-10-01', 'end': '2026-10-01'}), ('all_time', {})]:
        expected = dashboard(store, filters)['summary']
        for key, value in summaries[column].items():
            assert value == expected[key], key
    assert summaries['today']['priced_percent'] < 100
    assert summaries['today']['change_coverage'] == 'partial'


def test_widget_cache_invalidates_for_revision_timezone_and_midnight(indexed, monkeypatch):
    from codex_insights import widget_queries
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100))
    refresh(store)
    now = [datetime(2026, 10, 2, 3, 59, tzinfo=timezone.utc)]
    original = widget_queries.query_summary
    calls = []
    def tracked(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(widget_queries, 'query_summary', tracked)
    cache = WidgetSummaries(store, lambda: now[0])
    assert cache.read()['today']['total_tokens'] == 110
    cache.read()
    assert len(calls) == 2
    now[0] = datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc)
    assert cache.read()['today']['total_tokens'] == 0
    assert cache.read()['all_time']['total_tokens'] == 110
    store.set_setting('timezone', 'UTC')
    assert cache.read()['timezone'] == 'UTC'
    store.set_setting('data_revision', 999)
    assert cache.read()['revision'] == 999
    assert len(calls) == 8


def test_desktop_controls_unavailable_headless_and_save_while_busy(tmp_path):
    engine = Engine(tmp_path, demo=True)
    try:
        assert engine.call('desktop_state') == {'available': False}
        with pytest.raises(ValueError): engine.call('desktop_settings', {'widget_enabled': True})
        engine.desktop = DesktopController(engine)
        engine.desktop.attach(Native())
        engine.job['running'] = True
        assert engine.call('desktop_settings', {'widget_enabled': True})['preferences']['widget_enabled']
        assert engine.call('widget_summary')['job']['running']
        assert engine.call('dashboard')['desktop']['available']
    finally:
        engine.close()


def test_hidden_dashboard_keeps_watching_and_quit_stops_workers(tmp_path):
    engine = Engine(tmp_path / 'data')
    for source in engine.store.sources():
        engine.store.forget_source(source['id'])
    root = tmp_path / 'sessions'
    root.mkdir()
    engine.store.add_source(root)
    engine.desktop = DesktopController(engine)
    engine.desktop.attach(Native())
    engine.start()
    try:
        assert engine.desktop.closing_dashboard()
        (root / 'chat.jsonl').write_bytes(log() + token(100))
        engine.dirty.set()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and dashboard(engine.store)['summary']['total_tokens'] != 110:
            time.sleep(.05)
        assert dashboard(engine.store)['summary']['total_tokens'] == 110
        engine.desktop.command('quit')
    finally:
        engine.close()
    assert not engine.watch_thread.is_alive()
    assert engine.observer is None or not engine.observer.is_alive()
    assert engine.submit('Late work', lambda: None) == {'status': 'stopping'}


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows kernel objects')
def test_single_instance_activation_and_release(tmp_path):
    from codex_insights.single_instance import SingleInstance
    first = SingleInstance(tmp_path)
    assert first.owner
    activated = threading.Event()
    first.listen(activated.set)
    code = "from codex_insights.single_instance import SingleInstance; import sys; guard=SingleInstance(sys.argv[1]); print(guard.owner); guard.close()"
    try:
        child = subprocess.run([sys.executable, '-c', code, str(tmp_path)], capture_output=True, text=True, timeout=10)
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == 'False'
        assert activated.wait(2)
        other = SingleInstance(tmp_path / 'demo')
        assert other.owner
        other.close()
    finally:
        first.close()
    new = SingleInstance(tmp_path)
    assert new.owner
    new.close()
