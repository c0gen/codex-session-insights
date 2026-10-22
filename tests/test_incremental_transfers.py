"""Sparse imports preserve accepted rows and only recalculate proven dependencies."""
import hashlib
import json
import threading
import zipfile

import pytest

from codex_insights import projection, transfer_staging
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import log, token


def setup_archive(indexed, tmp_path, count=3):
    store, root, _ = indexed
    for index in range(count):
        (root / f'{index}.jsonl').write_bytes(log(f'chat-{index}') + token(100 + index))
    refresh(store)
    path = tmp_path / 'a.codex-insights'
    export_snapshot(store, path)
    target = Store(tmp_path / 't')
    target.set_setting('timezone', store.setting('timezone'))
    import_snapshot(target, path)
    return store, root, path, target


def rows(store):
    with store.connect() as db:
        return {r['session_id']: (r['rowid'], r['fact']) for r in db.execute('SELECT rowid,* FROM canonical')}


def test_newer_identical_snapshot_does_no_staging_or_metrics(indexed, tmp_path, monkeypatch):
    source, _, path, target = setup_archive(indexed, tmp_path)
    before = rows(target)
    revision = target.setting('data_revision')
    export_snapshot(source, path)
    monkeypatch.setattr(transfer_staging, 'prepare', lambda *_: pytest.fail('Identical snapshot must not stage'))
    result = import_snapshot(target, path)
    assert result['reused'] == 3 and result['checked'] == 3
    assert result['added'] == result['changed'] == result['removed'] == result['recalculated'] == 0
    assert rows(target) == before and target.setting('data_revision') == revision


def test_one_changed_chat_preserves_other_canonical_and_metric_rows(indexed, tmp_path, monkeypatch):
    source, root, path, target = setup_archive(indexed, tmp_path)
    before = rows(target)
    with target.connect() as db:
        metrics = [tuple(r) for r in db.execute("SELECT rowid,* FROM records WHERE session_id!='chat-1' ORDER BY event_id")]
    with (root / '1.jsonl').open('ab') as stream:
        stream.write(token(500, 8, last=399))
    refresh(source)
    export_snapshot(source, path)
    seen, reconcile = [], projection.reconcile_sessions
    def counted(facts, *args):
        seen.extend(f['id'] for f in facts)
        return reconcile(facts, *args)
    monkeypatch.setattr(projection, 'reconcile_sessions', counted)
    result = import_snapshot(target, path)
    assert result['changed'] == result['recalculated'] == 1 and result['reused'] == 2
    assert seen == ['chat-1']
    assert all(rows(target)[sid] == value for sid, value in before.items() if sid != 'chat-1')
    with target.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT rowid,* FROM records WHERE session_id!='chat-1' ORDER BY event_id")] == metrics
    assert dashboard(target)['summary'] == dashboard(source)['summary']


def test_backfill_without_archive_reuses_accepted_evidence(indexed, tmp_path, monkeypatch):
    source, _, path, target = setup_archive(indexed, tmp_path)
    with target.connect() as db:
        db.execute('DELETE FROM transfer_fingerprints')
    for saved in (target.directory / 'imports').iterdir():
        saved.unlink()
    export_snapshot(source, path)
    monkeypatch.setattr(transfer_staging, 'prepare', lambda *_: pytest.fail('Backfill must not recalculate'))
    result = import_snapshot(target, path)
    assert result['backfilled'] == 3 and result['recalculated'] == 0


def test_remove_source_segments_retains_other_copies_and_empty_source(indexed, tmp_path):
    source, root, path, target = setup_archive(indexed, tmp_path, 1)
    local = tmp_path / 'local'; local.mkdir()
    (local / 'copy.jsonl').write_bytes((root / '0.jsonl').read_bytes())
    target.add_source(local)
    refresh(target)
    (root / '0.jsonl').unlink()
    source.forget_source(source.sources()[0]['id'])
    export_snapshot(source, path)
    result = import_snapshot(target, path)
    assert result['removed'] == 1 and result['sessions'] == 0
    assert dashboard(target)['summary']['total_tokens'] == 110
    empty = Store(tmp_path / 'empty')
    assert import_snapshot(empty, path)['status'] == 'imported'
    assert len(empty.sources()) == 1


