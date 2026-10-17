import json

import pytest

from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from conftest import event, log, token


@pytest.mark.parametrize('bad', [
    event('session_meta', {'id': 'bad', 'git': 'PRIVATE INVALID GIT'}),
    event('session_meta', {'id': 'bad', 'source': {'subagent': []}}),
    event('session_meta', {'id': 'bad', 'source': {'subagent': {'thread_spawn': 'PRIVATE SPAWN'}}}),
    event('session_meta', {'id': 'bad', 'source': {'subagent': {'thread_spawn': {'parent_thread_id': ['invalid']}}}}),
    log('bad') + event('turn_context', {'settings': 'PRIVATE SETTINGS'}),
    log('bad') + event('event_msg', {'type': 'thread_settings_applied', 'thread_settings': []}),
    log('bad') + event('turn_context', {'settings': {'model': ['PRIVATE MODEL']}}),
    log('bad') + event('turn_context', {'thread_settings': {'effort': {'PRIVATE': 'high'}}}),
    log('bad') + event('event_msg', {'type': 'token_count', 'info': 'PRIVATE INFO'}),
    log('bad') + event('event_msg', {'type': 'token_count', 'info': {'total_token_usage': []}}),
])
def test_malformed_nested_payload_isolated_and_retried(indexed, bad):
    store, root, _ = indexed
    (root / 'a-malformed.jsonl').write_bytes(bad)
    (root / 'z-valid.jsonl').write_bytes(log() + token(100))
    result = refresh(store)
    assert result['errors'] == 1
    assert dashboard(store)['summary']['total_tokens'] == 110
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM file_failures').fetchone()[0] == 1
    diagnostic = (store.directory / 'indexing-errors.jsonl').read_text()
    assert 'PRIVATE' not in diagnostic
    assert json.loads(diagnostic)['error_type'] == 'ValueError'
    restarted = Store(store.directory)
    assert refresh(restarted, automatic=True)['skipped_errors'] == 1
    assert refresh(restarted)['errors'] == 1
    (root / 'a-malformed.jsonl').write_bytes(log('bad') + token(100))
    assert refresh(restarted, automatic=True)['errors'] == 0
    assert dashboard(restarted)['summary']['total_tokens'] == 220


def test_bad_append_retains_prior_facts_and_checkpoint(indexed):
    store, root, _ = indexed
    path = root / 'chat.jsonl'
    path.write_bytes(log() + token(100))
    refresh(store)
    with store.connect() as db:
        original = db.execute('SELECT offset FROM files').fetchone()[0]
    with path.open('ab') as stream:
        stream.write(token(300, 5, last=200) + event('event_msg', {'type': 'token_count', 'info': ['invalid']}, 6))
    assert refresh(store)['errors'] == 1
    assert dashboard(store)['summary']['total_tokens'] == 110
    with store.connect() as db:
        assert db.execute('SELECT offset FROM files').fetchone()[0] == original


def test_optional_null_and_omitted_nested_data_remain_valid(indexed):
    store, root, _ = indexed
    (root / 'valid.jsonl').write_bytes(
        event('session_meta', {'id': 'chat', 'git': None, 'source': {'subagent': 'review'}})
        + event('turn_context', {'settings': None})
        + event('event_msg', {'type': 'token_count', 'info': None}) + token(100))
    assert refresh(store)['errors'] == 0
    assert dashboard(store)['summary']['total_tokens'] == 110


def test_unexpected_programming_error_is_not_silenced(indexed, monkeypatch):
    from codex_insights.parser import SessionParser
    store, root, _ = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100))

    def broken(*args):
        raise AttributeError('Unexpected implementation defect')

    monkeypatch.setattr(SessionParser, 'consume', broken)
    with pytest.raises(AttributeError, match='implementation defect'):
        refresh(store)
