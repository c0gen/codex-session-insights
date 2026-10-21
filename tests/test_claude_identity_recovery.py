"""Recover separate agent histories, preserving physical evidence and accounting."""
import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from codex_insights.codec import pack, unpack
from codex_insights.ingestion import anchor, refresh
from codex_insights.projection import rebuild_projection
from codex_insights.providers import adapter
from codex_insights.providers import claude_identity
from codex_insights.providers.transcripts import TranscriptParser
from codex_insights.storage import Store
from codex_insights.queries import dashboard
from codex_insights.history_review import read, resolve
from codex_insights.claude_recovery_store import status
from codex_insights.snapshot_export import export_usage
from codex_insights.transfers import export_snapshot, import_snapshot


def line(session='parent', response='main', output=10, **extra):
    return (json.dumps({'timestamp': '2026-10-20T12:00:00Z', 'sessionId': session,
        'type': 'assistant', 'uuid': response, 'cwd': 'C:/PRIVATE_PATH/project',
        'message': {'id': response, 'model': 'claude-sonnet-4-6', 'usage': {'input_tokens': 100, 'output_tokens': output},
                    'content': [{'type': 'text', 'text': 'PRIVATE_RESPONSE'}]}, **extra}) + '\n').encode()


def total(store):
    return dashboard(store, {'provider': 'claude_code'})['summary']['total_tokens']


def report(store):
    with store.connect() as db:
        return status(db)


def groups(store):
    with store.connect() as db:
        return read(db)


def legacy_resolve(event, path, previous=None):
    child = Path(path).parent.name == 'subagents'
    sid = Path(path).stem if child else event.get('sessionId')
    return {'id': 'claude_code:' + sid, 'suffix': sid,
            'agent_id': Path(path).stem if child else None, 'session_id': event['sessionId'],
            'parent_session_id': 'claude_code:' + event['sessionId'] if child else None,
            'session_source': 'spawned_subagent' if child else 'top_level'}


def old_index(tmp_path, monkeypatch, fixtures=None):
    root = tmp_path / 'projects'
    root.mkdir(parents=True)
    store = Store(tmp_path / 'data')
    store.set_setting('timezone', 'UTC')
    source = store.add_source(root, provider='claude_code')
    fixtures = fixtures or [('parent.jsonl', line()), ('agent-a.jsonl', line(response='child', output=20, agentId='a', isSidechain=True))]
    with monkeypatch.context() as patch:
        patch.setattr(claude_identity, 'resolve', legacy_resolve)
        for relative, raw in fixtures:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            parser = TranscriptParser('claude_code', path=path)
            offset = 0
            for record in raw.splitlines(keepends=True):
                offset += len(record)
                parser.consume(record, offset)
            parser.state.pop('claude_identity', None)
            parser.state['version'] = 3
            fact = parser.fact()
            stat = path.stat()
            with store.connect() as db:
                db.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', (source, str(path), offset, stat.st_mtime_ns,
                           stat.st_size, anchor(path, offset), pack(parser.state), 3))
                store.put_candidate(db, source, fact, 3, path)
                store.choose_canonical(db, fact['segment_id'])
    rebuild_projection(store)
    return store, root, source


@pytest.mark.parametrize('layout', ['agent-a.jsonl', 'parent/subagents/agent-a.jsonl',
                                    'parent/subagents/workflows/wf-one/agent-a.jsonl'])
def test_layouts_and_portable_identity(tmp_path, layout):
    identities = []
    for computer in ('windows', 'mac'):
        store = Store(tmp_path / computer / 'data')
        root = tmp_path / computer / 'projects'
        root.mkdir()
        store.add_source(root, provider='claude_code')
        (root / 'parent.jsonl').write_bytes(line())
        path = root / layout
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(line(response='child', output=20, isSidechain=True, agentId='a'))
        assert refresh(store)['errors'] == 0
        assert total(store) == 230
        assert groups(store) == []
        with store.connect() as db:
            child = db.execute("SELECT session_id,parent_id FROM canonical WHERE category='spawned_subagent'").fetchone()
            identities.append(tuple(child))
        assert refresh(store)['bytes_read'] == 0
    assert identities[0] == identities[1]
    assert identities[0][1] == 'claude_code:parent'


