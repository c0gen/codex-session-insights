"""Live Codex work serviced by the owning writer between committed batches."""
from contextlib import contextmanager
import threading
import time


class LiveMaintenance:
    def __init__(self, store, cancel=None):
        self.store, self.cancel, self.busy = store, cancel, False
        self.scan = None

    def __call__(self):
        # A running Scan already services watcher hints between its own batches.
        if self.busy or getattr(self.store, 'active_scans', 0) or (self.cancel and self.cancel.is_set()):
            return
        self.busy = True
        try:
            from .index_scan import Scan
            live = getattr(self.store, 'live_paths', None)
            if not live:
                return
            if self.scan is None:
                sources = [s for s in self.store.sources() if s['enabled'] and s['kind'] == 'folder'
                           and s['provider'] == 'codex' and s['root']]
                report = dict(files=0, changed_files=0, bytes_read=0, errors=0, skipped_errors=0)
                self.scan = Scan(self.store, sources, report, cancel=self.cancel, automatic=True)
            self.scan.hints()
            deadline = time.monotonic() + .25
            # Discovery shares this slice's budget; a large history resumes next call.
            if self.scan.walk is None and live.discovery_due():
                live.begin_discovery()
                self.scan.advance_inventory(deadline)
            elif self.scan.walk is not None:
                self.scan.advance_inventory(deadline)
            self.scan.finalize(deadline)
            while self.scan.tasks and time.monotonic() < deadline and not self.scan.cancelled():
                self.scan.step()
            self.scan.finalize(deadline)
        finally:
            self.busy = False

    def close(self):
        if self.scan:
            self.scan.close()


@contextmanager
def live_work(store, cancel=None):
    previous = getattr(store, 'cooperate', None)
    worker = LiveMaintenance(store, cancel)
    store.cooperate = worker
    try:
        yield worker
    finally:
        worker.close()
        store.cooperate = previous


def checkpoint(store):
    callback = getattr(store, 'cooperate', None)
    if callback:
        callback()


def cancelled(store):
    stop = getattr(store, 'maintenance_cancel', None)
    if stop and stop.is_set():
        raise InterruptedError('Index maintenance cancelled; progress is saved for the next run')
