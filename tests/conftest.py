import json
from datetime import datetime, timezone, timedelta

import pytest
from codex_insights.storage import Store

T = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)


def event(kind, payload, seconds=0):
    return (json.dumps({'type':kind,'timestamp':(T+timedelta(seconds=seconds)).isoformat(),'payload':payload})+'\n').encode()


def usage(n):
    return {'input_tokens':n,'cached_input_tokens':n//2,'output_tokens':n//10,'reasoning_output_tokens':n//20,'total_tokens':n+n//10}


def log(sid='chat', parent=None):
    meta={'id':sid,'cwd':'C:/private/work/project','source':{'subagent':{'thread_spawn':{'parent_thread_id':parent}}} if parent else 'cli'}
    return event('session_meta',meta)+event('turn_context',{'model':'gpt-5.3-codex','effort':'high'},1)+event('event_msg',{'type':'user_message','message':'PRIVATE PROMPT'},2)


def token(n, seconds=3, last=None):
    return event('event_msg',{'type':'token_count','info':{'total_token_usage':usage(n),'last_token_usage':usage(last if last is not None else n)}},seconds)


@pytest.fixture
def indexed(tmp_path):
    root=tmp_path/'sessions';root.mkdir()
    store=Store(tmp_path/'db');store.set_setting('timezone','America/New_York')
    sid=store.add_source(root)
    return store,root,sid