def test_parent_scoping_streaming_and_copied_responses(tmp_path):
    store = Store(tmp_path / 'data')
    root = tmp_path / 'projects'
    root.mkdir()
    store.add_source(root, provider='claude_code')
    for parent in ('one', 'two'):
        path = root / parent / 'subagents/agent-a.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(line(parent, parent, 5, agentId='a', isSidechain=True) + line(parent, parent, 20, agentId='a', isSidechain=True))
    (root / 'copy.jsonl').write_bytes((root / 'one/subagents/agent-a.jsonl').read_bytes())
    refresh(store)
    assert total(store) == 240
    assert not groups(store)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM canonical').fetchone()[0] == 2
    assert adapter('claude_code').version == 4
    assert adapter('antigravity').version == 3


@pytest.mark.parametrize('extra', [{'sessionId': None, 'agentId': None, 'isSidechain': True},
                                  {'agentId': 'different', 'isSidechain': True},
                                  {'isSidechain': False, 'agentId': 'a'},
                                  {'sessionId': 'different-parent', 'isSidechain': True, 'agentId': 'a'}])
def test_contradictory_identity_never_combines(tmp_path, extra):
    parser = TranscriptParser('claude_code', path=tmp_path / 'parent/subagents/agent-a.jsonl')
    if extra == {'sessionId': None, 'agentId': None, 'isSidechain': True}:
        parser = TranscriptParser('claude_code', path=tmp_path / 'unknown.jsonl')
    with pytest.raises(claude_identity.IdentityError):
        parser.consume(line(**extra), 100)


def test_mixed_identity_append_keeps_accepted_usage(tmp_path):
    store = Store(tmp_path / 'data')
    root = tmp_path / 'projects'
    root.mkdir()
    store.add_source(root, provider='claude_code')
    path = root / 'parent.jsonl'
    path.write_bytes(line())
    refresh(store)
    path.write_bytes(path.read_bytes() + line('different', 'new'))
    assert refresh(store)['errors'] == 1
    assert total(store) == 110
    assert report(store)['identity_issues'] == 1
    assert groups(store)[0]['reason_code'] == 'claude_identity_unverified'


@pytest.mark.parametrize('layout', ['agent-a.jsonl', 'parent/subagents/agent-a.jsonl',
                                    'parent/subagents/workflows/wf-one/agent-a.jsonl'])
def test_existing_conflicts_recover_without_ghost_parent(tmp_path, monkeypatch, layout):
    store, root, source = old_index(tmp_path, monkeypatch, [('parent.jsonl', line()),
        (layout, line(response='child', output=20, agentId='a', isSidechain=True))])
    exporter = store.setting('exporter_id')
    store.set_setting('export_revision', 12)
    refresh(store)
    assert total(store) == 230
    assert not groups(store)
    assert report(store)['state'] == 'complete'
    assert store.setting('exporter_id') == exporter and store.setting('export_revision') == 12
    backup = store.directory / 'insights.before-claude-identity-v1.sqlite3'
    assert backup.exists()
    backup_hash = hashlib.sha256(backup.read_bytes()).digest()
    assert refresh(Store(store.directory))['bytes_read'] == 0
    assert hashlib.sha256(backup.read_bytes()).digest() == backup_hash
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM canonical').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM files WHERE parser_version=4').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM claude_recovery_stage').fetchone()[0] == 0
        assert b'PRIVATE_RESPONSE' not in b''.join(r[0] for r in db.execute('SELECT state FROM files'))


def test_saved_choice_on_false_collision_is_archived(tmp_path, monkeypatch):
    store, _, source = old_index(tmp_path, monkeypatch)
    group = groups(store)[0]
    resolve(store, {'id': group['id'], 'revision': group['revision'], 'selected': group['versions'][0]['id']})
    refresh(store)
    assert total(store) == 230 and not groups(store)
    assert report(store)['reopened_choices'] == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM claude_recovery_choices').fetchone()[0] == 1


def test_cancellation_and_restart_resume_staged_files(tmp_path, monkeypatch):
    store, root, _ = old_index(tmp_path, monkeypatch)
    before = total(store)
    cancel = threading.Event()
    def progress(value):
        if value.get('files') == 1:
            cancel.set()
    assert refresh(store, progress=progress, cancel=cancel)['cancelled']
    assert total(store) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM claude_recovery_stage').fetchone()[0] == 1
    cancel.clear()
    refresh(Store(store.directory), cancel=cancel)
    assert total(store) == 230 and report(store)['state'] == 'complete'


