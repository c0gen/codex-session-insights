"""Cache metrics use reconciled counters and the effective cost rates."""
import pytest

from codex_insights.accounting.pricing import MODEL_RATE_RECORDS, estimate_token_cost
from codex_insights.ingestion import refresh
from codex_insights.projection import ensure_projection, PROJECTION_VERSION
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot
from codex_insights.usage_metrics import subset_percent
from conftest import event, log, token


@pytest.mark.parametrize('n,d,result', [(0,0,None),(1,0,None),(2,1,None),(-1,3,None),(0,3,0),(6,10,60),(1,4,25)])
def test_subset_ratio(n,d,result):
    assert subset_percent(n,d) == result


@pytest.mark.parametrize('model,at,tier,fast,request_input,difference', [
    ('gpt-5.6-sol','2026-08-20',None,0,100,4.5),
    ('gpt-5.6-sol','2026-08-21',None,0,100,3.6),
    ('gpt-5.6-sol','2026-08-21','priority',0,300000,14.4),
    ('gpt-5.6-sol','2026-08-21','flex',0,300000,3.6),
    ('gpt-5.6-sol','2026-08-21',None,.35,300000,9.72),
    ('gpt-5.6-sol','2026-07-20','priority',0,300000,9),
    ('gpt-5.6-sol','2026-07-20',None,.35,300000,9),
    ('gpt-5.3-codex','2026-10-01','flex',0,100,1.575),
])
def test_effective_rates_and_counterfactual(model,at,tier,fast,request_input,difference):
    usage = dict(input_tokens=1000000,cached_input_tokens=600000,cache_write_input_tokens=100000,output_tokens=200000,reasoning_output_tokens=50000)
    kwargs = dict(at=at,service_tier=tier,service_tier_logged=bool(tier),assumed_fast_share=fast,request_input_tokens=request_input)
    price = estimate_token_cost(model,usage,**kwargs)
    counterfactual = estimate_token_cost(model,{**usage,'cached_input_tokens':0},**kwargs)
    rates = price['rates_per_million']
    assert rates['input'] - rates['cached_input'] == pytest.approx(difference)
    assert price['cache_discount_usd'] == pytest.approx(.6*(rates['input']-rates['cached_input']))
    assert price['usd'] + price['cache_discount_usd'] == pytest.approx(counterfactual['usd'])


def test_fixture_rates_signed_and_no_rounding(monkeypatch):
    monkeypatch.setitem(MODEL_RATE_RECORDS,'fixture',[dict(start=None,end=None,rates=dict(input=2,cached_input=.2,output=10,pricing_model='fixture'))])
    usage = dict(input_tokens=1000000,cached_input_tokens=600000,output_tokens=200000)
    assert estimate_token_cost('fixture',usage)['cache_discount_usd'] == pytest.approx(1.08)
    assert estimate_token_cost('fixture',dict(input_tokens=1,cached_input_tokens=1))['cache_discount_usd'] == pytest.approx(.0000018)
    MODEL_RATE_RECORDS['fixture'][0]['rates']['cached_input']=3
    assert estimate_token_cost('fixture',usage)['cache_discount_usd'] == pytest.approx(-.6)


def write_usage(root, sid, model, usage):
    (root/(sid+'.jsonl')).write_bytes(log(sid)+event('turn_context',{'model':model},2)+event('event_msg',{'type':'token_count','info':{'total_token_usage':usage,'last_token_usage':usage}},3))


