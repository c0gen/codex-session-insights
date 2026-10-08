import hashlib
import json
import zipfile
from datetime import timedelta

import pytest
from codex_insights.ingestion import refresh
from codex_insights.parser import SessionParser, portable_fact
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from codex_insights.accounting.history_boundary import resolve_history_seed
from conftest import event, log, token, T


def test_append_partial_line_and_unchanged_refresh(indexed):
    store,root,_=indexed;path=root/'chat.jsonl'
    tail=token(300,5,last=200)
    path.write_bytes(log()+token(100)+tail[:25])
    refresh(store)
    assert dashboard(store)['summary']['total_tokens']==110
    assert refresh(store)['bytes_read']==0
    with path.open('ab') as f:f.write(tail[25:])
    assert refresh(store)['bytes_read']==len(tail)
    assert dashboard(store)['summary']['total_tokens']==330
    assert dashboard(store)['summary']['prompts']==1


def test_copy_dedup_offline_and_forget(indexed,tmp_path):
    store,root,sid=indexed;content=log()+token(100)
    (root/'a.jsonl').write_bytes(content);refresh(store)
    duplicate=tmp_path/'usb';duplicate.mkdir();(duplicate/'renamed.jsonl').write_bytes(content)
    usb=store.add_source(duplicate);refresh(store)
    assert dashboard(store)['summary']['total_tokens']==110
    duplicate.rename(tmp_path/'unplugged');refresh(store)
    assert next(s for s in store.sources() if s['id']==usb)['status']=='Offline'
    assert dashboard(store)['summary']['total_tokens']==110
    store.forget_source(sid);rebuild_projection(store)
    assert dashboard(store)['summary']['total_tokens']==110
    store.forget_source(usb);rebuild_projection(store)
    assert dashboard(store)['summary']['chats']==0
    assert dashboard(store)['summary']['total_tokens']==0


def test_snapshot_replacement_integrity_privacy(indexed,tmp_path):
    store,root,_=indexed;path=root/'chat.jsonl';path.write_bytes(log()+token(100));refresh(store)
    bundle=tmp_path/'usage.codex-insights';export_snapshot(store,bundle,'Intel Mac')
    target=Store(tmp_path/'target');target.set_setting('timezone','UTC')
    assert import_snapshot(target,bundle)['status']=='imported'
    assert import_snapshot(target,bundle)['status']=='unchanged'
    assert dashboard(target)['summary']['total_tokens']==110
    with zipfile.ZipFile(bundle) as z:
        facts=z.read('facts.jsonl');manifest=json.loads(z.read('manifest.json'))
        assert b'PRIVATE PROMPT' not in facts and b'C:/private' not in facts
    with path.open('ab') as f:f.write(token(300,6,last=200))
    refresh(store);export_snapshot(store,bundle);import_snapshot(target,bundle)
    assert dashboard(target)['summary']['total_tokens']==330
    broken=tmp_path/'bad.codex-insights'
    with zipfile.ZipFile(broken,'w') as z:
        manifest['revision']=99
        z.writestr('manifest.json',json.dumps(manifest));z.writestr('facts.jsonl',facts+b'corrupt')
    with pytest.raises(ValueError,match='checksum'):import_snapshot(target,broken)
    assert dashboard(target)['summary']['total_tokens']==330


def test_local_export_survives_longer_import(indexed,tmp_path):
    store,root,_=indexed;short=log()+token(100);(root/'a.jsonl').write_bytes(short);refresh(store)
    second=Store(tmp_path/'second');folder=tmp_path/'other';folder.mkdir();second.add_source(folder)
    (folder/'a.jsonl').write_bytes(short+token(300,6,last=200));refresh(second)
    bundle=tmp_path/'other.codex-insights';export_snapshot(second,bundle);import_snapshot(store,bundle)
    assert dashboard(store)['summary']['total_tokens']==330
    output=tmp_path/'local.codex-insights'
    assert export_snapshot(store,output)['sessions']==1
    third=Store(tmp_path/'third');import_snapshot(third,output)
    assert dashboard(third)['summary']['total_tokens']==110


def test_confirmed_edits_date_cutoff_and_model(indexed):
    store,root,_=indexed
    patch='*** Begin Patch\n*** Update File: C:/private/work/project/file.py\n@@\n-old\n+new\n+extra\n*** End Patch'
    call=event('response_item',{'type':'custom_tool_call','name':'apply_patch','call_id':'edit','input':patch},10)
    output=event('response_item',{'type':'custom_tool_call_output','call_id':'edit','output':'Success. Updated the following files:\nM C:/private/work/project/file.py\n'},86400)
    path=root/'edit.jsonl';path.write_bytes(log()+token(100)+call);refresh(store)
    assert dashboard(store)['summary']['change_coverage']=='partial'
    with path.open('ab') as f:f.write(output)
    refresh(store)
    assert dashboard(store,{'model':'gpt-5.3-codex'})['summary']['lines_added']==2
    previous=dashboard(store,{'range':'custom','start':'2026-10-01','end':'2026-10-01'})
    assert previous['summary']['lines_added']==0
    assert previous['summary']['change_coverage']=='partial'


def test_portable_history_boundary_is_exact():
    parser=SessionParser();offset=0
    for raw in [log(),token(100)]:
        for line in raw.splitlines(keepends=True):offset+=len(line);parser.consume(line,offset)
    fact=portable_fact(parser.fact())
    base={'thread_id':'chat','end_byte_offset':offset,'end_ordinal_exclusive':fact['record_count']}
    seed,error=resolve_history_seed({'history_base':base},{'chat':fact})
    assert error is None and seed['usage']['total_tokens']==110
    base['end_byte_offset']-=1
    assert resolve_history_seed({'history_base':base},{'chat':fact})[1]=='history_base_boundary_mismatch'


def test_child_replay_excluded_when_parent_arrives_late(indexed):
    store,root,_=indexed
    # The copied token event retains its original pre-spawn timestamp.
    child_log=log('child','parent').replace(T.isoformat().encode(),(T+timedelta(seconds=5)).isoformat().encode(),1)
    child=child_log+token(100)+token(150,6,last=50)
    (root/'child.jsonl').write_bytes(child);refresh(store)
    (root/'parent.jsonl').write_bytes(log('parent')+token(100));refresh(store)
    assert dashboard(store)['summary']['total_tokens']==165
    assert dashboard(store)['summary']['chats']==1


def test_timezone_and_unknown_model_price(indexed):
    store,root,_=indexed
    (root/'time.jsonl').write_bytes(log()+event('turn_context',{'model':'unpriced-model'},3)+event('event_msg',{'type':'token_count','info':{'last_token_usage':{'input_tokens':40,'output_tokens':10,'total_tokens':50}}},4))
    refresh(store);data=dashboard(store)
    assert data['summary']['total_tokens']==50 and data['summary']['priced_percent']==0
    assert data['summary']['cost']==0
