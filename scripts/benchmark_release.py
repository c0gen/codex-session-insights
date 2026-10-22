"""Measure interactive reads on a disposable copy of a preserved index."""
import argparse
import codex_insights  # Select the prepared runtime before importing sqlite3.
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import shutil
import time

from codex_insights.dashboard_cache import DashboardCache
from codex_insights.local_token_burn import LocalTokenBurn
from codex_insights.queries import dashboard
from codex_insights.storage import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixture', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--runs', type=int, default=5)
parser.add_argument('--offline-fixture', action='store_true', help='Copy a closed, immutable fixture with no WAL')
parser.add_argument('--reuse-copy', action='store_true', help='Remeasure an existing disposable benchmark copy')
args = parser.parse_args()
if args.reuse_copy:
    if not (args.output / 'benchmark.json').is_file() or (args.output / 'insights.sqlite3').resolve() == args.fixture.resolve():
        raise ValueError('Reuse requires a separate existing benchmark copy')
else:
    args.output.mkdir(parents=True, exist_ok=False)
def copy_offline():
    original = args.fixture.stat()
    wal = Path(str(args.fixture) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Offline fixture has a WAL; use the SQLite backup mode')
    shutil.copyfile(args.fixture, args.output / 'insights.sqlite3')
    after = args.fixture.stat()
    if (after.st_size, after.st_mtime_ns) != (original.st_size, original.st_mtime_ns) or (wal.exists() and wal.stat().st_size):
        raise ValueError('Fixture changed while copying; discard the benchmark copy')
if args.reuse_copy:
    pass
elif args.offline_fixture:
    copy_offline()
else:
    with closing(sqlite3.connect(args.fixture.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(args.output / 'insights.sqlite3')) as target:
            started_copy = time.monotonic()
            last_progress = [started_copy]
            def copy_progress(status, remaining, total):
                if time.monotonic() - started_copy > 120:
                    raise TimeoutError('Fixture copy exceeded two minutes; source left unchanged')
                if time.monotonic() - last_progress[0] > 15:
                    print(json.dumps({'copy_pages_remaining': remaining, 'copy_pages': total, 'status': status}), flush=True)
                    last_progress[0] = time.monotonic()
            source.backup(target, pages=1024, progress=copy_progress)
started = time.perf_counter()
store = Store(args.output)
from codex_insights.buckets import current, rebuild_buckets
if not current(store.setting('bucket_version')):
    rebuild_buckets(store, resume=True)
result = {'fixture': str(args.fixture), 'sqlite': sqlite3.sqlite_version,
          'migration_seconds': round(time.perf_counter() - started, 3), 'runs': args.runs}
def measure(label, action):
    readings = []
    for _ in range(args.runs):
        start = time.perf_counter()
        value = action()
        readings.append(time.perf_counter() - start)
    readings.sort()
    result[label] = {'p95_seconds': round(readings[math.ceil(len(readings) * .95) - 1], 4),
                     'min_seconds': round(readings[0], 4)}
    print(json.dumps({label: result[label]}), flush=True)
    return value
from codex_insights.dashboard_aggregates import SharedAggregates
def fresh(view):
    store._dashboard_aggregates = SharedAggregates(32)
    return dashboard(store, {'_view': view})
full = measure('full_dashboard', lambda: fresh('full'))
overview = measure('overview', lambda: fresh('overview'))
measure('projects', lambda: fresh('projects'))
measure('usage', lambda: fresh('usage'))
measure('sources', lambda: fresh('sources'))
assert overview['summary'] == full['summary']
assert overview['timeline'] == full['timeline']
cache = DashboardCache(store)
cache.read({'_view': 'overview'})
measure('cached_overview_query', lambda: cache.read({'_view': 'overview'}))
measure('cached_bootstrap', lambda: cache.snapshot.load({}))
cache.close()
reader = LocalTokenBurn(store)
reader.read_rates()
measure('local_rates', reader.read_rates)
with store.connect() as db:
    segment = db.execute("SELECT segment_id FROM canonical WHERE provider='codex' LIMIT 1").fetchone()[0]
    result['codex_update_dependencies'] = len(store.related_segments(db, {segment}))
    result['sessions'] = db.execute('SELECT count(*) FROM canonical').fetchone()[0]
    result['records'] = db.execute('SELECT count(*) FROM records').fetchone()[0]
(args.output / 'benchmark.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result), flush=True)
