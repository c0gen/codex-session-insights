"""Exercise a packaged export/import with synthetic Claude pricing evidence only.

Usage: python scripts/smoke_exporter.py <packaged executable> [--native-exporter]
The optional native check is for the Intel Mac exporter window.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from codex_insights.queries import dashboard
from codex_insights.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--native-exporter', action='store_true')
    args = parser.parse_args()
    executable = args.executable.resolve()
    parent = Path(__file__).resolve().parents[1] / '.local-data'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='packaged-export-', dir=parent) as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(parent.resolve())
        profile = root / "profile space café's"
        logs = profile / 'projects/project'
        logs.mkdir(parents=True)
        usage = {'input_tokens': 1_000_000, 'output_tokens': 100_000,
                 'cache_read_input_tokens': 200_000, 'cache_creation_input_tokens': 300_000,
                 'cache_creation': {'ephemeral_5m_input_tokens': 200_000, 'ephemeral_1h_input_tokens': 100_000},
                 'speed': 'fast', 'service_tier': 'standard', 'inference_geo': 'us'}
        event = {'type': 'assistant', 'sessionId': 'synthetic', 'uuid': 'response',
                 'timestamp': '2026-10-04T12:00:00Z', 'cwd': '/private-smoke/project',
                 'message': {'id': 'response', 'model': 'claude-opus-5-5', 'usage': usage,
                             'content': [{'type': 'text', 'text': 'PRIVATE_SMOKE_CANARY'}]}}
        (logs / 'chat.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')
        source = Store(root / 'source')
        source.add_source(profile / 'projects', provider='claude_code')
        # Prevent the packaged app from registering any real provider sources.
        source.set_setting('provider_defaults_registered', True)
        source.set_setting('timezone', 'UTC')
        source.set_setting('live_usage_enabled', False)
        env = {**os.environ, 'CLAUDE_CONFIG_DIR': str(profile), 'CODEX_HOME': str(root / 'codex')}
        env['CODEX_INSIGHTS_SMOKE_MIN_TOKENS'] = '1600000'
        for name in ('CODEX_INSIGHTS_SMOKE_RESULT', 'CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT',
                     'CODEX_INSIGHTS_ALLOWANCE_SMOKE_RESULT'):
            env.pop(name, None)

        def run(*arguments, environment=None):
            completed = subprocess.run([str(executable), *map(str, arguments)], env=environment or env,
                                       capture_output=True, timeout=90)
            if completed.returncode:
                startup = source.directory / 'startup.log'
                raise AssertionError({'exit_code': completed.returncode,
                                      'stderr': completed.stderr.decode('utf-8', 'replace'),
                                      'stdout': completed.stdout.decode('utf-8', 'replace'),
                                      'startup': startup.read_text(encoding='utf-8')[-12000:] if startup.exists() else None})

        if args.native_exporter:
            native = root / 'native.json'
            run('--data-dir', source.directory, 'exporter', '--smoke-result', native)
            native_result = json.loads(native.read_text(encoding='utf-8'))
            assert native_result['ok'], native_result
        snapshot = root / 'usage.codex-insights'
        run('--data-dir', source.directory, 'export', '--output', snapshot)
        local = dashboard(source, {'provider': 'claude_code'})
        assert local['summary']['cost'] == 17.25
        with zipfile.ZipFile(snapshot) as bundle:
            assert json.loads(bundle.read('manifest.json'))['format_version'] == 6
            facts = bundle.read('facts.jsonl')
            assert b'PRIVATE_SMOKE_CANARY' not in facts and b'/private-smoke' not in facts
            assert b'"speed":"fast"' in facts and b'"inference_geo":"us"' in facts
        target = root / 'target'
        receiver = Store(target)
        receiver.set_setting('provider_defaults_registered', True)
        receiver.set_setting('live_usage_enabled', False)
        receiving_env = {**env, 'CLAUDE_CONFIG_DIR': str(root / 'receiver-profile'), 'CODEX_HOME': str(root / 'receiver-codex')}
        run('--data-dir', target, 'import', snapshot, environment=receiving_env)
        remote = dashboard(Store(target), {'provider': 'claude_code'})
        assert remote['summary']['cost'] == local['summary']['cost']
        assert remote['summary']['priced_percent'] == local['summary']['priced_percent'] == 100
        assert remote['usage_metrics'] == local['usage_metrics']
        # Formatting-only copies reconcile in the packaged collector too.
        (logs / 'formatted.jsonl').write_text(json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        run('--data-dir', source.directory, 'export', '--output', snapshot)
        from codex_insights.history_review import read
        with source.connect() as db:
            assert read(db) == []
        conflicting = json.loads(json.dumps(event))
        conflicting['message']['usage']['output_tokens'] = 200_000
        (logs / 'divergent.jsonl').write_text(json.dumps(conflicting) + '\n', encoding='utf-8')
        run('--data-dir', source.directory, 'export', '--output', snapshot)
        run('--data-dir', target, 'import', snapshot, environment=receiving_env)
        from smoke_history_review import check
        check(executable, target, receiving_env)
        # Receiving-side choices must never recirculate as locally observed facts.
        outbound = root / 'no-local-history.codex-insights'
        run('--data-dir', target, 'export', '--output', outbound, environment=receiving_env)
        with zipfile.ZipFile(outbound) as bundle:
            assert json.loads(bundle.read('manifest.json'))['fact_count'] == 0
        print('Packaged v6 Claude cost export/import passed')
        print('Packaged normalized-copy, retained alternatives and review API passed')
        from smoke_claude_recovery import check as check_recovery
        check_recovery(root / 'identity-recovery', run, env)


if __name__ == '__main__':
    main()
