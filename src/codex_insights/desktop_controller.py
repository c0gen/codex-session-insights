"""Desktop lifecycle policy, independent of the native toolkit for testing."""
import logging
import threading
from .account_storage import connection_id

from .desktop_preferences import DesktopPreferences

log = logging.getLogger(__name__)


class DesktopController:
    def __init__(self, engine, preferences=None):
        self.engine = engine
        self.preferences = preferences or DesktopPreferences(engine.store, background=True)
        self.value = self.preferences.read()
        self.native = None
        self.tray_active = False
        self.error = None
        self.quitting = False
        self.settings_request = 0
        self.account_request = None
        self.navigation_sequence = 0
        self.lock = threading.RLock()

    def state(self):
        with self.lock:
            return {"available": True, "preferences": dict(self.value),
                    "revision": self.preferences.revision, "tray_active": self.tray_active,
                    "error": self.error or self.preferences.error, "settings_request": self.settings_request,
                    "account_request": dict(self.account_request) if self.account_request else None}

    def attach(self, native):
        self.native = native
        native.setup(self)
        native.dispatch(self.apply)

    def update(self, changes):
        with self.lock:
            self.value = self.preferences.update(changes)
        if self.native:
            self.native.dispatch(self.apply)
        return self.state()

    def background_update(self, changes):
        try:
            self.update(changes)
        except Exception:
            log.exception("Could not change desktop preferences")
            self.error = "Could not change desktop preferences. Try again in Settings."

    def apply(self):
        """Called only on the native GUI thread."""
        if self.quitting:
            return
        value = dict(self.value)
        self.error = None
        if value["tray_enabled"]:
            try:
                self.native.ensure_tray()
                self.tray_active = True
            except Exception:
                log.exception("Tray initialization failed")
                self.tray_active = False
                self.error = "Tray unavailable. Closing the dashboard will quit the app."
                self.native.show_dashboard()
        else:
            # Never remove the last way to recover a hidden dashboard.
            self.native.show_dashboard()
            self.native.remove_tray()
            self.tray_active = False
        try:
            if value["widget_enabled"]:
                self.native.show_widget(value)
            else:
                self.native.remove_widget()
            self.native.update_menu(value)
        except Exception:
            log.exception("Widget initialization failed")
            self.error = "Could not open the widget. Try disabling and enabling it in Settings."
            self.native.remove_widget()

    def closing_dashboard(self, user_close=True):
        """Return True to cancel a user close and keep the process in the tray."""
        if not self.quitting and user_close and self.value["tray_enabled"] and self.tray_active:
            self.native.hide_dashboard()
            return True
        self.begin_quit()
        return False

    def begin_quit(self):
        if self.quitting:
            return
        self.quitting = True
        begin_close = getattr(self.engine, "begin_close", None)
        if begin_close:
            begin_close()
        else:
            self.engine.stop.set()
            self.engine.cancel.set()
        self.native.remove_tray()
        self.tray_active = False
        self.native.remove_widget()

    def command(self, command, account_id=None):
        if command not in {"show_dashboard", "show_settings", "show_account", "quit"}:
            raise ValueError("Unknown desktop command")
        if command == "show_account" and not connection_id(account_id):
            raise ValueError("Choose an account to open")
        def execute():
            if command == "quit":
                self.begin_quit()
                self.native.close_dashboard()
            elif not self.quitting:
                if command == "show_settings":
                    self.settings_request += 1
                elif command == "show_account":
                    self.navigation_sequence += 1
                    self.account_request = {"sequence": self.navigation_sequence, "account_id": account_id}
                self.native.show_dashboard()
        self.native.dispatch(execute)
        return {"status": "accepted"}

    def dispose(self):
        self.preferences.close()
        if self.native:
            self.native.dispose()
