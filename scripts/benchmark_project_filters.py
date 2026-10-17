"""Compare project-filter queries using a disposable, synthetic usage index."""
import argparse
import importlib.util
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from codex_insights.buckets import GROUP, SELECT
from codex_insights.projection import PROJECTION_VERSION
from codex_insights.queries import dashboard
from codex_insights.storage import Store


def seed_store(directory, projects=100, sessions=10000):
    store = Store(directory)
    store.set_setting('timezone', 'UTC')
    store.set_setting('projection_version', PROJECTION_VERSION)
    store.set_setting('project_groups_version', 1)
    with store.connect() as db:
        db.execute("INSERT INTO sources(id,label,kind,provider) VALUES('fixture','Synthetic','import','codex')")
        db.executemany('INSERT INTO project_memberships VALUES(?,?,?)',
                       [(f'p{i}', f'Project {i}', f'p{i}') for i in range(projects)])
        db.executemany('INSERT INTO canonical(segment_id,session_id,source_id,project_id,project_label,category,trace_count,diagnostic) VALUES(?,?,?,?,?,?,?,?)',
                       [(f's{i}', f's{i}', 'fixture', f'p{i % projects}', f'Project {i % projects}', 'top_level', 1, '{}') for i in range(sessions)])
        db.executemany('INSERT INTO session_projects VALUES(?,?)',
                       [(f's{i}', f'p{i % projects}') for i in range(sessions)])
        columns = 'event_id,segment_id,session_id,source_id,project_id,kind,ts,day,model,total,input,output,priced,known_total,known_input,known_output'
        db.executemany('INSERT INTO records(' + columns + ') VALUES(' + ','.join('?' for _ in columns.split(',')) + ')',
                       [(f'e{i}', f's{i}', f's{i}', 'fixture', f'p{i % projects}', 'usage',
                         '2026-10-01T12:00:00+00:00', '2026-10-01', 'fixture-model', 110, 100, 10, 1, 1, 1, 1)
                        for i in range(sessions)])
        db.execute('INSERT INTO metric_buckets SELECT ' + SELECT + ' FROM records GROUP BY ' + GROUP)
    return store


def load_baseline(directory):
    def module(name):
        spec = importlib.util.spec_from_file_location('codex_insights._baseline_' + name, directory / (name + '.py'))
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    queries = module('queries')
    queries.indexed_token_totals = module('indexed_tokens').indexed_token_totals
    return queries.dashboard


def measure(store, query, filters, runs):
    timings = []
    for _ in range(runs):
        started = perf_counter()
        value = query(store, filters)
        timings.append(perf_counter() - started)
    return {'median_seconds': round(median(timings), 4), 'project_count': len(value['projects'])}, value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--projects', type=int, default=100)
    parser.add_argument('--sessions', type=int, default=10000)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if min(args.projects, args.sessions, args.runs) < 1:
        parser.error('Projects, sessions and runs must be positive.')
    with TemporaryDirectory(prefix='insights-filter-benchmark-') as directory:
        store = seed_store(directory, args.projects, args.sessions)
        queries = {'current': dashboard}
        if args.baseline:
            queries = {'baseline': load_baseline(args.baseline), **queries}
        print(json.dumps({'projects': args.projects, 'sessions': args.sessions, 'runs': args.runs}), flush=True)
        for label, filters in [('project', {'project_id': 'p0'}), ('all_projects', {})]:
            expected = None
            for version, query in queries.items():
                result, value = measure(store, query, filters, args.runs)
                # generated_at is expected to differ across measurements.
                comparable = {k: v for k, v in value.items() if k != 'generated_at'}
                if expected is None:
                    expected = comparable
                else:
                    assert comparable == expected, 'Optimization changed dashboard results'
                print(json.dumps({'case': label, 'version': version, **result}), flush=True)


if __name__ == '__main__':
    main()
