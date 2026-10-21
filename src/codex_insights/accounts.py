"""Concurrent connections, independent of the analytics/indexing transaction queue."""
import threading
import uuid
import webbrowser

from .account_login import AccountLogin
from .account_monitor import AccountMonitor
from .account_storage import AccountRegistry, label
from .account_totals import account_token_total
from .account_groups import display_ids
from .codex_account import AppServerProvider


class Accounts:
    def __init__(self, directory, enabled=True, allowed=True, current_provider=None,
                 provider_factory=AppServerProvider, opener=webbrowser.open, login_timeout=300):
        self.registry = AccountRegistry(directory)
        self.factory = provider_factory
        self.enabled, self.allowed = bool(enabled), bool(allowed)
        self.lock = threading.RLock()
        self.closed = self.started = False
        self.entries = {entry["id"]: entry for entry in self.registry.load()}
        self.monitors = {}
        self.removing = set()
        self.cleanup_threads = []
        self.error = None
        self.login = AccountLogin(opener, login_timeout)
        for identifier, entry in self.entries.items():
            provider = current_provider if identifier == "current" and current_provider is not None else self._provider(identifier)
            self.monitors[identifier] = self._monitor(entry, provider)

    def _provider(self, identifier):
        return self.factory(home=None if identifier == "current" else self.registry.home(identifier))

    def _monitor(self, entry, provider):
        return AccountMonitor(provider, enabled=self.enabled and entry["enabled"], allowed=self.allowed)

    @property
    def current(self):
        return self.monitors["current"].limits

    def current_allowance(self):
        with self.lock:
            monitor = self.monitors['current']
            with monitor.history.lock, monitor.limits.lock:
                return monitor.limits.read()

    def token_total(self):
        """Only summary counters are needed by the Overview's live status."""
        with self.lock:
            totals = []
            for identifier, entry in self.entries.items():
                history = self.monitors[identifier].history
                with history.lock:
                    totals.append({**entry, 'removing': identifier in self.removing,
                                   'identity': history.account, 'history': history.read(('summary',))})
            return account_token_total(totals, self.enabled, self.allowed)

    def refresh_current(self):
        with self.lock:
            return self.monitors["current"].refresh()

    def start(self):
        with self.lock:
            if self.closed:
                return
            self.started = True
            for monitor in self.monitors.values():
                monitor.start()

    def read(self):
        with self.lock:
            snapshots, totals = [], []
            for identifier, entry in self.entries.items():
                monitor = self.monitors[identifier]
                # Capture the history and its identity together, without exposing
                # account identities to browser clients or saving raw API data.
                with monitor.history.lock:
                    snapshot = {**entry, "provider": "codex", "managed": identifier != "current", "removing": identifier in self.removing,
                                **monitor.read()}
                    totals.append({**snapshot, "identity": monitor.history.account})
                snapshots.append(snapshot)
            representatives = display_ids(totals)
            for snapshot in snapshots:
                snapshot["display_id"] = representatives[snapshot["id"]]
            return {"enabled": self.enabled, "allowed": self.allowed, "error": self.error or self.registry.error,
                    "login": self.login.read(), "accounts": snapshots,
                    "token_total": account_token_total(totals, self.enabled, self.allowed)}

    def _require(self, identifier=None):
        if self.closed:
            raise ValueError("Accounts are closing.")
        if not self.allowed:
            raise ValueError("Account connections are disabled in demo and exporter modes.")
        if identifier is not None and (identifier not in self.entries or identifier in self.removing):
            raise ValueError("Account connection is unavailable.")

    def configure(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)
            for identifier, monitor in self.monitors.items():
                monitor.configure(self.enabled and self.entries[identifier]["enabled"])
        if not enabled:
            self.login.cancel()

    def refresh(self, identifier=None):
        with self.lock:
            self._require(identifier)
            for key, monitor in self.monitors.items():
                if identifier is None or key == identifier:
                    monitor.refresh()
        return {"status": "started"}

    def update(self, identifier, changes):
        with self.lock:
            self._require(identifier)
            if not isinstance(changes, dict) or changes.keys() - {"label", "enabled"}:
                raise ValueError("Unknown account preference.")
            changes = dict(changes)
            if "label" in changes:
                changes["label"] = label(changes["label"])
            if "enabled" in changes and type(changes["enabled"]) is not bool:
                raise ValueError("Account enabled must be true or false.")
            updated = {**self.entries[identifier], **changes}
            self.registry.save([updated if key == identifier else entry for key, entry in self.entries.items()])
            self.entries[identifier] = updated
            if "enabled" in changes:
                self.monitors[identifier].configure(self.enabled and updated["enabled"])
            return self.read()

    def connect(self, account_label=None, identifier=None):
        with self.lock:
            self._require(identifier)
            if not self.enabled:
                raise ValueError("Enable live account data in Settings before connecting an account.")
            if self.login.read()["status"] in {"starting", "waiting", "cancelling"}:
                raise ValueError("Finish or cancel the current sign-in first.")
            if identifier == "current":
                raise ValueError("Manage the current Codex sign-in in Codex.")
            reconnect = identifier is not None
            identifier = identifier or uuid.uuid4().hex
            entry = dict(self.entries[identifier]) if reconnect else {
                "id": identifier, "label": label(account_label or "Additional account"), "enabled": True}
            home = self.registry.home(identifier, create=True)
            if reconnect:
                # Stop old credential readers before beginning a fresh managed login.
                self.monitors[identifier].close()
            provider = self.factory(home=home)

            def completed(success):
                with self.lock:
                    if self.closed:
                        if not reconnect:
                            self.registry.forget_credentials(identifier)
                        return
                    # Label/enabled changes remain available during browser sign-in.
                    connected_entry = self.entries.get(identifier, entry) if reconnect else entry
                    if success:
                        try:
                            self.registry.save([*([v for k, v in self.entries.items() if k != identifier]), connected_entry])
                        except Exception:
                            if not reconnect:
                                self.registry.forget_credentials(identifier)
                            else:
                                monitor = self.monitors[identifier] = self._monitor(connected_entry, self._provider(identifier))
                                if self.started:
                                    monitor.start()
                            raise
                        self.entries[identifier] = connected_entry
                    if success or reconnect:
                        monitor = self.monitors[identifier] = self._monitor(connected_entry, self._provider(identifier))
                        if self.started:
                            monitor.start()
                    else:
                        self.registry.forget_credentials(identifier)
            return self.login.start(identifier, entry["label"], provider, completed)

    def remove(self, identifier):
        with self.lock:
            self._require(identifier)
            if identifier == "current":
                raise ValueError("Disable Current Codex to hide its connection; its sign-in belongs to Codex.")
            login = self.login.read()
            if login.get("account_id") == identifier and login["status"] in {"starting", "waiting", "cancelling"}:
                raise ValueError("Cancel this account's sign-in before removing it.")
            self.registry.save([v for k, v in self.entries.items() if k != identifier])
            monitor = self.monitors.pop(identifier)
            self.entries.pop(identifier)
            monitor.begin_close()
            def cleanup():
                monitor.close()
                provider = self._provider(identifier)
                if hasattr(provider, "timeout"):
                    provider.timeout = min(provider.timeout, 5)
                try:
                    provider.logout()
                except Exception:
                    pass
                finally:
                    provider.close()
                    try:
                        self.registry.forget_credentials(identifier)
                    except OSError:
                        self.error = "An account was disconnected, but its saved credential file could not be removed. Check access to the app's account-profiles folder."
            thread = threading.Thread(target=cleanup, daemon=True, name="insights-account-remove")
            self.cleanup_threads = [task for task in self.cleanup_threads if task.is_alive()]
            self.cleanup_threads.append(thread)
            thread.start()
        return {"status": "removed"}

    def close(self):
        with self.lock:
            self.closed = True
            monitors = list(self.monitors.values())
            for monitor in monitors:
                monitor.begin_close()
        self.login.close()
        for monitor in monitors:
            monitor.close()
        for thread in self.cleanup_threads:
            thread.join(timeout=17)