@pytest.mark.parametrize("during_units", [False, True])
def test_cancelled_calculation_leaves_accepted_source_and_metrics(indexed, tmp_path, during_units):
    source, root, path, target = setup_archive(indexed, tmp_path)
    before, revision = rows(target), target.sources()[0]['revision']
    with (root / '1.jsonl').open('ab') as stream:
        stream.write(token(500, 8, last=399))
    refresh(source); export_snapshot(source, path)
    cancel = threading.Event()
    def progress(value):
        if not during_units and value['phase'] == 'Calculating changed usage':
            cancel.set()
    def cooperate():
        import inspect
        if any(frame.function == 'prepare' and 'since' in frame.frame.f_locals for frame in inspect.stack()):
            cancel.set()
    if during_units:
        target.cooperate = cooperate
        target.maintenance_cancel = cancel
    with pytest.raises(InterruptedError):
        import_snapshot(target, path, progress, cancel)
    assert rows(target) == before and target.sources()[0]['revision'] == revision
    target.cooperate = target.maintenance_cancel = None
    assert import_snapshot(target, path)['changed'] == 1


def test_corrupt_same_revision_and_duplicate_records_are_checked(indexed, tmp_path):
    _, _, path, target = setup_archive(indexed, tmp_path, 1)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        facts = archive.read('facts.jsonl')
    bad = tmp_path / 'bad.codex-insights'
    with zipfile.ZipFile(bad, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('facts.jsonl', facts + b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        import_snapshot(target, bad)
    manifest.update(fact_count=2, facts_sha256=hashlib.sha256(facts + facts).hexdigest())
    with zipfile.ZipFile(bad, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('facts.jsonl', facts + facts)
    with pytest.raises(ValueError, match='Duplicate'):
        import_snapshot(target, bad)


def test_legacy_reordered_bucket_columns_publish_by_name(indexed, tmp_path):
    source, root, path, target = setup_archive(indexed, tmp_path)
    with target.connect() as db:
        columns = [r['name'] for r in db.execute('PRAGMA table_info(metric_buckets)')]
        reordered = columns[1:] + columns[:1]
        db.execute('ALTER TABLE metric_buckets RENAME TO old_buckets')
        db.execute('CREATE TABLE metric_buckets AS SELECT ' + ','.join(reordered) + ' FROM old_buckets')
        db.execute('DROP TABLE old_buckets')
    with (root / '1.jsonl').open('ab') as stream:
        stream.write(token(500, 8, last=399))
    refresh(source); export_snapshot(source, path)
    import_snapshot(target, path)
    expected = dashboard(source)
    actual = dashboard(target)
    for key in ('summary', 'timeline', 'models', 'projects', 'heatmap', 'tiers', 'efforts', 'agents', 'daily_sessions', 'cache_rate_timeline', 'usage_metrics'):
        assert actual[key] == expected[key], key


def test_new_live_different_session_response_claim_restages_import(tmp_path, monkeypatch):
    from test_claude_cost_history import line
    from codex_insights import transfer_publication
    remote = Store(tmp_path / 'remote')
    remote_root = tmp_path / 'rr'; remote_root.mkdir()
    remote.add_source(remote_root, provider='claude_code')
    (remote_root / 'r.jsonl').write_bytes(line(sid='remote', mid='shared-response'))
    refresh(remote)
    archive = tmp_path / 'shared.codex-insights'; export_snapshot(remote, archive)
    target = Store(tmp_path / 'target')
    local_root = tmp_path / 'lr'; local_root.mkdir()
    target.add_source(local_root, provider='claude_code')
    refresh(target)
    original, calls = transfer_publication.publish, []
    inserted = []
    def cooperate():
        import inspect
        if inserted or not any(frame.function == 'prepare' and 'since' in frame.frame.f_locals for frame in inspect.stack()):
            return
        inserted.append(1)
        (local_root / 'l.jsonl').write_bytes(line(sid='different-live-session', mid='shared-response'))
        refresh(target)
    target.cooperate = cooperate
    def concurrent(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(transfer_publication, 'publish', concurrent)
    import_snapshot(target, archive)
    assert inserted and len(calls) == 2
    before = dashboard(target)
    projection.rebuild_projection(target)
    after = dashboard(target)
    assert before['summary'] == after['summary']
    assert before['summary']['total_tokens'] == dashboard(remote)['summary']['total_tokens']


def test_newer_identical_claude_v5_never_clones_or_reconciles(tmp_path, monkeypatch):
    from test_claude_cost_history import line
    from codex_insights.codec import loads, dumps
    from codex_insights import isolated_jobs
    remote = Store(tmp_path / 'remote')
    root = tmp_path / 'claude'; root.mkdir()
    remote.add_source(root, provider='claude_code')
    (root / 'chat.jsonl').write_bytes(line())
    refresh(remote)
    archive = tmp_path / 'old.codex-insights'; export_snapshot(remote, archive)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        values = [loads(raw)['accepted'] for raw in bundle.read('facts.jsonl').splitlines()]
    for fact in values:
        fact.pop('record_hash', None); fact.pop('record_proofs', None)
    raw = ''.join(dumps(fact) + '\n' for fact in values).encode('utf-8')
    manifest.update(format_version=5, facts_sha256=hashlib.sha256(raw).hexdigest())
    def write():
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(manifest)); bundle.writestr('facts.jsonl', raw)
    write()
    target = Store(tmp_path / 'target')
    target.cooperate = lambda: None
    import_snapshot(target, archive)
    import_snapshot(target, archive)  # Learn complete accepted source input.
    manifest['revision'] += 1
    write()
    monkeypatch.setattr(isolated_jobs, 'backup', lambda *_: pytest.fail('Identical legacy archive cloned index'))
    monkeypatch.setattr(transfer_staging, 'prepare', lambda *_: pytest.fail('Identical legacy archive recalculated'))
    result = import_snapshot(target, archive)
    assert result['checked'] == result['reused'] == 1
    assert result['changed'] == result['recalculated'] == 0


def test_stale_ledger_cannot_hide_reversion_after_legacy_acceptance(indexed, tmp_path):
    from codex_insights.transfers import _legacy_import_snapshot
    source, root, path, target = setup_archive(indexed, tmp_path, 1)
    with zipfile.ZipFile(path) as archive:
        original_facts = archive.read('facts.jsonl')
        original_manifest = json.loads(archive.read('manifest.json'))
    with target.connect() as db:
        old_rows = [tuple(r) for r in db.execute('SELECT * FROM transfer_fingerprints')]
        old_meta = [tuple(r) for r in db.execute('SELECT * FROM transfer_fingerprint_sources')]
    with (root / '0.jsonl').open('ab') as stream:
        stream.write(token(300, 8, last=200))
    refresh(source); export_snapshot(source, path)
    _legacy_import_snapshot(target, path)
    assert dashboard(target)['summary']['total_tokens'] == 330
    # Simulate a ledger left by an earlier app while accepted revision advanced.
    with target.connect() as db:
        db.executemany('INSERT OR REPLACE INTO transfer_fingerprints VALUES(?,?,?,?,?,?,?,?,?,?)', old_rows)
        db.executemany('INSERT OR REPLACE INTO transfer_fingerprint_sources VALUES(?,?,?)', old_meta)
    original_manifest['revision'] = 3
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(original_manifest)); archive.writestr('facts.jsonl', original_facts)
    result = import_snapshot(target, path)
    assert result['changed'] == 1 and result['recalculated'] == 1
    assert dashboard(target)['summary']['total_tokens'] == 110


def test_rekeyed_legacy_source_empty_snapshot_retains_independent_local_copy(tmp_path, monkeypatch):
    from test_claude_identity_recovery import old_index, line
    from codex_insights.codec import loads, dumps
    remote, _, _ = old_index(tmp_path / 'mac', monkeypatch, [
        ('parent.jsonl', line()),
        ('parent/subagents/agent-a.jsonl', line(response='child', output=20, agentId='a', isSidechain=True))])
    archive = tmp_path / 'old.codex-insights'; export_snapshot(remote, archive)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        values = [loads(raw)['accepted'] for raw in bundle.read('facts.jsonl').splitlines()]
    for fact in values:
        fact.pop('record_hash', None); fact.pop('record_proofs', None)
    raw = ''.join(dumps(fact) + '\n' for fact in values).encode('utf-8')
    manifest.update(format_version=5, facts_sha256=hashlib.sha256(raw).hexdigest())
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest)); bundle.writestr('facts.jsonl', raw)
    target = Store(tmp_path / 'target'); import_snapshot(target, archive)
    import_snapshot(target, archive)  # Complete ledger retains original input IDs.
    local = tmp_path / 'local/parent/subagents'; local.mkdir(parents=True)
    (local / 'agent-a.jsonl').write_bytes(line(response='child', output=20, agentId='a', isSidechain=True))
    target.add_source(tmp_path / 'local', provider='claude_code'); refresh(target)
    assert dashboard(target)['summary']['total_tokens'] == 230
    manifest.update(revision=2, fact_count=0, facts_sha256=hashlib.sha256(b'').hexdigest())
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('manifest.json', json.dumps(manifest)); bundle.writestr('facts.jsonl', b'')
    import_snapshot(target, archive)
    assert dashboard(target)['summary']['total_tokens'] == 120
    with target.connect() as db:
        assert db.execute("SELECT count(*) FROM candidates c JOIN sources s ON s.id=c.source_id WHERE s.kind='import'").fetchone()[0] == 0
        assert not db.execute("SELECT 1 FROM claude_recovery_sources WHERE state!='complete'").fetchone()
