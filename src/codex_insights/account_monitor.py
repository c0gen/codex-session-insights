"""Two independently fresh sections sharing one account's credential provider."""
import time

from .account_data import normalize_history
from .account_polling import PollingCache
from .account_rpc import AllowanceError
from .usage_limits import UsageLimits


class AccountMonitor:
    def __init__(self, provider, enabled=True, allowed=True, clock=time.time):
        self.provider = provider
        self.limits = UsageLimits(provider, enabled=enabled, allowed=allowed, clock=clock, listener=self.changed)
        def history(changed):
            fetch = getattr(provider, "fetch_history", None)
            if not fetch:
                raise AllowanceError("unsupported", "Token history is unavailable from this account provider.")
            return fetch(changed)
        empty = normalize_history({})
        self.history = PollingCache(provider, history, normalize_history,
            lambda value: value["daily"] is not None or any(v is not None for v in value["summary"].values()),
            empty, enabled=enabled, allowed=allowed, clock=clock, interval=300, listener=self.changed,
            missing_message="This account has not returned token history.")

    def changed(self, identity):
        # Use the same lock order as Accounts.read, including while invalidating.
        with self.history.lock, self.limits.lock:
            self.limits.invalidate(identity)
            self.history.invalidate(identity)

    def start(self):
        self.limits.start()
        self.history.start()

    def configure(self, enabled):
        with self.history.lock, self.limits.lock:
            self.limits.configure(enabled)
            self.history.configure(enabled)

    def refresh(self):
        result = self.limits.refresh()
        self.history.refresh()
        return result

    def read(self):
        with self.history.lock, self.limits.lock:
            history, allowance = self.history.read(), self.limits.read()
            return {"plan": getattr(self.provider, "plan", None),
                    "allowance": allowance, "history": history}

    def begin_close(self):
        with self.history.lock, self.limits.lock:
            self.limits.begin_close()
            self.history.begin_close()

    def close(self):
        self.begin_close()
        self.limits.close()
        self.history.close()
