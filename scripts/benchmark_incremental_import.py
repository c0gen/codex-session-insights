"""Measure a one-percent archive delta against the preserved full importer.

The supplied index must be a disposable copy. Input archives are read-only;
preparation, copy and one-time ledger backfill are reported separately.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import zipfile

from codex_insights.codec import dumps, loads
from codex_insights.dashboard_cache import DashboardCache
from codex_insights.storage import Store
from codex_insights.transfers import import_snapshot, _legacy_import_snapshot
from codex_insights import transfer_publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, help='Existing disposable reference accepting the same base revision')
    parser.add_argument('--baseline-results', type=Path, help='Reuse equivalent full-import timing on the adjacent revision; explicitly labeled')
    args = parser.parse_args()
    if not args.index.resolve().is_relative_to(Path('.local-data').resolve()):
        raise ValueError('The index must be a disposable .local-data copy')
    args.output.mkdir(parents=True, exist_ok=False)
    store = Store(args.index)
    prepared = time.perf_counter()
    import_snapshot(store, args.archive)
    # Legacy acceptance may need one-time ledger backfill; do it before routine
    # delta timing, as a normal upgraded app would after accepting that source.
    import_snapshot(store, args.archive)
    preparation = time.perf_counter() - prepared
    with zipfile.ZipFile(args.archive) as source:
        manifest = json.loads(source.read('manifest.json'))
        changed = max(1, math.ceil(manifest['fact_count'] * .01))
        checksum = hashlib.sha256()
        raw = args.output / 'facts.jsonl'
        with source.open('facts.jsonl') as incoming, raw.open('wb') as outgoing:
            for index, line in enumerate(incoming):
                if index < changed:
                    value = loads(line.decode('utf-8'))
                    value['accepted']['project_label'] += ' [benchmark]'
                    line = (dumps(value) + '\n').encode('utf-8')
                checksum.update(line)
                outgoing.write(line)
        manifest.update(revision=manifest['revision'] + 1, facts_sha256=checksum.hexdigest())
        delta = args.output / 'delta.codex-insights'
        with zipfile.ZipFile(delta, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('manifest.json', json.dumps(manifest))
            archive.write(raw, 'facts.jsonl')
    baseline_directory = args.reference or args.output / 'full'
    if not args.reference:
        baseline_directory.mkdir()
    wal = Path(str(store.path) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Disposable source still has a WAL; close its readers first')
    if not args.reference:
        shutil.copyfile(store.path, baseline_directory / 'insights.sqlite3')
    cache = DashboardCache(store)
    cache.read({'_view': 'overview'})
    published = []
    original = transfer_publication.publish
    def publication(*values, **options):
        result = original(*values, **options)
        if result is True:
            published.append(time.perf_counter())
        return result
    transfer_publication.publish = publication
    store.cooperate = lambda: None
    started = time.perf_counter()
    incremental = import_snapshot(store, delta)
    incremental_seconds = time.perf_counter() - started
    if incremental['changed'] != changed or incremental['added'] or incremental['removed']:
        raise AssertionError('Benchmark was not a steady one-percent accepted-input delta: ' + str(incremental))
    print(json.dumps({'phase': 'incremental_complete', 'seconds': incremental_seconds, 'counts': incremental}), flush=True)
    fresh = cache.read({'_view': 'overview', '_background': True, '_retry': True})
    commit_to_metrics = time.perf_counter() - published[-1]
    cache.close()
    reference = Store(baseline_directory)
    reference.cooperate = lambda: None
    if args.baseline_results:
        prior = json.loads(args.baseline_results.read_text(encoding='utf-8'))
        if prior['sessions_in_archive'] != manifest['fact_count'] or prior['changed_sessions'] != changed:
            raise ValueError('Prior baseline has a different workload')
        baseline_seconds = prior['full_import_seconds']
    else:
        started = time.perf_counter()
        baseline = _legacy_import_snapshot(reference, delta)
        baseline_seconds = time.perf_counter() - started
        print(json.dumps({'phase': 'full_import_complete', 'seconds': baseline_seconds}), flush=True)
    from codex_insights.queries import dashboard
    expected, actual = dashboard(reference), dashboard(store)
    for key in ('summary','timeline','projects','models','heatmap','tiers','efforts','agents','daily_sessions','cache_rate_timeline','usage_metrics'):
        left, right = expected[key], actual[key]
        if args.baseline_results and key == 'projects':
            left = [{k:v for k,v in row.items() if k != 'name'} for row in left]
            right = [{k:v for k,v in row.items() if k != 'name'} for row in right]
        if left != right:
            raise AssertionError('Full importer parity mismatch: ' + key)
    result = {'sessions_in_archive': manifest['fact_count'], 'changed_sessions': changed,
              'preparation_and_backfill_seconds': round(preparation, 3),
              'incremental_seconds': round(incremental_seconds, 3),
              'full_import_seconds': round(baseline_seconds, 3),
              'overall_speedup': round(baseline_seconds / incremental_seconds, 2),
              'commit_to_active_metrics_seconds': round(commit_to_metrics, 3),
              'incremental': incremental, 'parity': True, 'runs': 1,
              'comparison': 'Equivalent full-import workload on adjacent revision; project-label-only delta' if args.baseline_results else 'Same archive on identical accepted bases',
              'baseline_results': str(args.baseline_results) if args.baseline_results else None}
    (args.output / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