def test_failed_publish_rolls_back_then_retries(tmp_path, monkeypatch):
    from codex_insights import projection
    store, _, _ = old_index(tmp_path, monkeypatch)
    before = total(store)
    with monkeypatch.context() as patch:
        patch.setattr(projection, 'project_segments', lambda *_: (_ for _ in ()).throw(RuntimeError('synthetic publication failure')))
        with pytest.raises(RuntimeError, match='publication'):
            refresh(store)
    assert total(store) == before
    refresh(Store(store.directory))
    assert total(store) == 230


def test_failed_backup_prevents_staging(tmp_path, monkeypatch):
    from codex_insights import claude_recovery
    store, _, _ = old_index(tmp_path, monkeypatch)
    before = total(store)
    monkeypatch.setattr(claude_recovery, 'backup', lambda *_: (_ for _ in ()).throw(OSError('synthetic disk full')))
    with pytest.raises(OSError, match='disk full'):
        refresh(store)
    assert total(store) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM claude_recovery_stage').fetchone()[0] == 0


def test_offline_cached_agents_recover_but_remain_pending(tmp_path, monkeypatch):
    store, root, _ = old_index(tmp_path, monkeypatch)
    moved = root.with_name('disconnected')
    root.rename(moved)
    refresh(store)
    assert total(store) == 230
    assert report(store)['state'] == 'awaiting_verification'
    moved.rename(root)
    refresh(store)
    assert total(store) == 230 and not groups(store)


def test_large_counters_and_real_disagreement_survive(tmp_path, monkeypatch):
    store, _, _ = old_index(tmp_path, monkeypatch, [('one.jsonl', line(output=3_000_000_000)),
        ('copy.jsonl', line(output=3_000_000_001))])
    refresh(store)
    group = groups(store)[0]
    assert group['state'] == 'needs_review'
    assert group['alternative_only_tokens'] == 0
    assert group['disputed_responses'] == 1
    assert total(store) in (3_000_000_100, 3_000_000_101)


