"""Configured profile discovery and configuration ownership across upgrades."""
import json

from codex_insights.providers.profiles import SEEN_ROOTS, config_directory, register_claude_profiles
from codex_insights.providers.setup import Setup
from codex_insights.storage import Store


def test_discovery_deduplicates_and_preserves_disabled_and_forgotten_roots(tmp_path):
    home, custom = tmp_path / 'home', tmp_path / 'profile space café'
    store = Store(tmp_path / 'data')
    env = {'CLAUDE_CONFIG_DIR': str(custom)}
    register_claude_profiles(store, home, env)
    assert len(store.sources()) == 2
    sid = store.sources()[0]['id']
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0 WHERE id=?', (sid,))
    register_claude_profiles(store, home, env)
    assert next(s for s in store.sources() if s['id'] == sid)['enabled'] == 0
    forgotten = next(s for s in store.sources() if s['id'] != sid)
    store.forget_source(forgotten['id'])
    register_claude_profiles(Store(store.directory), home, env)
    assert len(store.sources()) == 1
    assert len(store.setting(SEEN_ROOTS)) == 2


def test_existing_indexes_do_not_restore_forgotten_default_but_find_custom(tmp_path):
    store = Store(tmp_path / 'data')
    store.set_setting('provider_defaults_registered', True)
    register_claude_profiles(store, tmp_path / 'home', {'CLAUDE_CONFIG_DIR': str(tmp_path / 'custom')})
    assert [s['root'] for s in store.sources()] == [str((tmp_path / 'custom/projects').resolve())]


def test_manually_forgotten_profile_is_not_later_rediscovered(tmp_path):
    store = Store(tmp_path / 'data')
    custom = tmp_path / 'custom'
    sid = store.add_source(custom / 'projects', provider='claude_code')
    store.forget_source(sid)
    register_claude_profiles(store, tmp_path / 'home', {'CLAUDE_CONFIG_DIR': str(custom)})
    assert len(store.sources()) == 1
    assert store.sources()[0]['root'] != str((custom / 'projects').resolve())


def test_empty_override_and_equivalent_default_only_register_once(tmp_path):
    assert config_directory(tmp_path, {'CLAUDE_CONFIG_DIR': '  '}) == (tmp_path / '.claude').resolve()
    store = Store(tmp_path / 'data')
    register_claude_profiles(store, tmp_path, {'CLAUDE_CONFIG_DIR': str(tmp_path / '.claude/../.claude')})
    assert len(store.sources()) == 1


def test_profile_switch_restores_its_own_previous_command(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    setup = Setup(tmp_path / 'data', home=home, command=['bridge'])
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    default = setup.path('claude_code')
    default.parent.mkdir(parents=True)
    default.write_text(json.dumps({'statusLine': {'type': 'command', 'command': 'default-original'}}))
    setup.update('claude_code', 'install')
    default_previous = setup.previous_file('claude_code')
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'custom'))
    custom = setup.path('claude_code')
    custom.parent.mkdir(parents=True)
    custom.write_text(json.dumps({'statusLine': {'type': 'command', 'command': 'custom-original'}}))
    setup.update('claude_code', 'install')
    assert setup.previous_file('claude_code') != default_previous
    setup.update('claude_code', 'uninstall')
    assert json.loads(custom.read_text())['statusLine']['command'] == 'custom-original'
    monkeypatch.delenv('CLAUDE_CONFIG_DIR')
    assert setup.preview('claude_code')['installed']
    setup.update('claude_code', 'uninstall')
    assert json.loads(default.read_text())['statusLine']['command'] == 'default-original'


def test_legacy_ownership_upgrade_keeps_original_and_respects_user_edits(tmp_path, monkeypatch):
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    setup = Setup(tmp_path / 'data', home=tmp_path / 'home', command=['new-bridge'])
    path = setup.path('claude_code')
    path.parent.mkdir(parents=True)
    previous = {'type': 'command', 'command': 'original'}
    installed = {'type': 'command', 'command': 'old-bridge'}
    path.write_text(json.dumps({'statusLine': installed, 'other': True}))
    setup.state_path.parent.mkdir(parents=True)
    setup.state_path.write_text(json.dumps({'claude_code': {'previous': previous, 'installed': installed, 'status': 'installed'}}))
    assert setup.preview('claude_code')['upgrade_available']
    setup.update('claude_code', 'install')
    assert json.loads(setup.previous_file('claude_code').read_text()) == previous
    assert 'claude_code' not in json.loads(setup.state_path.read_text())
    path.write_text(json.dumps({'statusLine': {'type': 'command', 'command': 'user-changed'}}))
    setup.update('claude_code', 'uninstall')
    assert json.loads(path.read_text())['statusLine']['command'] == 'user-changed'
