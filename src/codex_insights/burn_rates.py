"""In-memory rates from observed counters; callers hold their polling cache lock."""
from collections import deque
import math


def empty_estimate(updated_at=None):
    return {"value": None, "status": "unavailable", "observed_seconds": 0,
            "updated_at": updated_at}


class RollingRate:
    """A five-minute trailing estimate, retaining the sample before the cutoff."""
    def __init__(self, interval, unit_seconds, window_seconds=300, minimum_seconds=60):
        self.interval, self.unit_seconds = interval, unit_seconds
        self.window_seconds, self.minimum_seconds = window_seconds, minimum_seconds
        self.samples = deque()
        self.key = self.updated_at = None

    def reset(self):
        self.samples.clear()
        self.key = self.updated_at = None

    def observe(self, value, at, key=None):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            self.reset()
            self.updated_at = at
            return
        if self.samples:
            previous_at, previous_value = self.samples[-1]
            if (key != self.key or at < previous_at or at - previous_at > self.interval * 2
                    or value < previous_value):
                self.reset()
            elif at == previous_at:
                self.samples.pop()
        self.key, self.updated_at = key, at
        self.samples.append((at, value))
        cutoff = at - self.window_seconds
        while len(self.samples) > 2 and self.samples[1][0] <= cutoff:
            self.samples.popleft()

    def read(self, *, enabled=True, stale=False):
        if not enabled or not self.samples:
            return empty_estimate(self.updated_at)
        first_at, first_value = self.samples[0]
        last_at, last_value = self.samples[-1]
        elapsed = last_at - first_at
        value = ((last_value - first_value) / elapsed * self.unit_seconds
                 if elapsed >= self.minimum_seconds else None)
        return {"value": value, "status": "stale" if stale else "available" if value is not None else "collecting",
                "observed_seconds": elapsed, "updated_at": self.updated_at}


class AllowanceBurnRates:
    def __init__(self, interval=60):
        self.interval = interval
        self.rates = {}

    def reset(self):
        self.rates.clear()

    def observe(self, payload, at):
        active = {}
        for bucket in payload["buckets"]:
            for window in bucket["windows"]:
                key = (bucket["id"], window["id"])
                rate = self.rates.get(key) or RollingRate(self.interval, 3600)
                remaining = window["remaining_percent"]
                rate.observe(None if remaining is None else 100 - remaining, at,
                             key=(window["window_duration_mins"], window["resets_at"]))
                active[key] = rate
        self.rates = active

    def decorate(self, snapshot):
        for bucket in snapshot["buckets"]:
            for window in bucket["windows"]:
                rate = self.rates.get((bucket["id"], window["id"]))
                window["burn_rate"] = (rate.read(enabled=snapshot["enabled"], stale=snapshot["stale"])
                                       if rate else empty_estimate())
