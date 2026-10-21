"""Cooperative scans: watcher work can interrupt historical file parsing."""
import time
from collections import OrderedDict
from pathlib import Path

from .index_file import FileIndexer
from .index_failures import FileFailures
from .index_health import source_checked
from .providers import adapter


class Scan:
    def __init__(self, store, sources, report, progress=None, cancel=None, rebuild=False, automatic=False, live_sources=()):
        self.primary = {s['id'] for s in sources}
        self.store, self.sources, self.report = store, {s['id']: s for s in [*live_sources, *sources]}, report
        self.progress, self.cancel = progress, cancel
        self.reader = FileIndexer(store, report, cancel, rebuild, automatic)
        self.live_reader = FileIndexer(store, report, cancel, False, True)
        self.failures = {sid: FileFailures(store, sid, adapter(s['provider']).version)
                         for sid, s in self.sources.items()}
        self.tasks = OrderedDict()
        self.urgent = set()
        self.live = getattr(store, 'live_paths', None)
        self.last_inventory = time.monotonic()
        self.complete = set()
        self.finalized, self.finalizers, self.discovery_stamps = set(), {}, {}
        self.counts = {}
        self.processed = 0
        self.completed_stamps = {}

    def cancelled(self):
        return self.cancel is not None and self.cancel.is_set()

    def enqueue(self, sid, path, urgent=False):
        with self.store.connect() as db:
            self._enqueue(db, sid, path, urgent)

    def _enqueue(self, db, sid, path, urgent=False):
        key = (sid, str(path))
        if sid not in self.sources:
            return
        if key not in self.tasks:
            self.tasks[key] = None
        if urgent:
            self.urgent.add(key)
            self.tasks.move_to_end(key, last=False)
        db.execute('INSERT OR IGNORE INTO index_pending VALUES(?,?)', key)
        # A bound applies only to the exact bytes already verified. A file
        # changed by a watcher can never inherit an old historical bound.
        db.execute('DELETE FROM pending_time_evidence WHERE source_id=? AND path=?', key)
        try:
            stamp = Path(path).stat()
            if not urgent:
                db.execute('INSERT INTO pending_time_evidence SELECT source_id,path,affected_until FROM file_time_evidence '
                           'WHERE source_id=? AND path=? AND size=? AND mtime=?', (*key, stamp.st_size, stamp.st_mtime_ns))
        except OSError:
            pass

    def hints(self):
        if not self.live:
            return
        others = []
        for sid, path in self.live.take():
            if sid not in self.sources:
                others.append((sid, path))
                continue
            # Deletions require inventory verification, not a fabricated read error.
            if Path(path).is_file():
                self.enqueue(sid, path, urgent=True)
        self.live.requeue(others)

    def inventory(self, primary_only=False):
        self.last_inventory = time.monotonic()
        for sid, source in self.sources.items():
            if primary_only and sid not in self.primary:
                continue
            if self.cancelled():
                return
            root = Path(source['root'])
            started = time.time()
            failures = self.failures[sid]
            failures.seen.clear()
            self.complete.discard(sid)
            self.finalized.discard(sid)
            finalizer = self.finalizers.pop(sid, None)
            if finalizer:
                finalizer.close()
            try:
                if not root.is_dir():
                    with self.store.connect() as db:
                        db.execute("UPDATE sources SET status='Offline',detail='Previously indexed history retained' WHERE id=?", (sid,))
                        source_checked(db, sid, error='source_offline')
                    continue
                with self.store.connect() as db:
                    checkpoints = {r['path']: dict(r) for r in db.execute(
                        'SELECT f.path,f.size,f.mtime,f.parser_version,c.checked_at AS verified FROM files f '
                        'LEFT JOIN file_coverage c ON c.source_id=f.source_id AND c.path=f.path WHERE f.source_id=?', (sid,))}
                changed, seen = [], set()
                for path in adapter(source['provider']).discover(root, source['kind']):
                    if self.cancelled():
                        return
                    key = str(path)
                    seen.add(key)
                    failures.seen.add(key)
                    self.report['files'] += 1
                    if len(seen) % 64 == 1:
                        self.hints()
                        if self.urgent:
                            self.step(urgent_only=True)
                    cached = checkpoints.get(key)
                    try:
                        stat = path.stat()
                        if self.reader.rebuild and self.completed_stamps.get((sid, key)) == (stat.st_size, stat.st_mtime_ns):
                            continue
                        if (not (self.reader.rebuild and sid in self.primary) and cached and cached['parser_version'] == failures.parser_version
                                and cached['size'] == stat.st_size and cached['mtime'] == stat.st_mtime_ns
                                and key not in failures.failed and cached['verified'] is not None):
                            continue
                        changed.append((stat.st_mtime_ns, path))
                    except OSError:
                        changed.append((0, path))
                self.counts[sid] = len(seen)
                changed.sort(key=lambda item: item[0])
                for offset in range(0, len(changed), 64):
                    if self.cancelled():
                        return
                    with self.store.connect() as db:
                        for mtime, path in changed[offset:offset + 64]:
                            self._enqueue(db, sid, path, urgent=mtime / 1e9 >= started - 300)
                    # Queue construction is background work too. Commit before
                    # servicing watcher hints, using the same owning writer.
                    self.hints()
                    if self.urgent:
                        self.step(urgent_only=True)
                with self.store.connect() as db:
                    for row in db.execute('SELECT path FROM file_coverage WHERE source_id=?', (sid,)).fetchall():
                        if row[0] not in seen:
                            db.execute('DELETE FROM file_coverage WHERE source_id=? AND path=?', (sid, row[0]))
                    # Only a completed inventory can clear vanished pending paths.
                    for row in db.execute('SELECT path FROM index_pending WHERE source_id=?', (sid,)).fetchall():
                        if row[0] not in seen:
                            db.execute('DELETE FROM index_pending WHERE source_id=? AND path=?', (sid, row[0]))
                    source_checked(db, sid, started, discovered=True)
                self.discovery_stamps[sid] = started
                self.complete.add(sid)
            except OSError:
                self.report['errors'] += 1
                with self.store.connect() as db:
                    source_checked(db, sid, error='discovery_error')

    def step(self, urgent_only=False):
        if not self.tasks or self.cancelled():
            return
        key = next((key for key in self.tasks if key in self.urgent), None)
        if key is None:
            if urgent_only:
                return
            key = next(iter(self.tasks))
        sid, path = key
        task = self.tasks[key]
        if task is None:
            self.processed += 1
            if self.progress:
                self.progress({**self.report, 'files': self.processed, 'discovered_files': self.report['files'],
                               'source': self.sources[sid]['label']})
            if self.cancelled():
                return
            reader = self.reader if sid in self.primary else self.live_reader
            task = self.tasks[key] = reader.read(self.sources[sid], Path(path), self.failures[sid])
        try:
            next(task)
            if key in self.urgent:
                self.tasks.move_to_end(key)
        except StopIteration:
            with self.store.connect() as db:
                saved = db.execute('SELECT size,mtime FROM files WHERE source_id=? AND path=?', key).fetchone()
                if saved:
                    self.completed_stamps[key] = tuple(saved)
            del self.tasks[key]
            self.urgent.discard(key)
        if self.progress:
            self.progress({**self.report, 'files': self.processed, 'source': self.sources[sid]['label']})

    def finalize(self, deadline=None):
        from .source_finalization import advance
        return advance(self, deadline)

    def close(self):
        for task in self.finalizers.values():
            task.close()
        if self.live:
            self.live.requeue(list(self.tasks))
        for task in self.tasks.values():
            if task is not None:
                task.close()

    def run_pending(self):
        try:
            self.reader.flush()
            self.hints()
            while self.tasks and not self.cancelled():
                self.hints()
                self.step()
                self.finalize()
            self.reader.flush()
        finally:
            self.close()

    def run(self):
        try:
            self.reader.flush()
            self.hints()
            self.inventory(primary_only=True)
            while self.tasks and not self.cancelled():
                self.hints()
                if self.live and time.monotonic() - self.last_inventory >= 30:
                    self.inventory()
                self.step()
                self.finalize()
            self.reader.flush()
            if self.cancelled():
                return
            while self.finalize():
                self.hints()
                while self.tasks and not self.cancelled():
                    self.step()
        finally:
            self.close()