def test_aggregate_partial_unknown_zero_and_record_bucket_parity(indexed,monkeypatch):
    store,root,_=indexed
    monkeypatch.setitem(MODEL_RATE_RECORDS,'fixture',[dict(start=None,end=None,rates=dict(input=2,cached_input=.2,output=10,pricing_model='fixture'))])
    usage=dict(input_tokens=1000000,cached_input_tokens=600000,output_tokens=200000,reasoning_output_tokens=50000,total_tokens=1200000)
    write_usage(root,'known','fixture',usage)
    refresh(store)
    expected=dict(cache_reuse_percent=60,reasoning_share_percent=25,cache_discount_usd=1.08,cache_discount_priced_tokens=600000,cache_discount_total_tokens=600000,cache_discount_coverage_percent=100)
    expected['reasoning_share_basis'] = dict(reasoning_tokens=50000, output_tokens=200000, included_responses=1, total_responses=1)
    assert dashboard(store)['usage_metrics']==expected
    write_usage(root,'unknown','unpublished',usage)
    refresh(store)
    partial=dashboard(store)['usage_metrics']
    assert partial=={**expected,'cache_discount_total_tokens':1200000,'cache_discount_coverage_percent':50,
        'reasoning_share_basis': dict(reasoning_tokens=100000, output_tokens=400000, included_responses=2, total_responses=2)}
    store.set_setting('bucket_version',None)
    assert dashboard(store)['usage_metrics']==partial
    unknown=dashboard(store,{'model':'unpublished'})['usage_metrics']
    assert unknown['cache_discount_usd'] is None
    assert unknown['cache_discount_coverage_percent']==0
    empty=dashboard(store,{'range':'custom','start':'2020-01-01','end':'2020-01-01'})['usage_metrics']
    assert empty['cache_discount_usd'] is None
    assert empty['cache_discount_coverage_percent'] is None
    assert empty['cache_reuse_percent'] is None
    assert empty['reasoning_share_percent'] is None
    write_usage(root,'zero','zero-only',{**usage,'cached_input_tokens':0,'reasoning_output_tokens':0})
    refresh(store)
    zero=dashboard(store,{'model':'zero-only'})['usage_metrics']
    assert zero['cache_discount_usd']==0
    assert zero['cache_reuse_percent']==0
    assert zero['reasoning_share_percent']==0
    assert zero['cache_discount_coverage_percent'] is None