def test_corrected_export_replaces_v5_and_is_idempotent(tmp_path, monkeypatch):
    import zipfile
    from codex_insights.codec import loads, dumps
    store, _, _ = old_index(tmp_path / 'mac', monkeypatch)
    snapshot = tmp_path / 'mac.codex-insights'
    export_snapshot(store, snapshot)
    with zipfile.ZipFile(snapshot) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        values = [loads(raw)['accepted'] for raw in archive.read('facts.jsonl').decode().splitlines()]
    # v5 did not carry normalized proofs or rejected alternatives.
    for f in values:
        f.pop('record_hash', None)
        f.pop('record_proofs', None)
    raw = ''.join(dumps(f) + '\n' for f in values).encode()
    manifest.update(format_version=5, facts_sha256=hashlib.sha256(raw).hexdigest())
    with zipfile.ZipFile(snapshot, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('facts.jsonl', raw)
    windows = Store(tmp_path / 'windows')
    import_snapshot(windows, snapshot)
    assert report(windows)['state'] == 'awaiting_verification'
    export_usage(store, snapshot)
    import_snapshot(windows, snapshot)
    assert total(windows) == total(store) == 230
    assert not groups(windows)
    assert import_snapshot(windows, snapshot)['status'] == 'unchanged'
    assert report(windows)['state'] == 'complete'


def test_readonly_diagnostics_does_not_construct_engine(tmp_path, monkeypatch, capsys):
    from codex_insights import cli
    store, _, _ = old_index(tmp_path, monkeypatch)
    before = hashlib.sha256(store.path.read_bytes()).digest()
    monkeypatch.setattr(cli, 'Engine', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('Engine constructed')))
    assert cli.main(['--data-dir', str(store.directory), 'diagnose-history']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['conflicts_by_provider'] == {'claude_code': 1}
    assert hashlib.sha256(store.path.read_bytes()).digest() == before
    assert not (store.directory / 'insights.before-claude-identity-v1.sqlite3').exists()


def test_pre_review_checkpoints_recover_rejected_agent(tmp_path, monkeypatch):
    store, _, _ = old_index(tmp_path, monkeypatch)
    with store.connect() as db:
        db.execute("DELETE FROM settings WHERE key='copy_history_version'")
        db.execute('UPDATE candidates SET same_source_conflict=1')
        for table in ('history_variants', 'variant_locations', 'history_pending'):
            db.execute('DELETE FROM ' + table)
    upgraded = Store(store.directory)
    refresh(upgraded)
    assert total(upgraded) == 230 and not groups(upgraded)
    assert (store.directory / 'insights.before-copy-review.sqlite3').exists()
    assert (store.directory / 'insights.before-claude-identity-v1.sqlite3').exists()


def test_same_filename_old_agents_under_distinct_parents(tmp_path, monkeypatch):
    store, _, _ = old_index(tmp_path, monkeypatch, [
        ('one/subagents/agent-a.jsonl', line('one', 'first', 10, agentId='a', isSidechain=True)),
        ('two/subagents/agent-a.jsonl', line('two', 'second', 20, agentId='a', isSidechain=True))])
    refresh(store)
    assert total(store) == 230 and not groups(store)
    assert report(store)['newly_included_responses'] == 1


def test_true_agent_branch_choice_follows_one_to_one_identity_change(tmp_path, monkeypatch):
    store, _, _ = old_index(tmp_path, monkeypatch, [
        ('first/parent/subagents/agent-a.jsonl', line(response='child', output=10, agentId='a', isSidechain=True)),
        ('copy/parent/subagents/agent-a.jsonl', line(response='child', output=20, agentId='a', isSidechain=True))])
    group = groups(store)[0]
    chosen = next(v for v in group['versions'] if v['recorded_tokens'] == 120)
    resolve(store, {'id': group['id'], 'revision': group['revision'], 'selected': chosen['id']})
    refresh(store)
    assert total(store) == 120
    assert groups(store)[0]['state'] == 'manually_resolved'
    assert report(store)['reopened_choices'] == 0


def test_staged_evidence_survives_file_loss_between_runs(tmp_path, monkeypatch):
    store, root, _ = old_index(tmp_path, monkeypatch)
    path = root / 'agent-a.jsonl'
    path.write_bytes(path.read_bytes() + line(response='new-child', output=30, agentId='a', isSidechain=True))
    cancel = threading.Event()
    def progress(value):
        if value.get('files') == 1:
            cancel.set()
    refresh(store, progress=progress, cancel=cancel)
    path.unlink()
    cancel.clear()
    refresh(Store(store.directory), cancel=cancel)
    assert total(store) == 360  # parent 110, original child 120, staged child 130
    assert report(store)['state'] == 'awaiting_verification'


def test_disabled_source_waits_until_enabled(tmp_path, monkeypatch):
    store, _, sid = old_index(tmp_path, monkeypatch)
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0 WHERE id=?', (sid,))
    rebuild_projection(store)
    refresh(store)
    assert not (store.directory / 'insights.before-claude-identity-v1.sqlite3').exists()
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=1 WHERE id=?', (sid,))
    rebuild_projection(store)
    refresh(store)
    assert total(store) == 230


def test_recovery_preserves_logged_pricing_and_filters(tmp_path, monkeypatch):
    from test_claude_cost_history import line as priced_line
    store, _, _ = old_index(tmp_path, monkeypatch, [
        ('main.jsonl', priced_line(speed='fast', inference_geo='us', service_tier='standard')),
        ('agent-a.jsonl', priced_line(mid='child', speed='fast', inference_geo='us', service_tier='standard'))])
    refresh(store)
    data = dashboard(store, {'provider': 'claude_code', 'model': 'claude-opus-5-5'})
    assert data['summary']['cost'] == 34.5
    assert data['summary']['total_tokens'] == 3_200_000
    snapshot = tmp_path / 'priced.codex-insights'
    export_usage(store, snapshot)
    receiver = Store(tmp_path / 'receiver')
    import_snapshot(receiver, snapshot)
    assert dashboard(receiver, {'provider': 'claude_code'})['usage_metrics'] == data['usage_metrics']


def test_catalog_recovery_reports_progress_and_reads_once(tmp_path, monkeypatch):
    fixtures = []
    for index in range(64):
        parent = 'parent-' + str(index)
        fixtures += [(parent + '/main.jsonl', line(parent, 'main-' + str(index))),
                     (parent + '/agent-a.jsonl', line(parent, 'child-' + str(index), 20, agentId='a', isSidechain=True))]
    store, _, _ = old_index(tmp_path, monkeypatch, fixtures)
    progress = []
    refresh(store, progress=progress.append)
    assert total(store) == 64 * 230
    assert len([p for p in progress if p.get('phase') == 'Recovering Claude history']) == 128
    assert refresh(Store(store.directory))['bytes_read'] == 0


def test_readonly_launcher_creates_no_files_in_index(tmp_path, monkeypatch, capsys):
    from codex_insights.launcher import launch
    store, _, _ = old_index(tmp_path, monkeypatch)
    before = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in store.directory.iterdir() if p.is_file()}
    assert launch(['--data-dir', str(store.directory), 'diagnose-history']) == 0
    capsys.readouterr()
    assert {p.name: hashlib.sha256(p.read_bytes()).digest() for p in store.directory.iterdir() if p.is_file()} == before


