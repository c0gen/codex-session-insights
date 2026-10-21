"""Real scheduler/watcher latency with 10,000 already indexed historical files."""
import argparse
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from codex_insights.ingestion import refresh
from codex_insights.jobs import Jobs
from codex_insights.live_index import LivePaths
from codex_insights.storage import Store


def event(kind, payload, at='2026-01-01T00:00:00+00:00'):
    return (json.dumps({'type': kind, 'timestamp': at, 'payload': payload}) + '\n').encode()


def fixture(directory):
    directory = directory.resolve()
    root = directory / 'sessions'
    root.mkdir(parents=True)
    store = Store(directory / 'index')
    sid = store.add_source(root)
    content = event('session_meta', {'id': 'historical', 'cwd': 'synthetic'})
    first = root / 'old-00000.jsonl'
    first.write_bytes(content)
    refresh(store)
    with store.connect() as db:
        cached = dict(db.execute('SELECT * FROM files').fetchone())
    # All files are byte-identical copies of the already verified history.
    # Seed checkpoints in one transaction so setup does not measure first indexing.
    values, health = [], []
    for i in range(1, 10000):
        path = root / f'old-{i:05}.jsonl'
        path.write_bytes(content)
        stat = path.stat()
        values.append((sid, str(path), cached['offset'], stat.st_mtime_ns, stat.st_size,
                       cached['anchor'], cached['state'], cached['parser_version']))
        health.append((sid, str(path), time.time(), None, 0, None))
    with store.connect() as db:
        db.executemany('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)', values)
        db.executemany('INSERT INTO file_coverage VALUES(?,?,?,?,?,?)', health)
    active = root / 'active.jsonl'
    active.write_bytes(event('session_meta', {'id': 'active', 'cwd': 'synthetic'}))
    refresh(store)
    return store, root, sid, active