def test_real_schema_upgrade_deferred_offline_import_and_rollback(indexed,tmp_path,monkeypatch):
    from codex_insights import projection
    store,root,_=indexed
    (root/'chat.jsonl').write_bytes(log()+token(100))
    refresh(store)
    expected=dashboard(store)
    snapshot=tmp_path/'copy.codex-insights'
    export_snapshot(store,snapshot)
    target=Store(tmp_path/'imported')
    import_snapshot(target,snapshot)
    for current in (store,target):
        with current.connect() as db:
            for table in ('records','metric_buckets'):
                for col in ('cache_discount','cache_priced'):
                    db.execute(f'ALTER TABLE {table} DROP COLUMN {col}')
        current.set_setting('projection_version',1)
        reopened=Store(current.directory)
        pending=dashboard(reopened)
        assert pending['summary']==expected['summary']
        assert pending['usage_metrics']['cache_discount_usd'] is None
        assert pending['usage_metrics']['cache_discount_coverage_percent']==0
        assert pending['daily_sessions']==[]
        before=current.setting('data_revision')
        original=projection.project_segments
        def fail(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('interrupted')
        with monkeypatch.context() as patch:
            patch.setattr(projection,'project_segments',fail)
            with pytest.raises(RuntimeError):
                ensure_projection(reopened)
        assert reopened.setting('projection_version')==1
        assert reopened.setting('data_revision')==before
        assert dashboard(reopened)['usage_metrics']==pending['usage_metrics']
        if current is store:
            root.rename(root.with_name('offline'))
            assert refresh(reopened)['bytes_read']==0
        else:
            assert import_snapshot(reopened,snapshot)['status']=='unchanged'
        assert reopened.setting('projection_version')==PROJECTION_VERSION
        assert dashboard(reopened)['usage_metrics']==expected['usage_metrics']
        assert dashboard(reopened)['daily_sessions']==expected['daily_sessions']
        assert not ensure_projection(reopened)
        assert reopened.setting('data_revision')==before+1



def test_weighted_ratios_invalid_subsets_and_small_discounts(indexed):
    store,root,_=indexed
    for sid,inp,cached,out,reason in [('a',100,100,10,0),('b',900,0,90,45)]:
        write_usage(root,sid,'gpt-5.3-codex',dict(input_tokens=inp,cached_input_tokens=cached,output_tokens=out,reasoning_output_tokens=reason,total_tokens=inp+out))
    refresh(store)
    metrics=dashboard(store)['usage_metrics']
    assert metrics['cache_reuse_percent']==10
    assert metrics['reasoning_share_percent']==45
    assert metrics['cache_discount_usd']==pytest.approx(.0001575)
    write_usage(root,'invalid','invalid',dict(input_tokens=1,cached_input_tokens=2,output_tokens=1,reasoning_output_tokens=2,total_tokens=2))
    refresh(store)
    invalid=dashboard(store,{'model':'invalid'})
    assert invalid['summary']['cached_tokens']==2
    assert invalid['summary']['reasoning_tokens']==2
    assert invalid['usage_metrics']['cache_reuse_percent'] is None
    assert invalid['usage_metrics']['reasoning_share_percent'] is None


def test_prerelease_and_context_boundary():
    usage=dict(input_tokens=100,cached_input_tokens=50)
    assert estimate_token_cost('gpt-6-sol',usage,at='2026-09-21') is None
    short=estimate_token_cost('gpt-6-sol',usage,at='2026-09-22',request_input_tokens=272000)
    long=estimate_token_cost('gpt-6-sol',usage,at='2026-09-22',request_input_tokens=272001)
    assert short['cache_discount_usd']==pytest.approx(.00009)
    assert long['cache_discount_usd']==pytest.approx(.00018)


def test_report_retains_public_metrics_without_private_fields(indexed,tmp_path,monkeypatch):
    import json
    from codex_insights import report
    store,root,_=indexed
    (root/'chat.jsonl').write_bytes(log()+token(100))
    refresh(store)
    data=dashboard(store)
    ui=tmp_path/'ui';ui.mkdir()
    (ui/'index.html').write_text('<html><head></head><body></body></html>')
    monkeypatch.setattr(report,'ui_directory',lambda:ui)
    destination=tmp_path/'report.html'
    report.export_html(data,destination)
    html=destination.read_text()
    payload=json.loads(html.split('window.__INSIGHTS_REPORT__=',1)[1].split(';</script>',1)[0])
    assert payload['usage_metrics']==data['usage_metrics']
    assert payload['daily_sessions']==data['daily_sessions']
    assert payload['cache_rate_timeline']==data['cache_rate_timeline']
    assert set(payload['daily_sessions'][0])=={'day','chats','subagents','system_agents'}
    assert 'PRIVATE PROMPT' not in html
    assert str(root) not in html

def test_dashboard_metrics_share_read_snapshot(indexed,monkeypatch):
    import json
    from codex_insights import queries
    store,root,_=indexed
    (root/'chat.jsonl').write_bytes(log()+token(100))
    refresh(store)
    expected=dashboard(store)
    original=queries.query_usage_metrics
    def concurrent_update(db,table,where,params,summary,discount=None):
        with store.connect() as writer:
            for name in ('records','metric_buckets'):
                writer.execute(f"UPDATE {name} SET cache_discount=9,input=9999,cached=99 WHERE kind='usage'")
            writer.execute("UPDATE settings SET value=? WHERE key='data_revision'",(json.dumps(expected['revision']+1),))
        return original(db,table,where,params,summary,discount)
    monkeypatch.setattr(queries,'query_usage_metrics',concurrent_update)
    observed=dashboard(store)
    assert observed['usage_metrics']==expected['usage_metrics']
    assert observed['daily_sessions']==expected['daily_sessions']
    assert observed['cache_rate_timeline']==expected['cache_rate_timeline']
    assert observed['revision']==expected['revision']

def test_reconciled_discount_excludes_replay_and_copied_sources(indexed,tmp_path):
    store,root,_=indexed
    parent=log('parent')+token(100)
    child=(event('session_meta',{'id':'child','source':{'subagent':{'thread_spawn':{'parent_thread_id':'parent'}}}},5)
           +event('turn_context',{'model':'gpt-5.3-codex'},5)+token(100,3)+token(150,6,last=50))
    (root/'parent.jsonl').write_bytes(parent)
    (root/'child.jsonl').write_bytes(child)
    (root/'copy.jsonl').write_bytes(child)
    copied=tmp_path/'copied';copied.mkdir()
    (copied/'child.jsonl').write_bytes(child)
    store.add_source(copied)
    refresh(store)
    data=dashboard(store)
    assert data['summary']['total_tokens']==165
    assert data['usage_metrics']['cache_discount_total_tokens']==75
    assert data['usage_metrics']['cache_discount_priced_tokens']==75
    assert data['usage_metrics']['cache_discount_usd']==pytest.approx(75*1.575/1000000)
    assert sum(row['cached_tokens'] for row in data['cache_rate_timeline']) == 75
    assert sum(row['input_tokens'] for row in data['cache_rate_timeline']) == 150
    assert data['daily_sessions']==[dict(day='2026-10-01',chats=1,subagents=1,system_agents=0)]
