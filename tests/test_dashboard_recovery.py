"""Dashboard selection recovery and missing-counter presentation contracts."""
import copy
import json

from conftest import log, token
from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.report import anonymize, export_html


def test_removed_filters_recover_without_changing_valid_date_or_provider(indexed, tmp_path):
    store, root, sid = indexed
    (root / 'a.jsonl').write_bytes(log() + token(100))
    refresh(store)
    pid = dashboard(store)['projects'][0]['project_id']
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'b.jsonl').write_bytes((log('other') + token(200)).replace(b'/work/project', b'/work/other'))
    store.add_source(other)
    refresh(store)
    store.forget_source(sid)
    rebuild_projection(store)
    filters = dict(project_id=pid, source_id=sid, model='removed-model', provider='codex',
                   range='custom', start='2026-10-01', end='2026-10-01')
    original = dict(filters)
    result = dashboard(store, filters)
    assert filters == original
    assert result['summary']['total_tokens'] == 220
    assert all(result['filters'][key] == '' for key in ('project_id', 'source_id', 'model'))
    assert all(result['filters'][key] == filters[key] for key in ('range', 'start', 'end', 'provider'))
    export_html(result, tmp_path / 'recovered.html')
    assert pid not in (tmp_path / 'recovered.html').read_text(encoding='utf-8')


def test_valid_empty_date_selection_and_disabled_source_are_preserved(indexed):
    store, root, sid = indexed
    (root / 'a.jsonl').write_bytes(log() + token(100))
    refresh(store)
    pid = dashboard(store)['projects'][0]['project_id']
    filters = dict(project_id=pid, source_id=sid, model='gpt-5.3-codex',
                   range='custom', start='2020-01-01', end='2020-01-01')
    result = dashboard(store, filters)
    assert all(result['filters'][key] == value for key, value in filters.items())
    assert result['summary']['total_tokens'] == 0
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0 WHERE id=?', (sid,))
    rebuild_projection(store)
    assert dashboard(store, {'source_id': sid})['filters']['source_id'] == sid


def test_anonymization_handles_stale_ids_without_mutating_snapshot(indexed):
    store, root, _ = indexed
    (root / 'a.jsonl').write_bytes(log() + token(100))
    refresh(store)
    result = dashboard(store)
    result['filters'].update(project_id='private-removed-project', source_id='private-removed-source')
    # Also tolerate a project row whose option disappeared in an older snapshot.
    result['options']['projects'] = []
    original = copy.deepcopy(result)
    anonymous = anonymize(result)
    assert anonymous['filters']['project_id'] == anonymous['filters']['source_id'] == ''
    assert anonymous['projects'][0]['name'] == 'Project 1'
    assert 'private-removed' not in json.dumps(anonymous)
    assert result == original


def test_missing_cache_counters_are_not_zero_discount(indexed):
    store, _, _ = indexed
    brain = store.directory / 'brain'
    path = brain / 'missing/.system_generated/logs/transcript.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'timestamp': '2026-10-01T14:00:00Z', 'sessionId': 'missing',
        'type': 'assistant', 'message': {'id': 'm', 'model': 'unknown', 'content': []}}) + '\n')
    store.add_source(brain, provider='antigravity')
    refresh(store)
    result = dashboard(store, {'provider': 'antigravity'})
    assert result['coverage']['tokens']['metrics']['cached']['state'] == 'unavailable'
    assert result['usage_metrics']['cache_discount_usd'] is None
    assert result['usage_metrics']['cache_discount_coverage_percent'] is None


def test_recorded_zero_cache_discount_stays_zero(indexed):
    store, root, _ = indexed
    (root / 'a.jsonl').write_bytes(log() + token(1))  # Recorded usage with zero cached reads.
    refresh(store)
    result = dashboard(store)
    assert result['coverage']['tokens']['metrics']['cached']['state'] == 'complete'
    assert result['usage_metrics']['cache_discount_usd'] == 0
