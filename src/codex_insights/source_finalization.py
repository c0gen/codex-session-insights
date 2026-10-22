"""Incremental source completion shared by full and cooperative scans."""
from datetime import datetime, timezone
from pathlib import Path
import time


def current(scan, sid):
    source = scan.sources[sid]
    if not Path(source['root']).is_dir():
        return False
    with scan.store.connect() as db:
        row = db.execute('SELECT h.discovered_at,h.error,s.enabled FROM index_health h '
                         'JOIN sources s ON s.id=h.source_id WHERE h.source_id=?', (sid,)).fetchone()
    return bool(row and row[0] == scan.discovery_stamps.get(sid) and row[1] is None and row[2])


def finish(scan, sid):
    from .copy_store import finish_verification
    from .providers.history_status import missing_history
    store, source = scan.store, scan.sources[sid]
    after = ''
    while True:
        with store.lock, store.connect() as db:
            segments = [r[0] for r in db.execute("SELECT segment_id FROM history_pending WHERE source_id=? "
                "AND reason='legacy_conflict' AND segment_id>? ORDER BY segment_id LIMIT 16", (sid, after))]
            if not segments:
                break
            for segment in finish_verification(db, sid, segments):
                if store.choose_canonical(db, segment):
                    db.execute('INSERT OR IGNORE INTO projection_queue VALUES(?)', (segment,))
            after = segments[-1]
        yield
    # Only this source's required projections can delay its completion.
    while True:
        with store.connect() as db:
            queued = [r[0] for r in db.execute('SELECT p.segment_id FROM projection_queue p '
                'WHERE EXISTS(SELECT 1 FROM session_metadata m WHERE m.segment_id=p.segment_id AND m.source_id=?) '
                'OR EXISTS(SELECT 1 FROM candidates c WHERE c.segment_id=p.segment_id AND c.source_id=?) LIMIT 16', (sid, sid))]
        if not queued:
            break
        scan.reader.flush(queued, max_batches=1)
        yield
    failures = scan.failures[sid]
    for index, path in enumerate(set(failures.failed) - failures.seen):
        failures.clear(path)
        if index % 16 == 15:
            yield
    failures.summarize()
    missing = missing_history(source['provider'], source['kind'], scan.counts[sid])
    with store.connect() as db:
        db.execute('UPDATE sources SET status=?,updated=? WHERE id=?',
                   (missing['status'] if missing else 'Ready', datetime.now(timezone.utc).isoformat(), sid))
        if missing:
            db.execute('UPDATE sources SET detail=? WHERE id=?', (missing['detail'], sid))


def advance(scan, deadline=None):
    """Return whether eligible completion work remains; each step is bounded."""
    deadline = time.monotonic() + .25 if deadline is None else deadline
    # Only this scan's queued work delays completion. Watcher hints arrive for
    # as long as a session is being written; they belong to the next scan and
    # stay visible as pending/live coverage, so they must not defer it forever.
    blocked = {sid for sid, _ in scan.tasks}
    for sid in sorted(scan.complete - scan.finalized - blocked):
        while not scan.cancelled() and time.monotonic() < deadline:
            if any(source == sid for source, _ in scan.tasks):
                break
            if not current(scan, sid):
                scan.complete.discard(sid)
                task = scan.finalizers.pop(sid, None)
                if task:
                    task.close()
                break
            task = scan.finalizers.setdefault(sid, finish(scan, sid))
            try:
                next(task)
            except StopIteration:
                scan.finalizers.pop(sid, None)
                scan.finalized.add(sid)
                break
    return bool(scan.complete - scan.finalized - blocked) and not scan.cancelled()
