"""Official CLI contract captured from 1.3.5, with identity/text removed."""
import json
from pathlib import Path

import pytest

from codex_insights.antigravity_usage import AntigravityUsageProvider, AntigravityUsage, normalize_report, ARGUMENTS
from codex_insights.account_rpc import AllowanceError
from codex_insights.providers.allowances import read
from codex_insights.providers.bridge import receive
from test_claude_usage import FakePopen, NOW

FIXTURE = Path(__file__).parent / 'fixtures/antigravity-usage-1.3.5.json'


def report():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def test_recorded_quota_contract_and_zeros():
    value = report()
    value.update(email='PRIVATE_EMAIL', response='PRIVATE_TEXT')
    buckets = normalize_report(value)['buckets']
    assert [b['id'] for b in buckets] == ['gemini-weekly', 'gemini-5h', '3p-weekly', '3p-5h']
    assert [b['remaining_percent'] for b in buckets] == [75, 0, 100, 100]
    assert buckets[0]['kind'] == 'seven_day' and buckets[1]['kind'] == 'five_hour'
    assert buckets[0]['scope_label'] == 'Gemini Models'
    assert 'PRIVATE' not in json.dumps(buckets)


@pytest.mark.parametrize('fraction', [None, True, -1, 1.1, float('nan'), '0.5'])
def test_invalid_quota_is_not_a_zero_reading(fraction):
    value = report()
    value['command']['data']['groups'][0]['buckets'][0]['remaining_fraction'] = fraction
    assert len(normalize_report(value)['buckets']) == 3


def test_unknown_and_model_reports_are_rejected():
    for value in ({}, {'status': 'ERROR'}, {**report(), 'num_turns': 1}, {**report(), 'command': {'name': 'other'}}):
        with pytest.raises(AllowanceError):
            normalize_report(value)


def test_official_client_is_gated_before_usage_and_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'PRIVATE_SECRET')
    popen = FakePopen(b'1.3.5\n', FIXTURE.read_bytes())
    provider = AntigravityUsageProvider(tmp_path, executable='agy.exe', popen=popen)
    assert len(provider.fetch()['buckets']) == 4
    assert popen.calls[0][0] == ['agy.exe', '--version']
    assert popen.calls[1][0] == ['agy.exe', *ARGUMENTS]
    assert 'GEMINI_API_KEY' not in popen.calls[1][1]['env']
    old = FakePopen(b'1.0.0\n')
    with pytest.raises(AllowanceError, match='1.1.11'):
        AntigravityUsageProvider(tmp_path, executable='agy.exe', popen=old).fetch()
    assert len(old.calls) == 1


def test_missing_signin_timeout_and_missing_cli(tmp_path):
    with pytest.raises(AllowanceError) as missing:
        AntigravityUsageProvider(tmp_path, discover=lambda: None).fetch()
    assert missing.value.code == 'missing_agy'
    with pytest.raises(AllowanceError):
        AntigravityUsageProvider(tmp_path, executable='agy.exe', popen=FakePopen(b'1.3.5', b'{"status":"ERROR"}')).fetch()
    popen = FakePopen(block=True)
    provider = AntigravityUsageProvider(tmp_path, executable='agy.exe', popen=popen)
    with pytest.raises(AllowanceError) as timeout:
        provider._run(['agy.exe', *ARGUMENTS], .01)
    assert timeout.value.code == 'timeout' and popen.processes[0].killed


def test_newest_source_wins_preserving_expiry_and_failures(tmp_path):
    now = NOW.timestamp()
    receive(tmp_path, 'antigravity', 'status', {'quota': {'statusline': {'remaining_fraction': .2}}}, now=NOW)
    cache = {'enabled': True, 'last_success_at': now - 10, 'buckets': normalize_report(report())['buckets'], 'stale': False}
    assert read(tmp_path, now=now, live={'antigravity': cache})[1]['buckets'][0]['id'] == 'statusline'
    cache['last_success_at'] = now + 1
    value = read(tmp_path, now=now + 2, live={'antigravity': cache})[1]
    assert value['source'] == 'Antigravity CLI /usage'
    assert value['buckets'][0]['remaining_percent'] == 75
    cache['stale'] = True; cache['error'] = 'Check failed'
    value = read(tmp_path, now=now + 1000000, live={'antigravity': cache})[1]
    assert value['status'] == 'stale' and value['buckets'][0]['remaining_percent'] == 75


def test_polling_defaults_and_demo_no_fetch(tmp_path):
    class Provider:
        def fetch(self):
            pytest.fail('disabled check must not fetch')
        def close(self): pass
    cache = AntigravityUsage(tmp_path, provider=Provider(), enabled=True, allowed=False)
    try:
        cache.start()
        assert not cache.read()['enabled']
        assert cache.interval == 300 and cache.max_backoff == 1800
    finally:
        cache.close()
