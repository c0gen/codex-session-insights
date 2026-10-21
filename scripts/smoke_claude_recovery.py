"""Probe old workflow-agent recovery using the packaged command line."""
import json

from codex_insights.codec import pack
from codex_insights.ingestion import anchor
from codex_insights.projection import rebuild_projection
from codex_insights.providers.claude_identity import identity, rekey
from codex_insights.providers.transcripts import TranscriptParser
from codex_insights.queries import dashboard
from codex_insights.storage import Store


def check(root, run, environment):
    profile = root / 'profile'
    logs = profile / 'projects/project'
    logs.mkdir(parents=True)
    source = Store(root / 'source')
    sid = source.add_source(profile / 'projects', provider='claude_code')
    for key, value in [('provider_defaults_registered', True), ('live_usage_enabled', False), ('timezone', 'UTC')]:
        source.set_setting(key, value)
    for relative, mid, output in [('parent.jsonl', 'parent-response', 10),
                                  ('parent/subagents/workflows/wf-smoke/agent-a.jsonl', 'child-response', 20)]:
        path = logs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {'type': 'assistant', 'sessionId': 'parent', 'uuid': mid,
                 'timestamp': '2026-10-20T12:00:00Z',
                 'message': {'id': mid, 'model': 'claude-sonnet-4-6', 'usage': {'input_tokens': 100, 'output_tokens': output}}}
        if output == 20:
            event.update(isSidechain=True, agentId='a')
        raw = (json.dumps(event) + '\n').encode()
        path.write_bytes(raw)
        parser = TranscriptParser('claude_code', path=path)
        parser.consume(raw, len(raw))
        # The old path-only parser collapsed workflow children into the parent.
        fact = rekey(parser.fact(), identity('parent'))
        parser.state['fact'].update({k: fact[k] for k in ('id', 'segment_id', 'parent_session_id', 'session_source')})
        parser.state.pop('claude_identity', None)
        parser.state['version'] = 3
        stat = path.stat()
        with source.connect() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', (sid, str(path), len(raw), stat.st_mtime_ns,
                       len(raw), anchor(path, len(raw)), pack(parser.state), 3))
            source.put_candidate(db, sid, fact, 3, path)
            source.choose_canonical(db, fact['segment_id'])
    rebuild_projection(source)
    env = {**environment, 'CLAUDE_CONFIG_DIR': str(profile), 'CODEX_HOME': str(root / 'codex')}
    before, after = root / 'before.json', root / 'after.json'
    run('--data-dir', source.directory, 'diagnose-history', '--output', before, environment=env)
    assert json.loads(before.read_text())['conflicts_by_provider'] == {'claude_code': 1}
    run('--data-dir', source.directory, 'scan', environment=env)
    run('--data-dir', source.directory, 'diagnose-history', '--output', after, environment=env)
    result = json.loads(after.read_text())
    assert result['conflicts'] == [], result
    assert result['recovery']['state'] == 'complete', result
    assert dashboard(source, {'provider': 'claude_code'})['summary']['total_tokens'] == 230
    assert (source.directory / 'insights.before-claude-identity-v1.sqlite3').is_file()
    snapshot = root / 'recovered.codex-insights'
    run('--data-dir', source.directory, 'export', '--output', snapshot, environment=env)
    receiver = Store(root / 'receiver')
    receiver.set_setting('provider_defaults_registered', True)
    receiver.set_setting('live_usage_enabled', False)
    receiving = {**env, 'CLAUDE_CONFIG_DIR': str(root / 'empty-profile')}
    run('--data-dir', receiver.directory, 'import', snapshot, environment=receiving)
    assert dashboard(receiver, {'provider': 'claude_code'})['summary']['total_tokens'] == 230
    print('Packaged Claude identity migration, backup, diagnostics and recovered transfer passed')
