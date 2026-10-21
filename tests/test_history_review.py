"""Copy reconciliation, durable review, migration and portable evidence."""
import hashlib
import json
import sqlite3
import threading
import zipfile
from copy import deepcopy

import pytest

from codex_insights.codec import dumps, loads, pack, unpack
from codex_insights.copy_reconciliation import covers, variant_id
from codex_insights.history_review import read, resolve
from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.snapshot_export import export_usage
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import event, legacy_records, log, token


def formatted(raw):
    return b''.join((json.dumps(json.loads(line), sort_keys=True, separators=(',', ':')) + '\n').encode() for line in raw.splitlines())


def review(store):
    with store.connect() as db:
        return read(db)


def choose(store, group=None, selected=None, undo=False):
    group = group or review(store)[0]
    selected = selected or next(v['id'] for v in group['versions'] if v['accepted'])
    return resolve(store, {'id': group['id'], 'revision': group['revision'], 'selected': selected, 'undo': undo})


def divergent(store, root):
    (root / 'accepted.jsonl').write_bytes(log() + token(100))
    refresh(store)
    (root / 'other.jsonl').write_bytes(log() + token(900))
    refresh(store)
    return review(store)[0]


@pytest.mark.parametrize('reverse', [False, True])
def test_normalized_copies_extensions_and_incremental_refresh(indexed, reverse):
    store, root, _ = indexed
    content = log() + token(100)
    a, b = (formatted(content), content) if reverse else (content, formatted(content))
    (root / 'a.jsonl').write_bytes(a)
    refresh(store)
    with store.connect() as db:
        accepted = unpack(db.execute('SELECT fact FROM canonical').fetchone()[0])
    (root / 'b.jsonl').write_bytes(b)
    refresh(store)
    assert review(store) == []
    assert dashboard(store)['summary']['total_tokens'] == 110
    with store.connect() as db:
        # Equivalent serialization must not displace physical boundary evidence.
        assert unpack(db.execute('SELECT fact FROM canonical').fetchone()[0])['prefix_hash'] == accepted['prefix_hash']
    with (root / 'b.jsonl').open('ab') as stream:
        stream.write(formatted(token(300, 5, last=200)))
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 330
    assert review(store) == []
    restarted = Store(store.directory)
    assert refresh(restarted)['bytes_read'] == 0
    assert dashboard(restarted)['summary']['total_tokens'] == 330


@pytest.mark.parametrize('mutation', ['timestamp', 'counters', 'order', 'parent'])
def test_similar_totals_never_prove_equivalence(indexed, mutation):
    store, root, _ = indexed
    original = log() + token(100)
    records = [json.loads(line) for line in original.splitlines()]
    if mutation == 'timestamp':
        records[-1]['timestamp'] = '2026-10-01T14:01:00Z'
    elif mutation == 'counters':
        records[-1]['payload']['info']['total_token_usage']['cached_input_tokens'] = 0
    elif mutation == 'order':
        records[1], records[2] = records[2], records[1]
    else:
        records[0]['payload']['parent_thread_id'] = 'different-parent'
    (root / 'a.jsonl').write_bytes(original)
    refresh(store)
    (root / 'b.jsonl').write_bytes(b''.join((json.dumps(r) + '\n').encode() for r in records))
    refresh(store)
    assert review(store)[0]['state'] == 'needs_review'
    assert len(review(store)[0]['versions']) == 2


