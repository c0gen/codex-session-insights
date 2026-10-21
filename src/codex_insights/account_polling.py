"""Independent in-memory section caches, with account and configuration fences."""
import copy
import threading
import time

from .account_rpc import AllowanceError


class PollingCache:
    def __init__(self, provider, fetch, normalize, available, empty, *, enabled=True, allowed=True,
                 clock=time.time, interval=60, max_backoff=300, listener=None, rates=None,
                 missing_code="unavailable", missing_message="Account data is unavailable.", backoff_base=None):
        self.provider, self.fetch, self.normalize, self.available = provider, fetch, normalize, available
        self.empty, self.payload = empty, copy.deepcopy(empty)
        self.allowed, self.enabled = allowed, bool(enabled) and allowed
        self.clock, self.interval, self.max_backoff = clock, interval, max_backoff
        self.backoff_base = min(60, interval) if backoff_base is None else backoff_base
        self.listener, self.missing_code, self.missing_message = listener, missing_code, missing_message
        self.rates = rates
        self.lock = threading.RLock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.thread = None
        self.refreshing = self.pending = False
        self.account = self.last_success = self.error = self.error_code = self.next_refresh = None
        self.failures = self.generation = self.identity_generation = 0
        self.expirations_seen = set()

    def start(self):
        with self.lock:
            if self.thread or self.stop.is_set() or not self.allowed:
                return
            self.thread = threading.Thread(target=self._run, daemon=True, name="insights-account-cache")
            self.thread.start()

    def read(self, fields=None):
        with self.lock:
            stale = self.last_success is not None and (self.failures > 0 or self.clock() - self.last_success > self.interval * 2 or not self.enabled)
            status = "disabled" if not self.enabled else "stale" if stale else "available" if self.available(self.payload) else "unavailable"
            payload = self.payload if fields is None else {key: self.payload[key] for key in fields if key in self.payload}
            snapshot = {**copy.deepcopy(payload), "enabled": self.enabled, "allowed": self.allowed,
                    "status": status, "refreshing": self.refreshing or self.pending, "stale": stale,
                    "last_success_at": self.last_success, "next_refresh_at": self.next_refresh,
                    "error": self.error, "error_code": self.error_code}
            if self.rates:
                self.rates.decorate(snapshot)
            return snapshot

    def refresh(self):
        self.start()
        with self.lock:
            if self.stop.is_set():
                return {"status": "stopping"}
            if not self.enabled:
                return {"status": "disabled"}
            if self.pending or self.refreshing:
                return {"status": "refreshing"}
            self.pending = True
            self.wake.set()
            return {"status": "started"}

    def configure(self, enabled):
        with self.lock:
            if self.rates and self.enabled != (bool(enabled) and self.allowed):
                self.rates.reset()
            self.enabled = bool(enabled) and self.allowed
            self.generation += 1
            self.next_refresh = None
            self.pending = self.enabled
            self.wake.set()
        self.start()

    def invalidate(self, identity):
        with self.lock:
            if identity != self.account:
                self.account = identity
                self.identity_generation += 1
                self.payload = copy.deepcopy(self.empty)
                if self.rates:
                    self.rates.reset()
                self.last_success = self.error = self.error_code = None
                self.expirations_seen.clear()
                # Clear identity-bound data, not the request budget. Allowance
                # and history can disagree when identity verification fails;
                # resetting deadlines here makes them wake/fetch each other
                # indefinitely. Only a successful fetch resets failure backoff.
                self.wake.set()

    def _expired(self):
        summary = self.payload.get("reset_credits") or {}
        found = False
        for credit in summary.get("credits") or []:
            expiry = credit.get("expires_at")
            key = (credit["id"], expiry)
            if credit["status"] == "available" and expiry is not None and expiry <= self.clock() and key not in self.expirations_seen:
                self.expirations_seen.add(key)
                found = True
        return found

    def _run(self):
        while not self.stop.is_set():
            with self.lock:
                due = self.enabled and (self.pending or self.next_refresh is None or
                                        self.clock() >= self.next_refresh or self._expired())
                if due:
                    self.pending = False
                    self.refreshing = True
                    generation = self.generation
                    identity_version = [self.identity_generation]
                self.wake.clear()
            if due:
                def changed(identity):
                    if self.listener:
                        self.listener(identity)
                    self.invalidate(identity)
                    with self.lock:
                        identity_version[0] = self.identity_generation
                try:
                    payload = self.normalize(self.fetch(changed))
                    with self.lock:
                        if self.enabled and not self.stop.is_set() and generation == self.generation and identity_version[0] == self.identity_generation:
                            self.payload = payload
                            self.last_success = self.clock()
                            if self.rates:
                                self.rates.observe(payload, self.last_success)
                            present = self.available(payload)
                            self.error = None if present else self.missing_message
                            self.error_code = None if present else self.missing_code
                            self.failures = 0
                except Exception as error:
                    with self.lock:
                        if self.enabled and not self.stop.is_set() and generation == self.generation and identity_version[0] == self.identity_generation:
                            self.failures += 1
                            self.error_code = error.code if isinstance(error, AllowanceError) else "connection"
                            self.error = str(error) if isinstance(error, AllowanceError) else "Account connection failed. Refresh to retry."
                finally:
                    with self.lock:
                        self.refreshing = False
                        delay = self.interval if not self.failures else min(self.max_backoff, self.backoff_base * 2 ** min(self.failures - 1, 5))
                        self.next_refresh = self.clock() + delay if self.enabled else None
            with self.lock:
                delay = min(1, max(0, self.next_refresh - self.clock())) if self.enabled and self.next_refresh else 1
            self.wake.wait(delay)

    def begin_close(self):
        with self.lock:
            self.generation += 1
            self.stop.set()
            self.enabled = False
            self.pending = False
            self.payload = copy.deepcopy(self.empty)
            if self.rates:
                self.rates.reset()
            self.account = self.last_success = self.error = self.error_code = None
            self.wake.set()

    def close(self):
        self.begin_close()
        self.provider.close()
        if self.thread:
            self.thread.join(timeout=3)
