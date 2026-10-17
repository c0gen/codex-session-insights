"""Run the generated hook command through Windows' command shell."""
import base64
import json
import os
import subprocess
import sys

import pytest

from codex_insights.providers.setup import Setup
from codex_insights.providers.windows_launcher import command


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher integration')
def test_stdin_stdout_and_quoted_unicode_arguments(tmp_path):
    script = tmp_path / "script space ' café.py"
    script.write_text('import json,sys; print(json.dumps([sys.argv[1:], json.load(sys.stdin)], ensure_ascii=False))', encoding='utf-8')
    value = "C:\\space directory\\Andy's 漢字 $(echo wrong)\\"
    launch = command([sys.executable, str(script), '--data-dir', value])
    assert launch.isascii()
    result = subprocess.run(['cmd.exe', '/d', '/s', '/c', launch], input=json.dumps({'text': 'hello 漢字'}).encode('utf-8'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    args, stdin = json.loads(result.stdout)
    assert args == ['--data-dir', value] and stdin == {'text': 'hello 漢字'}


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher integration')
def test_oversized_unicode_hook_still_returns_neutral_response(tmp_path):
    launch = command([sys.executable, '-m', 'codex_insights.providers.bridge', '--data-dir', str(tmp_path / 'data space'),
                      '--provider', 'antigravity', '--mode', 'hook', '--event', 'PostInvocation'])
    result = subprocess.run(['cmd.exe', '/d', '/s', '/c', launch], input=('漢' * 500000).encode('utf-8'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == b'{}'
    assert not list((tmp_path / 'data space').glob('bridge/events/*.jsonl'))


def test_owned_upgrade_preserves_original_setting_and_user_changes(tmp_path):
    home = tmp_path / 'home'
    config = home / '.gemini/config/hooks.json'; config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'other': {'enabled': False}}))
    setup = Setup(tmp_path / 'data', home=home, command=['old-bridge'])
    setup.update('antigravity', 'install')
    setup.command = ['new-bridge']
    assert setup.preview('antigravity')['upgrade_available']
    setup.update('antigravity', 'install')
    assert not setup.preview('antigravity')['upgrade_available']
    setup.update('antigravity', 'uninstall')
    assert json.loads(config.read_text()) == {'other': {'enabled': False}}
    setup.update('antigravity', 'install')
    value = json.loads(config.read_text()); value['codex-session-insights'] = {'enabled': False}
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='already in use'):
        setup.update('antigravity', 'install')
    setup.update('antigravity', 'uninstall')
    assert json.loads(config.read_text()) == value
