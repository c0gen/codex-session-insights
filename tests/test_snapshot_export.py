"""Refresh, cancellation and shared Claude pricing through exporter jobs."""
import threading
import time
import zipfile
from pathlib import Path

import pytest

from codex_insights import snapshot_export, transfers
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.service import Engine
from codex_insights.storage import Store
from test_claude_cost_history import line


@pytest.fixture
def exporter(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setenv('CODEX_HOME', str(home / '.codex'))
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    engine = Engine(tmp_path / 'data', exporter=True)
    engine.store.set_setting('timezone', 'UTC')
    root = home / '.claude/projects/project'
    root.mkdir(parents=True)
    path = root / 'main.jsonl'
    path.write_bytes(line(speed='fast', inference_geo='us', service_tier='standard'))
    refresh(engine.store)
    yield engine, path
    engine.close()


def wait_job(engine, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = next((j for j in engine.call('status')['completed'] if j['id'] == job_id), None)
        if result:
            return result
        time.sleep(.01)
    pytest.fail('Export did not finish')


def test_queued_export_refreshes_appends_and_roundtrips_claude_pricing(exporter, tmp_path, monkeypatch):
    engine, path = exporter
    path.write_bytes(path.read_bytes() + line(mid='new-response', model='claude-sonnet-5-5'))
    child = path.parent / 'main/subagents/agent-a.jsonl'
    child.parent.mkdir(parents=True)
    child.write_bytes(line(mid='child', model='claude-sonnet-5-5'))
    # A copied response must not add cost or discard the richer pricing metadata.
    (path.parent / 'copy.jsonl').write_bytes(line(sid='copy'))
    release = threading.Event()
    engine.submit('Earlier source work', lambda: release.wait(5))
    target = tmp_path / 'usage.codex-insights'
    monkeypatch.setattr(engine, 'choose', lambda *_: str(target))
    accepted = engine.call('export')
    assert accepted['status'] == 'queued'
    release.set()
    completed = wait_job(engine, accepted['job_id'])
    assert completed['state'] == 'completed'
    assert completed['result']['warnings'] == []
    assert completed['result']['refresh']['changed_files'] == 3
    local = dashboard(engine.store, {'provider': 'claude_code'})
    imported = Store(tmp_path / 'imported')
    transfers.import_snapshot(imported, target)
    remote = dashboard(imported, {'provider': 'claude_code'})
    assert local['summary']['cost'] == remote['summary']['cost'] == 25.09
    assert local['usage_metrics'] == remote['usage_metrics']
    assert local['summary']['priced_percent'] == remote['summary']['priced_percent'] == 100
    with zipfile.ZipFile(target) as archive:
        raw = archive.read('facts.jsonl')
        assert b'"speed":"fast"' in raw and b'"inference_geo":"us"' in raw
        assert b'PRIVATE_RESPONSE' not in raw and b'C:/private' not in raw
    assert not engine.claude_usage.allowed and not engine.antigravity_usage.allowed


def test_offline_retained_history_warns_but_unused_default_roots_do_not(exporter, tmp_path):
    engine, path = exporter
    # Simulate a disconnected indexed root without moving the fixture files.
    claude = next(s for s in engine.store.sources() if s['provider'] == 'claude_code')
    with engine.store.connect() as db:
        db.execute('UPDATE sources SET root=? WHERE id=?', (str(tmp_path / 'missing'), claude['id']))
    target = tmp_path / 'offline.codex-insights'
    result = snapshot_export.export_usage(engine.store, target)
    assert result['refresh']['offline_sources'] == 1
    assert len(result['warnings']) == 1 and 'retained history' in result['warnings'][0]
    imported = Store(tmp_path / 'imported')
    transfers.import_snapshot(imported, target)
    assert dashboard(imported)['summary']['cost'] == 17.25


def test_file_read_failure_preserves_accepted_history_and_warns(exporter, tmp_path, monkeypatch):
    engine, path = exporter
    path.write_bytes(path.read_bytes() + line(mid='unreadable-new'))
    original = Path.open

    def fail_file(self, *args, **kwargs):
        if self == path:
            raise PermissionError('synthetic')
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', fail_file)
    result = snapshot_export.export_usage(engine.store, tmp_path / 'partial.codex-insights')
    assert result['refresh']['errors'] == 1 and len(result['warnings']) == 1
    assert dashboard(engine.store)['summary']['cost'] == 17.25


@pytest.mark.parametrize('failure', ['during_refresh', 'after_compression', 'write'])
def test_cancel_or_write_failure_preserves_destination_and_revision(exporter, tmp_path, monkeypatch, failure):
    engine, _ = exporter
    destination = tmp_path / 'existing.codex-insights'
    destination.write_bytes(b'existing snapshot')
    revision = engine.store.setting('export_revision', 0)
    cancel = threading.Event()
    if failure == 'during_refresh':
        def cancelled(*_):
            cancel.set()
            return {'cancelled': True}
        monkeypatch.setattr(snapshot_export, 'refresh', cancelled)
    elif failure == 'after_compression':
        write = zipfile.ZipFile.write
        def cancelled_write(self, *args, **kwargs):
            result = write(self, *args, **kwargs)
            cancel.set()
            return result
        monkeypatch.setattr(zipfile.ZipFile, 'write', cancelled_write)
    else:
        def failed_write(*_):
            raise OSError('synthetic write failure')
        monkeypatch.setattr(transfers.os, 'replace', failed_write)
    with pytest.raises(OSError):
        snapshot_export.export_usage(engine.store, destination, cancel=cancel)
    assert destination.read_bytes() == b'existing snapshot'
    assert engine.store.setting('export_revision', 0) == revision
