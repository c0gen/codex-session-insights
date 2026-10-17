"""Public step logs, rewritten histories, private metadata and portable coverage."""
import json
import sys
import zipfile
from datetime import datetime, timezone

import pytest

from codex_insights.codec import pack, unpack
from codex_insights.ingestion import refresh
from codex_insights.providers import adapter
from codex_insights.providers.antigravity import AntigravityParser
from codex_insights.providers.bridge import receive
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot, validate_fact

NOW = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)


def step(index=1, **overrides):
    return {"created_at": NOW.isoformat(), "step_index": index, "source": "main",
            "type": "PLANNER_RESPONSE", "status": "DONE", "input_tokens": 10,
            "cache_read_tokens": 100, "output_tokens": 5, "content": "PRIVATE_TEXT", **overrides}


def content(*events):
    return b''.join((json.dumps(e) + '\n').encode() for e in events)


def setup(tmp_path):
    store = Store(tmp_path / 'data')
    root = tmp_path / 'brain'
    path = root / 'conversation/.system_generated/logs/transcript.jsonl'
    path.parent.mkdir(parents=True)
    store.add_source(root, provider='antigravity')
    return store, path


def test_native_steps_deduplicate_and_preserve_unknown_components(tmp_path):
    path = tmp_path / 'brain/conversation/.system_generated/logs/transcript.jsonl'
    parser = AntigravityParser(path=path)
    offset = 0
    for event in (step(0, type='USER_INPUT'), step(), step(), step(1, output_tokens=7)):
        raw = content(event); offset += len(raw); parser.consume(raw, offset)
    fact = parser.fact()
    # USER_INPUT counters are retained when explicitly present too.
    assert len(fact['raw_token_trace']) == 2
    assert fact['raw_token_trace'][1]['last_usage']['total_tokens'] == 117
    usage = fact['raw_token_trace'][1]['last_usage']
    assert usage['input_tokens'] == 110 and usage['cached_input_tokens'] == 100
    assert usage['cache_write_input_tokens'] is None and usage['reasoning_output_tokens'] is None
    assert len(fact['messages']) == 2
    assert 'PRIVATE_TEXT' not in str(unpack(pack(fact)))
    validate_fact(fact)
    with pytest.raises(ValueError, match='v4'):
        validate_fact(fact, 3)


def test_partial_zero_invalid_and_failed_usage(tmp_path):
    store, path = setup(tmp_path)
    path.write_bytes(content(step(input_tokens=0, cache_read_tokens=0, output_tokens=0)))
    refresh(store)
    data = dashboard(store, {'provider': 'antigravity'})
    assert data['summary']['analyzed_tokens'] == 0
    assert data['coverage']['tokens']['metrics']['writes']['state'] == 'unavailable'
    path.write_bytes(content(step(1), step(2, input_tokens=None, cache_read_tokens=None, status='ERROR'), step(3, input_tokens=True)))
    refresh(store)
    data = dashboard(store)
    assert data['summary']['total_tokens'] == 115
    assert data['summary']['output_tokens'] == 15
    assert data['coverage']['tokens']['state'] == 'partial'


def test_rewritten_incomplete_copied_and_reparsed_histories(tmp_path):
    store, path = setup(tmp_path)
    path.write_bytes(content(step()))
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 115
    assert refresh(store)['bytes_read'] == 0
    path.write_bytes(content(step(output_tokens=7), step(2)) + b'{"created_at":')
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 232
    # Compaction retains prior recorded steps and only adds the newly observed step.
    path.write_bytes(content(step(3)))
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 347
    refresh(store, rebuild=True)
    assert dashboard(store)['summary']['total_tokens'] == 347
    copied = tmp_path / 'copy'
    copy_path = copied / 'conversation/.system_generated/logs/transcript.jsonl'
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(content(step(1, output_tokens=7), step(2), step(3)))
    store.add_source(copied, provider='antigravity')
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 347


