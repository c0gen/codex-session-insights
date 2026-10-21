"""Prepare a separate candidate from already preserved offline evidence."""
import argparse
import json
from pathlib import Path

from codex_insights.index_recovery import prepare, compare, integrity
from codex_insights.ingestion import refresh
from codex_insights.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh', action='store_true', help='Replay available local logs in the candidate only')
    args = parser.parse_args()
    report = prepare(args.evidence, args.output)
    print(json.dumps({'phase': 'prepared', 'base': report['base']}), flush=True)
    store = Store(args.output)
    if args.refresh:
        try:
            report['refresh'] = refresh(store)
        except BaseException:
            report.update(state='replay_interrupted', promotion_allowed=False)
            (args.output / 'recovery-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            raise
    report['preservation'] = []
    for path in args.evidence.glob('insights*.sqlite3'):
        if report['checks'][path.name]['ok']:
            result = compare(path, store.path)
            report['preservation'].append(result)
            print(json.dumps(result), flush=True)
    report['candidate_integrity'] = integrity(store.path)
    report['state'] = 'validated' if report['candidate_integrity']['ok'] and all(r['preserved'] for r in report['preservation']) else 'needs_review'
    # Evidence predating the incident cannot certify settings/choices made later.
    report['promotion_allowed'] = False
    report['note'] = 'No live data was replaced. Verify incident-time history and user metadata before promotion.'
    (args.output / 'recovery-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'phase': report['state'], 'promotion_allowed': False}), flush=True)


if __name__ == '__main__':
    main()