def measure(directory, watchers, workload='idle', reconnect=False):
    store, root, sid, active = fixture(directory)
    if workload != 'idle':
        from copy import deepcopy
        from codex_insights.codec import unpack, digest
        from codex_insights.projection import project_segments
        other = store.add_source(directory / 'synthetic-snapshot', provider='claude_code', kind='import')
        with store.connect() as db:
            base = unpack(db.execute('SELECT fact FROM canonical LIMIT 1').fetchone()[0])
            segments = []
            # Reconnect checks need maintenance to outlast the five-second
            # watcher coalescing window, even on a fast SSD.
            for i in range(2400 if reconnect else 600):
                fact = deepcopy(base)
                provider = 'claude_code' if i % 10 == 0 else 'codex'
                identity = f'historical-{i}'
                fact.update(id=f'{provider}:{identity}', provider=provider,
                            segment_id=digest([provider, identity, 'transcript']) if provider != 'codex'
                            else digest([f'{provider}:{identity}', base['metadata_timestamp']]))
                from codex_insights.transfers import validate_fact
                validate_fact(fact)
                store.put_candidate(db, other if provider == 'claude_code' else sid, fact)
                store.choose_canonical(db, fact['segment_id'])
                segments.append(fact['segment_id'])
            project_segments(store, db, segments)
    if reconnect:
        offline = root.with_name('disconnected-sessions')
        assert offline.resolve().is_relative_to(directory.resolve())
        root.rename(offline)
        refresh(store)
        assert next(s for s in store.sources() if s['id'] == sid)['status'] == 'Offline'
        offline.rename(root)
    store.live_paths = LivePaths()
    if not reconnect:
        store.live_paths.begin_discovery()
    jobs = Jobs()
    jobs.next_automatic = jobs.clock() + 5
    written, observed, failures = {}, {}, []
    reconnected_during_maintenance = False
    observer = None
    class Events(FileSystemEventHandler):
        def on_any_event(self, value):
            store.live_paths.event(sid, root, value)
            if value.event_type in {'modified', 'created', 'moved', 'deleted'}:
                jobs.dirty.set()
    if watchers:
        observer = Observer()
        observer.schedule(Events(), str(root), recursive=True)
        observer.start()
    if workload != 'idle':
        from codex_insights.cooperative import live_work
        def maintenance():
            store.maintenance_cancel = jobs.cancel
            try:
                with live_work(store, jobs.cancel):
                    if workload == 'rebuild':
                        from codex_insights.projection import rebuild_projection
                        rebuild_projection(store)
                    elif workload == 'backfill':
                        refresh(store, cancel=jobs.cancel, rebuild=True)
                    else:
                        from codex_insights.transfers import export_snapshot, import_snapshot
                        incoming = directory / 'incoming.codex-insights'
                        export_snapshot(store, incoming)
                        import_snapshot(store, incoming, cancel=jobs.cancel)
            finally:
                store.maintenance_cancel = None
        jobs.submit('Historical maintenance', maintenance, origin='user', key='maintenance', cancelable=True)
    def write():
        try:
            for i in range(1, 21):
                at = datetime.now(timezone.utc).isoformat()
                usage = dict(input_tokens=i * 100, output_tokens=0, total_tokens=i * 100)
                with active.open('ab') as stream:
                    stream.write(event('event_msg', {'type': 'token_count', 'info': {'total_token_usage': usage}}, at))
                written[at] = time.monotonic()
                time.sleep(.2)
        except Exception as error:
            failures.append(str(error))
    writer = threading.Thread(target=write)
    writer.start()
    started = time.monotonic()
    try:
        while time.monotonic() - started < 45:
            failed = [item for item in jobs.snapshot()['completed'] if item['state'] == 'failed']
            assert not failed, failed
            if jobs.automatic_ready(jobs.dirty.is_set() or store.live_paths.discovery_due()):
                jobs.dirty.clear()
                jobs.submit('Live scan', lambda: refresh(store, cancel=jobs.cancel, automatic=True),
                            origin='automatic', key='automatic-refresh', cancelable=True)
            with store.connect() as db:
                if reconnect and db.execute('SELECT status FROM sources WHERE id=?', (sid,)).fetchone()[0] == 'Ready':
                    job = jobs.snapshot()
                    reconnected_during_maintenance |= bool(job['running'] and job.get('origin') == 'user')
                for row in db.execute("SELECT ts FROM records WHERE kind='usage' AND session_id='active'"):
                    if row[0] in written and row[0] not in observed:
                        observed[row[0]] = time.monotonic() - written[row[0]]
            if len(observed) == 20 and (not reconnect or reconnected_during_maintenance):
                break
            time.sleep(.05)
        writer.join()
        assert not failures, failures
        assert len(observed) == 20, (len(observed), jobs.snapshot())
        if reconnect:
            assert reconnected_during_maintenance, ('source did not recover until maintenance ended', jobs.snapshot())
        from codex_insights.local_token_burn import LocalTokenBurn
        assert LocalTokenBurn(store).read()['value'] == 400
        ordered = sorted(observed.values())
        p95 = ordered[math.ceil(len(ordered) * .95) - 1]
        assert p95 <= (10 if watchers else 35), p95
        return {'watchers': watchers, 'workload': workload, 'historical_files': 10000, 'events': 20,
                'p95_seconds': round(p95, 3), 'maximum_seconds': round(max(ordered), 3),
                'reconnected_during_maintenance': reconnected_during_maintenance if reconnect else None}
    finally:
        jobs.close()
        if observer:
            observer.stop()
            observer.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workload', choices=('idle','rebuild','backfill','import'), default='idle')
    parser.add_argument('--reconnect', action='store_true', help='Verify offline source recovery during maintenance')
    args = parser.parse_args()
    if args.reconnect and args.workload == 'idle':
        parser.error('--reconnect requires a maintenance workload')
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, watchers in (('watcher', True), ('fallback', False)):
        result = measure(args.output / name, watchers, args.workload, args.reconnect)
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.output / 'latency.json').write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
