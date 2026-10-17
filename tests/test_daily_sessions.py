"""Daily sessions count identities, independent of token volume or pagination."""
import json

from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.project_groups import merge_projects
from codex_insights.queries import dashboard
from codex_insights.transfers import export_snapshot, import_snapshot
from codex_insights.storage import Store


def event(at,kind,payload):
    return (json.dumps(dict(timestamp=at,type=kind,payload=payload))+'\n').encode()


def session(sid,at,source='cli',project='one',parent=None):
    return event(at,'session_meta',dict(id=sid,source=source,cwd='C:/synthetic/'+project,**({'forked_from_id':parent} if parent else {})))


def active(at,model='gpt-5.3-codex'):
    return event(at,'turn_context',dict(model=model))+event(at,'event_msg',dict(type='agent_message',message='synthetic'))


def counts(store,filters=None):
    return dashboard(store,filters)['daily_sessions']


def test_categories_replays_segments_copies_midnight_and_filters(indexed,tmp_path):
    store,root,sid=indexed
    old='2026-10-01T03:59:00Z'
    new='2026-10-02T03:59:00Z'
    later='2026-10-02T04:01:00Z'
    parent=session('parent',old)+active(old)
    (root/'parent.jsonl').write_bytes(parent)
    spawn={'subagent':{'thread_spawn':{'parent_thread_id':'parent'}}}
    child=session('child',new,spawn)+active(old)+active(new)+active(later)
    (root/'child.jsonl').write_bytes(child)
    nested={'subagent':{'thread_spawn':{'parent_thread_id':'child'}}}
    (root/'nested.jsonl').write_bytes(session('nested',later,nested)+active(old)+active(later))
    (root/'system.jsonl').write_bytes(session('system',later,{'subagent':'review'})+active(old)+active(later))
    (root/'fork.jsonl').write_bytes(session('fork',later,parent='parent',project='two')+active(old)+active(later,'other-model'))
    # A second physical segment and exact file copies do not add identities.
    (root/'page.jsonl').write_bytes(session('parent',new)+active(new)+active(new))
    (root/'copy.jsonl').write_bytes(child)
    copy_root=tmp_path/'copied';copy_root.mkdir()
    (copy_root/'child.jsonl').write_bytes(child)
    copy_sid=store.add_source(copy_root)
    refresh(store)
    expected=[dict(day='2026-09-30',chats=1,subagents=0,system_agents=0),dict(day='2026-10-01',chats=1,subagents=1,system_agents=0),dict(day='2026-10-02',chats=1,subagents=2,system_agents=1)]
    assert counts(store)==expected
    assert counts(store,{'model':'other-model'})==[expected[-1]|dict(subagents=0,system_agents=0)]
    assert counts(store,{'range':'custom','start':'2026-10-02','end':'2026-10-02'})==expected[-1:]
    assert refresh(store)['bytes_read']==0
    assert counts(store)==expected
    store.set_setting('bucket_version',None)
    assert counts(store)==expected
    store.set_setting('bucket_version',1)
    with store.connect() as db:
        selected=db.execute("SELECT source_id FROM canonical WHERE session_id='child'").fetchone()[0]
    other=copy_sid if selected==sid else sid
    # Source filters follow the selected canonical source, not every physical copy.
    other_rows=counts(store,{'source_id':other})
    assert all(r['subagents']<=1 for r in other_rows)
    with store.connect() as db:
        db.execute('UPDATE sources SET enabled=0 WHERE id=?',(copy_sid,))
    rebuild_projection(store)
    assert counts(store)==expected
    assert counts(store,{'source_id':copy_sid})==[]
    store.forget_source(copy_sid);rebuild_projection(store)
    assert counts(store)==expected
    projects={r['name']:r['id'] for r in dashboard(store)['options']['projects']}
    assert counts(store,{'project_id':projects['two']})==[expected[-1]|dict(subagents=0,system_agents=0)]
    merge_projects(store,[projects['two']],projects['one'])
    assert counts(store,{'project_id':projects['two']})==expected
    snapshot=tmp_path/'counts.codex-insights';export_snapshot(store,snapshot)
    target=Store(tmp_path/'imported');import_snapshot(target,snapshot)
    assert counts(target)==expected


def test_dst_timezone_inactive_day_and_zero_usage(indexed):
    store,root,_=indexed
    # Spring-forward transition: both times belong to March 8 locally.
    content=session('chat','2026-03-08T06:59:00Z')+active('2026-03-08T06:59:00Z')+active('2026-03-08T07:01:00Z')
    content+=active('2026-03-10T03:59:00Z')+active('2026-03-12T04:01:00Z')
    (root/'chat.jsonl').write_bytes(content)
    refresh(store)
    assert [r['day'] for r in counts(store)]==['2026-03-08','2026-03-09','2026-03-12']
    assert all(r['chats']==1 for r in counts(store))
    assert dashboard(store)['summary']['total_tokens']==0
    assert counts(store,{'model':'gpt-5.3-codex'})==counts(store)
    store.set_setting('timezone','UTC');rebuild_projection(store)
    assert [r['day'] for r in counts(store)]==['2026-03-08','2026-03-10','2026-03-12']
    assert counts(store,{'range':'custom','start':'2026-03-11','end':'2026-03-11'})==[]
    # Removed selections recover to the remaining valid filters.
    recovered = dashboard(store, {'model':'absent'})
    assert recovered['filters']['model'] == ''
    assert recovered['daily_sessions'] == counts(store)

def test_fall_dst_repeated_hour_is_one_session(indexed):
    store,root,_=indexed
    content=session('autumn','2025-11-02T05:30:00Z')
    content+=active('2025-11-02T05:30:00Z')+active('2025-11-02T06:30:00Z')
    (root/'autumn.jsonl').write_bytes(content)
    refresh(store)
    assert counts(store)==[dict(day='2025-11-02',chats=1,subagents=0,system_agents=0)]
