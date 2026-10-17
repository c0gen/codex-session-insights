"""Compatibility of already accepted legacy facts; live archive collection is retired."""
import json


import threading


import zipfile


from contextlib import contextmanager


import pytest


from codex_insights.codec import unpack


from codex_insights.ingestion import refresh


from codex_insights.providers.legacy import reader


from codex_insights.providers.legacy.accounting import facts, usage


from codex_insights.providers.legacy.decoder import decode


from codex_insights.providers.legacy.discovery import LegacyError, discover, normalize_root, read_snapshot


from codex_insights.providers.legacy.index import read_index


from codex_insights.providers.legacy.wire import WireError, message


from codex_insights.queries import dashboard


from codex_insights.storage import Store


from codex_insights.transfers import export_snapshot, import_snapshot, validate_fact


from legacy_fixtures import KEY, SECRET, SID, TID, TIME, archive, ciphertext, field, msg, profile


def test_authenticated_identity_schema_and_private_payload():
    raw = ciphertext(archive())
    decoded = decode(raw, KEY, SID)
    fact = facts(decoded, SID)
    assert fact['raw_token_trace'][0]['last_usage']['total_tokens'] == 117
    assert fact['change_events'][0]['added'] == fact['change_events'][0]['removed'] == 1
    assert SECRET not in str(fact)
    with pytest.raises(LegacyError, match='authentication_failed'):
        decode(raw[:-1] + bytes([raw[-1] ^ 1]), KEY, SID)
    with pytest.raises(LegacyError, match='authentication_failed'):
        decode(raw, b'x' * 32, SID)
    with pytest.raises(LegacyError, match='identity_mismatch'):
        decode(raw, KEY, TID)
    with pytest.raises(LegacyError, match='unsupported_trajectory_fields'):
        decode(ciphertext(archive() + field(400, 1)), KEY, SID)
    with pytest.raises(LegacyError, match='truncated_ciphertext'):
        decode(b'bad', KEY, SID)


def test_usage_missing_zero_cache_and_reasoning_subsets():
    explicit, _ = usage(field(2, 0) + field(3, 0) + field(5, 0) + field(9, 0) + field(4, 0))
    assert all(value == 0 for value in explicit.values())
    missing, _ = usage(field(2, 10) + field(3, 7))
    assert missing['input_tokens'] is None
    assert missing['output_tokens'] == 7
    assert missing['cache_write_input_tokens'] is None
    assert missing['total_tokens'] is None
    with pytest.raises(LegacyError, match='reasoning_subset'):
        usage(field(3, 7) + field(9, 8))
    with pytest.raises(LegacyError, match='output_breakdown'):
        usage(field(3, 7) + field(9, 2) + field(10, 2))


def test_failed_invocation_counts_usage_but_not_edits():
    fact = facts(decode(ciphertext(archive(failed=True)), KEY, SID), SID)
    assert fact['raw_token_trace'][0]['last_usage']['total_tokens'] == 117
    assert fact['change_events'][0]['outcome'] == 'failed'
    assert fact['change_events'][0]['added'] == 0


def test_repeated_response_snapshots_are_counted_once():
    fact = facts(decode(ciphertext(archive(repeated=True)), KEY, SID), SID)
    assert len(fact['raw_token_trace']) == 1


def test_only_dated_proven_zero_cache_requests_can_be_priced():
    from codex_insights.providers.legacy.pricing import estimate
    fact = facts(decode(ciphertext(archive(reads=0)),KEY,SID),SID)
    item = fact['raw_token_trace'][0]
    item['usage'] = item['last_usage']
    assert estimate(item)['usd'] == pytest.approx(0.0000038)
    item['usage']['cache_write_input_tokens'] = None
    assert estimate(item) is None


def test_unknown_reader_version_stops_before_key_extraction(monkeypatch):
    from codex_insights.providers.legacy.keys import reader_key
    with pytest.raises(LegacyError, match='legacy_collection_disabled'):
        with reader_key():
            pytest.fail('retired key extraction must never run')


@pytest.mark.parametrize('version',[1,2])
def test_prior_transfer_versions_remain_accepted(tmp_path, version):
    from conftest import log, token
    store = Store(tmp_path / 'old-local')
    root = tmp_path / 'codex'
    root.mkdir()
    (root / 'chat.jsonl').write_bytes(log() + token(10))
    store.add_source(root)
    refresh(store)
    snapshot = tmp_path / 'new.codex-insights'
    export_snapshot(store,snapshot)
    with zipfile.ZipFile(snapshot) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        content = bundle.read('facts.jsonl')
    manifest['format_version'] = version
    old = tmp_path / 'old.codex-insights'
    with zipfile.ZipFile(old,'w') as bundle:
        bundle.writestr('manifest.json',json.dumps(manifest))
        bundle.writestr('facts.jsonl',content)
    imported = Store(tmp_path / 'old-import')
    import_snapshot(imported,old)
    assert dashboard(imported)['summary'] == dashboard(store)['summary']