def test_hook_metadata_and_v4_private_transfer(tmp_path):
    store, path = setup(tmp_path)
    receive(store.directory, 'antigravity', 'hook', {'conversationId': 'conversation',
        'transcriptPath': str(path), 'workspacePaths': ['C:/private/project'], 'modelName': 'unknown-model'}, 'PostInvocation', NOW)
    path.write_bytes(content(step()))
    refresh(store)
    data = dashboard(store)
    assert data['summary']['total_tokens'] == 115
    assert 'unknown-model' in data['options']['models']
    archive = tmp_path / 'usage.codex-insights'
    export_snapshot(store, archive)
    with zipfile.ZipFile(archive) as bundle:
        raw = bundle.read('facts.jsonl')
        assert json.loads(bundle.read('manifest.json'))['format_version'] == 5
        assert all(value not in raw for value in (b'PRIVATE_TEXT', b'C:/private', b'transcriptPath', b'workspacePaths'))
    target = Store(tmp_path / 'imported')
    import_snapshot(target, archive)
    assert dashboard(target)['summary']['total_tokens'] == 115
    assert dashboard(target)['coverage']['tokens']['metrics']['writes']['state'] == 'unavailable'


def test_legacy_collection_is_disabled_at_all_entrypoints(tmp_path, monkeypatch, capsys):
    from codex_insights.cli import main
    from codex_insights.providers.legacy.keys import reader_key
    from codex_insights.providers.legacy.reader import SnapshotReader, census
    from codex_insights.providers.legacy.setup import LegacySources
    from codex_insights.providers.legacy.discovery import LegacyError
    from codex_insights.service import Engine
    assert census(tmp_path, tmp_path)['diagnostic'] == 'legacy_collection_disabled'
    with pytest.raises(LegacyError, match='disabled'):
        with reader_key(tmp_path):
            pytest.fail('keys must not be read')
    with pytest.raises(LegacyError, match='disabled'):
        with SnapshotReader(tmp_path, tmp_path):
            pytest.fail('archives must not be read')
    with pytest.raises(ValueError, match='disabled'):
        adapter('antigravity').snapshot_reader(tmp_path, tmp_path)
    with pytest.raises(ValueError, match='disabled'):
        LegacySources(None).preview(tmp_path, tmp_path)
    with pytest.raises(ValueError, match='disabled'):
        Store(tmp_path / 'retired-source').add_source(tmp_path, provider='antigravity', format='antigravity_legacy')
    assert main(['diagnose-antigravity-legacy', '--root', str(tmp_path), '--profile', str(tmp_path)]) == 2
    assert 'disabled' in capsys.readouterr().out
    engine = Engine(tmp_path / 'demo', demo=True)
    try:
        with pytest.raises(ValueError, match='disabled'):
            engine.call('legacy_source_preview')
        assert not engine.antigravity_usage.allowed
    finally:
        engine.close()


@pytest.mark.parametrize('transfer_version', [3, 4])
def test_retained_legacy_facts_survive_refresh_and_import(tmp_path, transfer_version):
    from codex_insights.providers.legacy.accounting import facts
    from codex_insights.providers.legacy.decoder import decode
    from codex_insights.projection import project_segments
    from legacy_fixtures import archive, ciphertext, KEY, SID
    store = Store(tmp_path / 'data')
    root = tmp_path / 'archives'; root.mkdir()
    original = root / 'original.pb'; original.write_bytes(b'original archives must remain unchanged')
    sid = store.add_source(root, provider='antigravity')
    fact = facts(decode(ciphertext(archive()), KEY, SID), SID)  # Synthetic historical fact, not a live key.
    from codex_insights.codec import digest
    fact.update(byte_count=len(ciphertext(archive())), prefix_hash=digest(['synthetic accepted archive']), proofs={})
    with store.connect() as db:
        db.execute("UPDATE sources SET format='antigravity_legacy' WHERE id=?", (sid,))
        store.put_candidate(db, sid, fact, 1002)
        store.choose_canonical(db, fact['segment_id'])
        project_segments(store, db, [fact['segment_id']])
    before = dashboard(store)['summary']
    assert before['total_tokens'] == 117
    refresh(store)
    assert dashboard(store)['summary'] == before
    assert store.sources()[0]['status'] == 'Collection disabled'
    assert original.read_bytes() == b'original archives must remain unchanged'
    archive_path = tmp_path / 'retained.codex-insights'
    export_snapshot(store, archive_path)
    if transfer_version == 3:
        with zipfile.ZipFile(archive_path) as bundle:
            manifest = json.loads(bundle.read('manifest.json')); raw = bundle.read('facts.jsonl')
        manifest['format_version'] = 3
        with zipfile.ZipFile(archive_path, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(manifest)); bundle.writestr('facts.jsonl', raw)
    imported = Store(tmp_path / 'imported')
    import_snapshot(imported, archive_path)
    assert dashboard(imported)['summary'] == before
