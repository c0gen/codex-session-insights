"""One database worker, with foreground priority and coalesced live scans."""
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable


@dataclass
class Work:
    id: int
    message: str
    action: Callable
    origin: str
    key: str | None
    cancelable: bool


class Jobs:
    def __init__(self, clock=time.monotonic, cooldown=5, fallback=30):
        self.clock, self.cooldown, self.fallback = clock, cooldown, fallback
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.dirty = threading.Event()
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insights-indexer")
        self.job = {"running": False, "message": "Ready", "progress": {}, "error": None}
        self.pending = deque()
        self.completed = deque(maxlen=100)
        self.current = None
        self.sequence = 0
        self.next_automatic = self.last_refresh = clock()

    def snapshot(self):
        with self.lock:
            return {**self.job, "progress": dict(self.job["progress"]),
                    "queued": [{"id": work.id, "message": work.message, "origin": work.origin}
                               for work in self.pending], "completed": list(self.completed)}

    def automatic_ready(self, dirty):
        with self.lock:
            now = self.clock()
            return (not self.stop.is_set() and self.current is None and not self.pending
                    and now >= self.next_automatic
                    and (dirty or now - self.last_refresh >= self.fallback))

    def submit(self, message, action, *, origin="user", key=None, cancelable=False):
        with self.lock:
            if self.stop.is_set():
                return {"status": "stopping"}
            if origin == "automatic":
                if self.current or self.pending or self.clock() < self.next_automatic:
                    return {"status": "deferred"}
            elif key:
                existing = next((work for work in self.pending if work.key == key), None)
                if (self.current and self.current.origin == "user"
                        and self.current.key == key and not self.cancel.is_set()):
                    existing = self.current
                if existing:
                    return {"status": "started" if existing is self.current else "queued",
                            "job_id": existing.id, "message": existing.message}
            self.sequence += 1
            work = Work(self.sequence, message, action, origin, key, cancelable)
            status = "started"
            if self.current:
                self.pending.append(work)
                status = "queued"
                if self.current.origin == "automatic" and self.current.cancelable:
                    self.cancel.set()
                    self.dirty.set()
            else:
                self._activate(work)
                self.executor.submit(self._run, work)
            return {"status": status, "job_id": work.id, "message": message}

    def _activate(self, work):
        # Called under the lock; cancellation belongs to one work item only.
        self.current = work
        self.cancel.clear()
        self.job = {"id": work.id, "origin": work.origin, "cancelable": work.cancelable,
                    "running": True, "message": work.message, "progress": {}, "error": None}

    def _run(self, work):
        while True:
            result, error = None, None
            try:
                result = work.action()
            except Exception as exc:
                error = str(exc)
            with self.lock:
                cancelled = work.cancelable and self.cancel.is_set()
                state = "cancelled" if cancelled else "failed" if error is not None else "completed"
                completion = {"id": work.id, "origin": work.origin, "message": work.message,
                              "state": state, "error": None if cancelled else error, "result": result}
                self.completed.append(completion)
                self.job.update(running=False, state=state, result=result,
                                message="Cancelled" if cancelled else "Update failed" if error is not None else "Up to date",
                                error=completion["error"])
                now = self.clock()
                self.next_automatic = now + self.cooldown
                if work.key in {"automatic-refresh", "refresh", "rebuild"}:
                    self.last_refresh = now
                self.current = None
                if self.stop.is_set() or not self.pending:
                    return
                work = self.pending.popleft()
                self._activate(work)

    def progress(self, value):
        with self.lock:
            self.job["progress"] = dict(value)

    def cancel_current(self):
        with self.lock:
            if not self.current or not self.current.cancelable:
                return {"status": "unchanged"}
            self.cancel.set()
            return {"status": "cancelling"}

    def close(self):
        with self.lock:
            self.stop.set()
            self.cancel.set()
            self.pending.clear()
        self.executor.shutdown(wait=True, cancel_futures=True)
