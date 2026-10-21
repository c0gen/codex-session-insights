"""Cache history and recorded reasoning preserve filters and response coverage."""
import json

import pytest

from codex_insights.buckets import rebuild_buckets
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from conftest import event, log, token, T


def test_daily_cache_counts_filters_copies_and_import(indexed, tmp_path):
    store, root, source_id = indexed
    content = log('one') + token(100)
    (root / 'one.jsonl').write_bytes(content)
    (root / 'copy.jsonl').write_bytes(content)
    (root / 'two.jsonl').write_bytes(log('two') + token(900, 86403))
    refresh(store)
    expected = [
        dict(day='2026-10-01', input_tokens=100, cached_tokens=50, observations=1, input_available=1, cached_available=1),
        dict(day='2026-10-02', input_tokens=900, cached_tokens=450, observations=1, input_available=1, cached_available=1),
    ]
    data = dashboard(store)
    assert data['cache_rate_timeline'] == expected
    project_id = data['options']['projects'][0]['id']
    for filters in ({'source_id': source_id}, {'model': 'gpt-5.3-codex'},
                    {'project_id': project_id}, {'provider': 'codex'}):
        assert dashboard(store, filters)['cache_rate_timeline'] == expected
    assert dashboard(store, {'range': 'custom', 'start': '2026-10-02', 'end': '2026-10-02'})['cache_rate_timeline'] == expected[1:]
    assert dashboard(store, {'range': 'custom', 'start': '2020-01-01', 'end': '2020-01-02'})['cache_rate_timeline'] == []
    assert dashboard(store, {'_view': 'usage'})['cache_rate_timeline'] == expected
    assert dashboard(store, {'_view': 'overview'})['cache_rate_timeline'] is None
    store.set_setting('bucket_version', None)
    assert dashboard(store)['cache_rate_timeline'] == expected
    snapshot = tmp_path / 'usage.codex-insights'
    export_snapshot(store, snapshot)
    imported = Store(tmp_path / 'imported')
    import_snapshot(imported, snapshot)
    assert dashboard(imported)['cache_rate_timeline'] == expected


def test_cache_day_uses_display_timezone_and_preserves_missing_counts(indexed):
    store, root, _ = indexed
    # 03:59 UTC belongs to the previous calendar day in New York.
    (root / 'one.jsonl').write_bytes(log() + token(100, -36001) + token(200, -35999, last=100))
    refresh(store)
    expected = dashboard(store)['cache_rate_timeline']
    assert [row['day'] for row in expected] == ['2026-09-30', '2026-10-01']
    with store.connect() as db:
        db.execute("UPDATE records SET known_cached=0,cached=NULL WHERE kind='usage' AND day='2026-09-30'")
    rebuild_buckets(store)
    result = dashboard(store)
    assert result['cache_rate_timeline'][0] == {**expected[0], 'cached_tokens': 0, 'cached_available': 0}
    assert result['cache_rate_timeline'][1] == expected[1]
    assert result['usage_metrics']['cache_reuse_percent'] is None
    store.set_setting('bucket_version', None)
    assert dashboard(store)['cache_rate_timeline'] == result['cache_rate_timeline']


def test_mixed_provider_reasoning_uses_matching_output_only(indexed, tmp_path):
    store, root, _ = indexed
    (root / 'one.jsonl').write_bytes(log() + token(100))
    claude = tmp_path / 'claude'; claude.mkdir()
    store.add_source(claude, provider='claude_code')
    (claude / 'one.jsonl').write_text(json.dumps({
        'sessionId': 'claude', 'timestamp': T.isoformat(), 'type': 'assistant', 'uuid': 'message',
        'cwd': 'C:/private/claude', 'message': {'id': 'message', 'model': 'claude-sonnet-4-6',
            'usage': {'input_tokens': 100, 'output_tokens': 10000, 'cache_read_input_tokens': 20}},
    }) + '\n', encoding='utf-8')
    refresh(store)
    metrics = dashboard(store)['usage_metrics']
    assert metrics['reasoning_share_percent'] == 50
    assert metrics['reasoning_share_basis'] == dict(reasoning_tokens=5, output_tokens=10,
        included_responses=1, total_responses=2)
    assert dashboard(store)['coverage']['tokens']['metrics']['reasoning']['state'] == 'partial'
    claude_metrics = dashboard(store, {'provider': 'claude_code'})['usage_metrics']
    assert claude_metrics['reasoning_share_percent'] is None
    assert claude_metrics['reasoning_share_basis']['included_responses'] == 0
    store.set_setting('bucket_version', None)
    assert dashboard(store)['usage_metrics'] == metrics


@pytest.mark.parametrize('reasoning,output,expected', [(2,10,20), (0,10,0), (0,0,None), (11,10,None)])
def test_reasoning_intersection_with_mixed_availability_in_one_bucket(indexed, reasoning, output, expected):
    store, root, _ = indexed
    (root / 'one.jsonl').write_bytes(log() + token(100) + token(1000, 4, last=900) + token(1100, 5, last=100))
    refresh(store)
    with store.connect() as db:
        ids = [row[0] for row in db.execute("SELECT event_id FROM records WHERE kind='usage' ORDER BY ts")]
        assert len(ids) == 3
        db.execute('UPDATE records SET reasoning=?,output=? WHERE event_id=?', (reasoning, output, ids[0]))
        db.execute('UPDATE records SET known_reasoning=0,reasoning=999,output=10000 WHERE event_id=?', (ids[1],))
        db.execute('UPDATE records SET known_output=0,reasoning=999,output=NULL WHERE event_id=?', (ids[2],))
    rebuild_buckets(store)
    with store.connect() as db:
        assert db.execute("SELECT event_count FROM metric_buckets WHERE kind='usage'").fetchone()[0] == 3
    result = dashboard(store)['usage_metrics']
    assert result['reasoning_share_percent'] == expected
    assert result['reasoning_share_basis'] == dict(reasoning_tokens=reasoning, output_tokens=output,
        included_responses=1, total_responses=3)
    store.set_setting('bucket_version', None)
    assert dashboard(store)['usage_metrics'] == result


def test_no_joint_reasoning_counters(indexed):
    store, root, _ = indexed
    (root / 'one.jsonl').write_bytes(log() + token(100) + token(200, 4, last=100))
    refresh(store)
    with store.connect() as db:
        ids = [r[0] for r in db.execute("SELECT event_id FROM records WHERE kind='usage' ORDER BY ts")]
        db.execute('UPDATE records SET known_output=0 WHERE event_id=?', (ids[0],))
        db.execute('UPDATE records SET known_reasoning=0 WHERE event_id=?', (ids[1],))
    rebuild_buckets(store)
    metrics = dashboard(store)['usage_metrics']
    assert metrics['reasoning_share_percent'] is None
    assert metrics['reasoning_share_basis'] == dict(reasoning_tokens=0, output_tokens=0,
        included_responses=0, total_responses=2)
