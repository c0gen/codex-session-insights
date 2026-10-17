"""Mac bundle resolution and exporter-specific native readiness."""
import json
import shlex
import sys

from codex_insights.desktop import verify_native
from codex_insights.providers.setup import Setup


def test_frozen_mac_uses_bundled_helper_and_quotes_arguments(tmp_path, monkeypatch):
    contents = tmp_path / "Exporter café's app.app" / 'Contents'
    resources = contents / 'Resources'
    resources.mkdir(parents=True)
    helper = contents / 'MacOS/bridge_entry'
    helper.parent.mkdir()
    helper.write_text('helper')
    helper.chmod(0o755)
    monkeypatch.setattr(sys, 'frozen', 'macosx_app', raising=False)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(sys, 'executable', str(helper.with_name('python')))
    monkeypatch.setenv('RESOURCEPATH', str(resources))
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    setup = Setup(tmp_path / 'data space', home=tmp_path / 'home')
    command = shlex.split(setup.shell_command('claude_code'))
    assert command[0] == str(helper.resolve())
    assert command[command.index('--data-dir') + 1] == str(tmp_path / 'data space')
    assert setup.preview('claude_code')['status'] == 'not_installed'
    helper.unlink()
    assert all(s['status'] == 'unavailable' and 'bridge is missing' in s['error'] for s in setup.states())


def test_native_exporter_needs_sources_and_controls_but_no_chart(tmp_path):
    class Window:
        destroyed = False

        def evaluate_js(self, script):
            if script.startswith('({'):
                return {'heading': 'Mac Exporter', 'bridge': {'tokens': 42, 'running': False},
                        'canvas': False, 'sources': True, 'exportControl': True}

        def destroy(self):
            self.destroyed = True

    window = Window()
    destination = tmp_path / 'native.json'
    verify_native(window, destination, exporter=True)
    assert json.loads(destination.read_text())['ok']
    assert window.destroyed