def test_selection_restart_extension_reopen_undo_and_stale_evidence(indexed):
    store, root, _ = indexed
    group = divergent(store, root)
    rejected = next(v['id'] for v in group['versions'] if not v['accepted'])
    choose(store, group, rejected)
    assert dashboard(store)['summary']['total_tokens'] == 990
    assert dashboard(store)['coverage']['conflicts'] == 0
    assert review(store)[0]['state'] == 'manually_resolved'
    restarted = Store(store.directory)
    refresh(restarted, rebuild=True)
    rebuild_projection(restarted)
    assert review(restarted)[0]['state'] == 'manually_resolved'
    with (root / 'other.jsonl').open('ab') as stream:
        stream.write(token(1000, 5, last=100))
    refresh(restarted)
    assert review(restarted)[0]['state'] == 'manually_resolved'
    assert dashboard(restarted)['summary']['total_tokens'] == 1100
    stale = review(restarted)[0]
    with (root / 'accepted.jsonl').open('ab') as stream:
        stream.write(token(300, 5, last=200))
    refresh(restarted)
    assert review(restarted)[0]['state'] == 'needs_review'
    with pytest.raises(ValueError, match='History changed'):
        choose(restarted, stale)
    choose(restarted)
    assert review(restarted)[0]['state'] == 'manually_resolved'
    choose(restarted, undo=True)
    assert review(restarted)[0]['state'] == 'needs_review'
    # Removing a rejected original does not erase potentially excluded history.
    (root / 'accepted.jsonl').unlink()
    refresh(restarted, rebuild=True)
    assert review(restarted)[0]['state'] == 'needs_review'