def test_readonly_audit_reads_committed_wal_without_touching_sidecars(tmp_path, monkeypatch):
    from codex_insights.history_diagnostics import diagnose
    store, _, _ = old_index(tmp_path, monkeypatch)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('audit-wal-test','1')")
        db.commit()
        before = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in store.directory.iterdir() if p.is_file()}
        assert diagnose(store.directory)['conflicts_by_provider'] == {'claude_code': 1}
        after = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in store.directory.iterdir() if p.is_file()}
        assert after == before


def test_metadata_only_agent_envelopes_keep_identity_on_later_system_records(tmp_path):
    parser = TranscriptParser('claude_code', path=tmp_path / 'copied.jsonl')
    raw = line(response='child', agentId='a', isSidechain=True)
    parser.consume(raw, len(raw))
    system = (json.dumps({'timestamp': '2026-10-20T12:00:01Z', 'type': 'system', 'sessionId': 'parent'}) + '\n').encode()
    parser.consume(system, len(raw + system))
    assert parser.fact()['session_source'] == 'spawned_subagent'
    assert parser.fact()['parent_session_id'] == 'claude_code:parent'


def test_corrected_import_archives_local_choice_between_parent_and_agent(tmp_path, monkeypatch):
    mac, _, _ = old_index(tmp_path / 'mac', monkeypatch)
    snapshot = tmp_path / 'mac.codex-insights'
    export_snapshot(mac, snapshot)
    windows = Store(tmp_path / 'windows')
    import_snapshot(windows, snapshot)
    group = groups(windows)[0]
    resolve(windows, {'id': group['id'], 'revision': group['revision'], 'selected': group['versions'][0]['id']})
    export_usage(mac, snapshot)
    import_snapshot(windows, snapshot)
    assert total(windows) == 230 and not groups(windows)
    assert report(windows)['reopened_choices'] == 1


def test_legacy_import_failure_rolls_back_snapshot_replacement(tmp_path, monkeypatch):
    from codex_insights import claude_recovery_publish
    mac, _, _ = old_index(tmp_path / 'mac', monkeypatch, [
        ('one/subagents/agent-a.jsonl', line('one', 'first', agentId='a', isSidechain=True)),
        ('two/subagents/agent-a.jsonl', line('two', 'second', agentId='a', isSidechain=True))])
    snapshot = tmp_path / 'mac.codex-insights'
    export_snapshot(mac, snapshot)
    windows = Store(tmp_path / 'windows')
    monkeypatch.setattr(claude_recovery_publish, 'publish', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('synthetic imported recovery failure')))
    with pytest.raises(RuntimeError, match='imported recovery'):
        import_snapshot(windows, snapshot)
    assert total(windows) == 0
    assert windows.sources() == []


def test_legacy_import_backup_failure_does_not_replace_snapshot(tmp_path, monkeypatch):
    from codex_insights import claude_recovery_store
    mac, _, _ = old_index(tmp_path / 'mac', monkeypatch, [
        ('one/subagents/agent-a.jsonl', line('one', 'first', agentId='a', isSidechain=True))])
    snapshot = tmp_path / 'mac.codex-insights'
    export_snapshot(mac, snapshot)
    windows = Store(tmp_path / 'windows')
    monkeypatch.setattr(claude_recovery_store, 'backup', lambda *_: (_ for _ in ()).throw(OSError('synthetic backup failure')))
    with pytest.raises(OSError, match='backup failure'):
        import_snapshot(windows, snapshot)
    assert windows.sources() == []
