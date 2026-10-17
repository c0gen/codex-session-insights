"""WinForms adapter. All window/tray operations run on pywebview's GUI thread."""
import logging
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path

from .windows_widget import WindowsWidget

log = logging.getLogger(__name__)


class WindowsDesktop:
    def __init__(self, window, url, bridge, store):
        # pywebview has loaded pythonnet and WinForms before before_show fires.
        from System import Action
        from System.Drawing import Icon, Point, Size
        from System.Windows.Forms import (NotifyIcon, ContextMenuStrip, ToolStripMenuItem,
                                          FormWindowState, CloseReason, Screen)
        from Microsoft.Win32 import SystemEvents
        self.Action, self.Point, self.Size = Action, Point, Size
        self.NotifyIcon, self.Menu, self.MenuItem = NotifyIcon, ContextMenuStrip, ToolStripMenuItem
        self.WindowState, self.CloseReason, self.Screen = FormWindowState, CloseReason, Screen
        self.system_events = SystemEvents
        self.window, self.url, self.bridge, self.store = window, url, bridge, store
        self.icon = Icon(str(Path(__file__).parent / "assets" / "insights.ico"))
        self.tray = self.menu = None
        self.disposed = False
        self.widget_host = WindowsWidget(self)

    @property
    def widget(self):
        return self.widget_host.window

    def setup(self, controller):
        self.controller = controller
        self.window.native.Icon = self.icon
        self.window.native.FormClosing += self.on_dashboard_closing
        self.system_events.DisplaySettingsChanged += self.on_displays_changed

    def dispatch(self, action):
        if self.disposed or self.window.native.IsDisposed:
            return
        def safe():
            if self.disposed:
                return
            try:
                action()
            except Exception:
                log.exception("Desktop operation failed")
                self.controller.error = "A desktop operation failed. See the startup log for details."
        self.window.native.BeginInvoke(self.Action(safe))

    def on_dashboard_closing(self, sender, args):
        args.Cancel = self.controller.closing_dashboard(args.CloseReason == self.CloseReason.UserClosing)

    def show_dashboard(self):
        form = self.window.native
        form.Show()
        if form.WindowState == self.WindowState.Minimized:
            form.WindowState = self.WindowState.Normal
        form.Activate()

    def hide_dashboard(self):
        self.window.native.Hide()

    def close_dashboard(self):
        self.window.native.Close()

    def ensure_tray(self):
        if self.tray:
            return
        tray, menu = self.NotifyIcon(), self.Menu()
        try:
            def item(label, callback):
                control = self.MenuItem(label)
                control.Click += lambda *_: callback()
                menu.Items.Add(control)
                return control
            item("Open dashboard", lambda: self.controller.command("show_dashboard"))
            self.widget_item = item("Show widget", lambda: self.controller.background_update(
                {"widget_enabled": not self.controller.value["widget_enabled"]}))
            item("Settings", lambda: self.controller.command("show_settings"))
            item("Refresh", lambda: threading.Thread(target=self.controller.engine.refresh, daemon=True).start())
            menu.Items.Add("-")
            item("Quit", lambda: self.controller.command("quit"))
            tray.Icon = self.icon
            tray.Text = "Codex Session Insights"
            tray.ContextMenuStrip = menu
            tray.DoubleClick += lambda *_: self.controller.command("show_dashboard")
            tray.Visible = True
            self.tray, self.menu = tray, menu
        except Exception:
            tray.Dispose()
            menu.Dispose()
            raise

    def remove_tray(self):
        if self.tray:
            self.tray.Visible = False
            self.tray.Dispose()
            self.menu.Dispose()
            self.tray = self.menu = None

    def update_menu(self, preferences):
        if self.tray:
            self.widget_item.Checked = preferences["widget_enabled"]
            self.widget_item.Text = "Hide widget" if preferences["widget_enabled"] else "Show widget"

    def show_widget(self, preferences):
        self.widget_host.show(preferences)

    def remove_widget(self):
        self.widget_host.remove()

    def fit_widget(self):
        self.widget_host.fit()

    @staticmethod
    def set_tool_window(form):
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        api.GetWindowLongW.restype = wintypes.LONG
        api.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        api.SetWindowLongW.restype = wintypes.LONG
        handle = form.Handle.ToInt64()
        style = api.GetWindowLongW(handle, -20)
        api.SetWindowLongW(handle, -20, (style & ~0x40000) | 0x80)

    @staticmethod
    def is_tool_window(form):
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        api.GetWindowLongW.restype = wintypes.LONG
        return bool(api.GetWindowLongW(form.Handle.ToInt64(), -20) & 0x80)

    def on_displays_changed(self, *_):
        self.dispatch(self.fit_widget)

    def dispose(self):
        if self.disposed:
            return
        self.widget_host.dispose()
        self.disposed = True
        self.system_events.DisplaySettingsChanged -= self.on_displays_changed
        self.remove_tray()
        self.icon.Dispose()
