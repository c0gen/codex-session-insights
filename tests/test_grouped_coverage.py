"""Grouped queries must match individual coverage queries and avoid N+1 scans."""
from contextlib import contextmanager
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from codex_insights.buckets import GROUP, SELECT
from codex_insights.grouped_coverage import coverage_groups
from codex_insights.indexed_tokens import indexed_token_totals
from codex_insights.providers import LABELS
from codex_insights.providers.schema import coverage
from codex_insights.queries import dashboard, filter_clause
from scripts.benchmark_project_filters import seed_store


@pytest.fixture
def mixed_groups(tmp_path):
    store = seed_store(tmp_path / 'data', projects=4, sessions=16)
    with store.connect() as db:
        db.execute("INSERT INTO sources(id,label,kind,provider) VALUES('other','Other','import','mixed')")
        for i in range(16):
            provider = tuple(LABELS)[i % 3]
            source = 'fixture' if i % 2 else 'other'
            day = '2026-10-01' if i % 2 else '2026-10-02'
            db.execute('UPDATE canonical SET provider=?,source_id=? WHERE segment_id=?', (provider, source, f's{i}'))
            db.execute('UPDATE records SET provider=?,source_id=?,model=?,day=?,ts=?,known_total=?,known_cached=?,known_reasoning=? WHERE segment_id=?',
                       (provider, source, 'fixture-model' if i % 2 else 'other-model', day, day + 'T12:00:00+00:00',
                        int(i % 4 != 0), int(i % 2 == 0), int(i % 3 == 0), f's{i}'))
        # A merged group, known zero counters, and a session without usage.
        db.execute("UPDATE project_memberships SET group_id='p0' WHERE project_id='p2'")
        db.execute("UPDATE records SET total=0,input=0,output=0,known_total=1 WHERE segment_id='s0'")
        db.execute("UPDATE records SET kind='presence',total=0,known_total=0 WHERE segment_id='s5'")
        repeated = dict(db.execute("SELECT * FROM records WHERE segment_id='s3'").fetchone())
        repeated.update(event_id='repeated', total=7, known_total=0)
        db.execute('INSERT INTO records(' + ','.join(repeated) + ') VALUES(' + ','.join('?' for _ in repeated) + ')', tuple(repeated.values()))
        # Repeated segments of one session must still count as one session.
        db.execute("INSERT INTO canonical(segment_id,session_id,source_id,project_id,project_label,category,trace_count,diagnostic) VALUES('copy','s0','other','p0','Project 0','top_level',1,'{}')")
        db.execute("INSERT INTO session_projects VALUES('copy','p0')")
        db.execute("INSERT INTO records(event_id,segment_id,session_id,source_id,project_id,kind,ts,day,provider,total,known_total) VALUES('copy','copy','s0','other','p0','usage','2026-10-02T12:00:00+00:00','2026-10-02','codex',7,1)")
        # Preserve the old provider-total behavior even for an unmatched record.
        db.execute("INSERT INTO records(event_id,segment_id,session_id,kind,ts,day,provider,total,known_total) VALUES('orphan','orphan','orphan','usage','2026-10-02T12:00:00+00:00','2026-10-02','codex',9,1)")
        db.execute('DELETE FROM metric_buckets')
        db.execute('INSERT INTO metric_buckets SELECT ' + SELECT + ' FROM records GROUP BY ' + GROUP)
    return store


@pytest.mark.parametrize('table', ['records', 'metric_buckets'])
@pytest.mark.parametrize('group', ['project', 'provider'])
@pytest.mark.parametrize('filters', [
    {}, {'project_id': 'p0'}, {'provider': 'codex'}, {'model': 'fixture-model'},
    {'source_id': 'other'}, {'range': 'custom', 'start': '2026-10-02', 'end': '2026-10-02'},
    {'range': 'custom', 'start': '2020-01-01', 'end': '2020-01-01'},
    {'project_id': 'p0', 'source_id': 'other', 'model': 'other-model', 'provider': 'codex'},
])
def test_grouped_coverage_matches_individual_queries(mixed_groups, table, group, filters):
    where, params, _ = filter_clause(filters, ZoneInfo('UTC'), date(2026, 10, 15))
    with mixed_groups.connect() as db:
        grouped = coverage_groups(db, table, where, params, group)
        if group == 'project':
            keys = {r[0] for r in db.execute('SELECT DISTINCT g.project_id FROM ' + table + ' r JOIN project_sessions g ON g.segment_id=r.segment_id WHERE ' + where, params)}
            condition = 'r.segment_id IN (SELECT segment_id FROM project_sessions WHERE project_id=?)'
        else:
            keys = {r[0] for r in db.execute('SELECT DISTINCT r.provider FROM ' + table + ' r WHERE ' + where, params)}
            condition = 'r.provider=?'
        assert set(grouped) == keys
        for key, result in grouped.items():
            clause, arguments = where + ' AND ' + condition, [*params, key]
            assert {k: v for k, v in result.items() if k != 'total_tokens'} == coverage(db, table, clause, arguments)
            assert result['total_tokens'] == db.execute('SELECT coalesce(sum(r.total),0) FROM ' + table + ' r WHERE ' + clause, arguments).fetchone()[0]
        if group == 'provider':
            expected = {}
            for provider in LABELS:
                clause, arguments = where + ' AND r.provider=?', [*params, provider]
                state = coverage(db, table, clause, arguments)
                tokens = db.execute('SELECT coalesce(sum(r.total),0) FROM ' + table + ' r WHERE ' + clause, arguments).fetchone()[0]
                expected[provider] = {'state': state['state'], 'sessions': state['sessions'],
                                      'total_tokens': tokens if state['state'] != 'unavailable' else None}
            assert indexed_token_totals(db, table, where, params) == expected


def test_dashboard_query_count_is_independent_of_project_count(tmp_path, monkeypatch):
    counts = []
    for projects in (1, 40):
        store = seed_store(tmp_path / str(projects), projects=projects, sessions=160)
        original = store.connect
        statements = []

        @contextmanager
        def traced():
            with original() as db:
                db.set_trace_callback(statements.append)
                yield db

        monkeypatch.setattr(store, 'connect', traced)
        result = dashboard(store)
        assert len(result['projects']) == projects
        selects = [sql for sql in statements if sql.startswith('SELECT')]
        assert len([sql for sql in selects if ' group_id,' in sql]) == 2
        counts.append(len(selects))
    assert counts[0] == counts[1]