def test_snapshot_alternatives_choices_and_no_import_reexport(indexed, tmp_path):
    store, root, _ = indexed
    divergent(store, root)
    snapshot = tmp_path / 'usage.codex-insights'
    result = export_usage(store, snapshot)
    assert result['unresolved_histories'] == 1
    assert 'alternative' in result['warnings'][0]
    with zipfile.ZipFile(snapshot) as archive:
        raw = archive.read('facts.jsonl')
        assert b'PRIVATE' not in raw and str(root).encode() not in raw
        value = loads(raw.decode())
        assert len(value['alternatives']) == 1
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    assert review(target)[0]['state'] == 'needs_review'
    assert dashboard(target)['summary']['total_tokens'] == 110
    assert len(review(target)[0]['versions']) == 2
    assert all(not v['locations'] for v in review(target)[0]['versions'])
    group = review(store)[0]
    choose(store, group, next(v['id'] for v in group['versions'] if not v['accepted']))
    export_snapshot(store, snapshot)
    import_snapshot(target, snapshot)
    assert review(target)[0]['state'] == 'manually_resolved'
    assert dashboard(target)['summary']['total_tokens'] == 990
    # A local choice survives a newer snapshot from the same exporter.
    choose(target, undo=True)
    choose(target, selected=next(v['id'] for v in review(target)[0]['versions'] if not v['accepted']))
    export_snapshot(store, snapshot)
    import_snapshot(target, snapshot)
    assert dashboard(target)['summary']['total_tokens'] == 110
    outbound = tmp_path / 'remote-only.codex-insights'
    assert export_snapshot(target, outbound)['sessions'] == 0


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5])
def test_pre_v6_import_compatibility(indexed, tmp_path, version):
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100))
    refresh(store)
    snapshot = tmp_path / 'usage.codex-insights'
    export_snapshot(store, snapshot)
    with zipfile.ZipFile(snapshot) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        raw = legacy_records(archive.read('facts.jsonl'))
    manifest.update(format_version=version, facts_sha256=hashlib.sha256(raw).hexdigest())
    with zipfile.ZipFile(snapshot, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('facts.jsonl', raw)
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    assert dashboard(target)['summary']['total_tokens'] == 110


def simulate_old_index(store, conflict=True):
    with store.connect() as db:
        db.execute("DELETE FROM settings WHERE key='copy_history_version'")
        db.execute("UPDATE settings SET value='5' WHERE key='projection_version'")
        db.execute('UPDATE candidates SET same_source_conflict=?', (int(conflict),))
        for table in ('history_variants', 'variant_locations', 'history_choices', 'history_pending'):
            db.execute('DELETE FROM ' + table)
        for row in db.execute('SELECT source_id,path,state FROM files').fetchall():
            state = unpack(row['state'])
            state.pop('record_hash', None)
            state.pop('record_proofs', None)
            state['version'] = 3
            db.execute('UPDATE files SET state=?,parser_version=3 WHERE source_id=? AND path=?',
                       (pack(state), row['source_id'], row['path']))
        for table in ('candidates', 'canonical'):
            for row in db.execute('SELECT rowid,fact FROM ' + table).fetchall():
                fact = unpack(row['fact'])
                fact.pop('record_hash', None)
                fact.pop('record_proofs', None)
                db.execute('UPDATE ' + table + ' SET fact=? WHERE rowid=?', (pack(fact), row['rowid']))


def test_migration_backup_recovers_alternatives_and_normalized_scan(indexed):
    store, root, _ = indexed
    content = log() + token(100)
    (root / 'a.jsonl').write_bytes(content)
    (root / 'b.jsonl').write_bytes(formatted(content))
    refresh(store)
    exporter = store.setting('exporter_id')
    store.set_setting('export_revision', 17)
    simulate_old_index(store)
    upgraded = Store(store.directory)
    backup = store.directory / 'insights.before-copy-review.sqlite3'
    assert backup.is_file()
    before = backup.read_bytes()
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM settings WHERE key='copy_history_version'").fetchone() is None
    assert refresh(upgraded)['changed_files'] == 2
    assert review(upgraded) == []
    assert upgraded.setting('exporter_id') == exporter
    assert upgraded.setting('export_revision') == 17
    assert refresh(Store(store.directory))['bytes_read'] == 0
    assert backup.read_bytes() == before


def test_migration_missing_evidence_stays_awaiting_and_manual_choice(indexed, tmp_path):
    store, root, sid = indexed
    (root / 'accepted.jsonl').write_bytes(log() + token(100))
    refresh(store)
    simulate_old_index(store)
    with store.connect() as db:
        db.execute('UPDATE sources SET root=? WHERE id=?', (str(tmp_path / 'offline'), sid))
    upgraded = Store(store.directory)
    refresh(upgraded)
    assert review(upgraded)[0]['state'] == 'awaiting_verification'
    assert dashboard(upgraded)['summary']['total_tokens'] == 110
    choose(upgraded)
    assert review(upgraded)[0]['state'] == 'manually_resolved'
    choose(upgraded, undo=True)
    assert review(upgraded)[0]['state'] == 'awaiting_verification'
    upgraded.forget_source(sid)
    rebuild_projection(upgraded)
    assert review(upgraded) == []


def test_boundary_evidence_from_equivalent_copy_survives_transfer(indexed, tmp_path):
    store, root, _ = indexed
    raw = log('parent') + token(100)
    (root / 'parent-a.jsonl').write_bytes(raw)
    refresh(store)
    differently_formatted = formatted(raw)
    (root / 'parent-b.jsonl').write_bytes(differently_formatted)
    base = {'thread_id': 'parent', 'end_byte_offset': len(differently_formatted), 'end_ordinal_exclusive': 4}
    (root / 'child.jsonl').write_bytes(event('session_meta', {'id': 'child', 'forked_from_id': 'parent', 'history_base': base}, 5)
                                     + token(150, 6, last=50))
    refresh(store)
    snapshot = tmp_path / 'usage.codex-insights'
    export_snapshot(store, snapshot)
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    with target.connect() as db:
        diag = json.loads(db.execute("SELECT diagnostic FROM canonical WHERE session_id='child'").fetchone()[0])
    assert diag['accounting'] == 'bounded_paginated_history'
    assert dashboard(target)['summary']['total_tokens'] == 165


def test_cancelled_scan_retains_existing_choice(indexed):
    store, root, _ = indexed
    divergent(store, root)
    choose(store)
    before = review(store)[0]
    cancel = threading.Event()
    cancel.set()
    assert refresh(store, cancel=cancel)['cancelled']
    assert review(store)[0] == before


def test_import_rejects_private_alternatives_atomically(indexed, tmp_path):
    store, root, _ = indexed
    divergent(store, root)
    snapshot = tmp_path / 'usage.codex-insights'
    export_snapshot(store, snapshot)
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    before = review(target)
    with zipfile.ZipFile(snapshot) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        value = loads(archive.read('facts.jsonl').decode())
    value['alternatives'][0]['prompt'] = 'PRIVATE'
    raw = (dumps(value) + '\n').encode()
    manifest.update(revision=manifest['revision'] + 1, facts_sha256=hashlib.sha256(raw).hexdigest())
    with zipfile.ZipFile(snapshot, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('facts.jsonl', raw)
    with pytest.raises(ValueError):
        import_snapshot(target, snapshot)
    assert review(target) == before


def test_accounting_format_choice_and_transfer_without_legacy_collection(tmp_path):
    from codex_insights.providers.legacy.accounting import facts
    from codex_insights.providers.legacy.decoder import decode
    from codex_insights.projection import project_segments
    from codex_insights.codec import digest
    from legacy_fixtures import archive, ciphertext, KEY, SID
    from test_providers import line
    store = Store(tmp_path / 'data')
    legacy = tmp_path / 'legacy'; legacy.mkdir()
    source = store.add_source(legacy, provider='antigravity')
    fact = facts(decode(ciphertext(archive()), KEY, SID), SID)
    fact.update(byte_count=100, prefix_hash=digest(['synthetic']), proofs={})
    with store.connect() as db:
        db.execute("UPDATE sources SET format='antigravity_legacy' WHERE id=?", (source,))
        store.put_candidate(db, source, fact, 1002)
        store.choose_canonical(db, fact['segment_id'])
        project_segments(store, db, [fact['segment_id']])
    public = tmp_path / 'public'
    path = public / SID / '.system_generated/logs/transcript.jsonl'
    path.parent.mkdir(parents=True)
    path.write_bytes(line(sid=SID))
    store.add_source(public, provider='antigravity')
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 117
    group = next(g for g in review(store) if g['kind'] == 'accounting')
    choose(store, group, next(v['id'] for v in group['versions'] if v['format'] == 'Transcript history'))
    assert dashboard(store)['summary']['total_tokens'] == 160
    assert dashboard(store)['coverage']['accounting_overlaps'] == 0
    snapshot = tmp_path / 'overlap.codex-insights'
    export_snapshot(store, snapshot)
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    assert dashboard(target)['summary']['total_tokens'] == 160
    assert next(g for g in review(target) if g['kind'] == 'accounting')['state'] == 'manually_resolved'
    choose(target, next(g for g in review(target) if g['kind'] == 'accounting'), undo=True)
    assert dashboard(target)['coverage']['accounting_overlaps'] == 1
    assert dashboard(target)['summary']['total_tokens'] == 117


def test_disable_enable_sources_and_cross_source_verified_extension(indexed, tmp_path):
    store, root, sid = indexed
    divergent(store, root)
    choose(store)
    other = tmp_path / 'other'; other.mkdir()
    (other / 'long.jsonl').write_bytes(log() + token(100) + token(300, 5, last=200))
    store.add_source(other)
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 330
    assert review(store)[0]['state'] == 'manually_resolved'

    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0 WHERE id=?', (sid,))
    rebuild_projection(store)
    assert dashboard(store)['summary']['total_tokens'] == 330
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=1 WHERE id=?', (sid,))
    rebuild_projection(store)
    assert review(store)[0]['state'] == 'manually_resolved'


def test_failed_reprojection_rolls_back_selection(indexed, monkeypatch):
    import codex_insights.projection as projection
    store, root, _ = indexed
    divergent(store, root)
    before = review(store)
    tokens = dashboard(store)['summary']['total_tokens']
    def fail(*args):
        raise RuntimeError('synthetic projection failure')
    monkeypatch.setattr(projection, 'project_segments', fail)
    with pytest.raises(RuntimeError, match='synthetic'):
        choose(store)
    assert review(store) == before
    assert dashboard(store)['summary']['total_tokens'] == tokens


def test_selected_extensions_keep_choice_through_snapshot_replacement(indexed, tmp_path):
    store, root, _ = indexed
    divergent(store, root)
    choose(store)
    with (root / 'accepted.jsonl').open('ab') as stream:
        stream.write(token(300, 5, last=200))
    refresh(store)
    snapshot = tmp_path / 'extensions.codex-insights'
    export_snapshot(store, snapshot)
    target = Store(tmp_path / 'target')
    import_snapshot(target, snapshot)
    assert review(target)[0]['state'] == 'manually_resolved'
    choose(target)  # Receiver's own decision must survive exporter revisions.
    with (root / 'accepted.jsonl').open('ab') as stream:
        stream.write(token(400, 6, last=100))
    refresh(store)
    export_snapshot(store, snapshot)
    import_snapshot(target, snapshot)
    assert review(target)[0]['state'] == 'manually_resolved'
    assert dashboard(target)['summary']['total_tokens'] == 440
