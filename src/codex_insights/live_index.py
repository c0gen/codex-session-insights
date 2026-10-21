"""Thread-safe watcher hints; only the indexing worker consumes file work."""
import threading
import time
import sqlite3
from pathlib import Path


class LivePaths:
    def __init__(self, clock=time.monotonic, cooldown=5):
        self.clock, self.cooldown = clock, cooldown
        self.lock = threading.Lock()
        self.paths = {}
        self.discovery = set()
        self.last_discovery = None

    def event(self, source_id, root, event):
        if event.event_type not in {'created', 'modified', 'moved', 'deleted'}:
            return
        root = Path(root).resolve()
        with self.lock:
            for name in (event.src_path, getattr(event, 'dest_path', None)):
                if not name:
                    continue
                path = Path(name).resolve()
                if not path.is_relative_to(root):
                    continue
                if event.is_directory:
                    self.discovery.add(source_id)
                elif path.suffix.lower() == '.jsonl' and not path.name.startswith('._'):
                    # First event wins: a continuous writer cannot postpone its scan.
                    self.paths.setdefault((source_id, str(path)), self.clock())

    def take(self, *, force=False, exclude=()):
        excluded = set(exclude)
        with self.lock:
            now = self.clock()
            keys = [key for key, at in self.paths.items()
                    if key not in excluded and (force or now - at >= self.cooldown)]
            for key in keys:
                del self.paths[key]
            return keys

    def pending(self):
        with self.lock:
            return list(self.paths)

    def requeue(self, keys):
        with self.lock:
            for key in keys:
                self.paths.setdefault(key, self.clock() - self.cooldown)

    def discovery_due(self):
        with self.lock:
            return bool(self.discovery or self.last_discovery is None or self.clock() - self.last_discovery >= 30)

    def begin_discovery(self):
        with self.lock:
            self.last_discovery = self.clock()
            self.discovery.clear()

    def prune(self, source_ids):
        with self.lock:
            self.paths = {key: at for key, at in self.paths.items() if key[0] in source_ids}
            self.discovery.intersection_update(source_ids)

    def poll_retries(self, store):
        try:
            with store.connect() as db:
                keys = [(r[0], r[1]) for r in db.execute(
                    'SELECT r.source_id,r.path FROM index_retries r JOIN sources s ON s.id=r.source_id '
                    'WHERE s.enabled=1 AND r.next_retry_at<=?', (time.time(),))]
            self.requeue(keys)
            return bool(keys)
        except sqlite3.DatabaseError:
            # Rate readers expose the index error; the watcher thread must survive it.
            return False
