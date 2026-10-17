"""Native widget lifecycle, menu and movement; GUI-thread operations only."""
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import logging

from .desktop_preferences import fit_rectangle
from .widget_geometry import WidgetLayout, restore_position
from .widget_resize import VerticalResize

log = logging.getLogger(__name__)


def window_api():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.ReleaseCapture.argtypes, api.ReleaseCapture.restype = [], wintypes.BOOL
    api.GetCursorPos.argtypes, api.GetCursorPos.restype = [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL
    api.GetAsyncKeyState.argtypes, api.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
    api.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    api.SendMessageW.restype = ctypes.c_ssize_t
    return api


def native_drag(api, handle):
    """Enter the OS move loop with native coordinates, never JS screenX/Y."""
    if not api.GetAsyncKeyState(0x01) & 0x8000:
        return  # The button may have been released before bridge dispatch.
    point = wintypes.POINT()
    if not api.GetCursorPos(ctypes.byref(point)):
        return
    coordinates = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
    api.ReleaseCapture()
    api.SendMessageW(handle, 0x00A1, 2, coordinates)  # WM_NCLBUTTONDOWN, HTCAPTION


class WidgetBridge:
    def __init__(self, owner, generation):
        # pywebview recursively exposes public attributes as part of its API.
        self._owner, self._generation = owner, generation

    def call(self, action, args=None):
        if action in {"widget_layout", "widget_command"}:
            return self._owner.request(action, args, self._generation)
        return self._owner.host.bridge.call(action, args)


class WindowsWidget:
    def __init__(self, host):
        from System.Drawing import Point, Size
        from System.Windows.Forms import Timer, Screen, Cursor, FormStartPosition
        self.Point, self.Size, self.Screen, self.Cursor = Point, Size, Screen, Cursor
        self.manual = FormStartPosition.Manual
        self.host, self.window, self.menu = host, None, None
        self.position = host.store.setting("widget_position", None)
        self.writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insights-position")
        self.timer = Timer()
        self.timer.Interval = 400
        self.timer.Tick += self.save_position
        self.layout = None
        self.placed = self.moving = self.disposed = False
        self.generation = 0
        self.preferred_height = None
        self.resize = VerticalResize(self, window_api(), Timer())

    def show(self, preferences):
        previous_height = self.preferred_height
        self.preferred_height = preferences.get("widget_height_css_px")
        if self.window:
            self.window.native.TopMost = preferences["always_on_top"]
            if previous_height != self.preferred_height:
                self.fit()
            return
        import webview
        self.generation += 1
        self.layout, self.placed = None, False
        self.window = webview.create_window(
            "Codex usage widget", self.host.url + "/widget/index.html",
            js_api=WidgetBridge(self, self.generation), width=240, height=120,
            x=0, y=0, min_size=(1, 1), frameless=True, easy_drag=False,
            resizable=False, shadow=True, hidden=True,
            on_top=preferences["always_on_top"], background_color="#10171c")
        form = self.window.native
        self.host.set_tool_window(form)
        form.StartPosition = self.manual
        form.MinimumSize = self.Size(1, 1)
        form.Icon = self.host.icon
        form.FormClosing += self.on_closing
        form.FormClosed += self.on_closed
        form.Deactivate += self.dismiss_menu
        form.Move += self.on_moved
        form.DpiChanged += self.on_dpi
        form.ResizeBegin += self.on_move_begin
        form.ResizeEnd += self.on_move_end
        # Put the hidden browser on its destination monitor before measuring it.
        self.fit()

    def request(self, action, args, generation):
        if action == "widget_layout":
            layout = WidgetLayout.read(args)
            operation = lambda: self.update_layout(layout)
        elif isinstance(args, dict) and args.get("command") in {"drag", "menu", "dismiss_menu", "resize_top", "resize_bottom", "fit_content"}:
            if args["command"] == "drag":
                operation = self.begin_drag
            elif args["command"] == "menu":
                operation = lambda: self.show_menu(args.get("keyboard") is True)
            elif args["command"].startswith("resize_"):
                operation = lambda: self.resize.start(args["command"][7:])
            elif args["command"] == "fit_content":
                operation = lambda: self.host.controller.background_update({"widget_height_css_px": None})
            else:
                operation = self.dismiss_menu
        else:
            raise ValueError("Unknown widget command")

        def execute():
            if not self.disposed and self.window and generation == self.generation:
                operation()
        self.host.dispatch(execute)
        return {"status": "accepted"}

    def update_layout(self, layout):
        if self.layout == layout and self.placed:
            return
        self.layout = layout
        self.fit()

    def fit(self):
        if not self.window or self.disposed or self.moving:
            return
        form = self.window.native
        screen = self.Screen.FromControl(form if self.placed else self.host.window.native)
        if not self.placed and isinstance(self.position, dict):
            screen = next((s for s in self.Screen.AllScreens
                           if s.DeviceName == self.position.get("monitor")), screen)
        work = screen.WorkingArea
        area = (work.Left, work.Top, work.Right, work.Bottom)
        bottom = form.Top + form.Height
        if self.layout:
            width, height = self.layout.pixels(work.Width, work.Height, self.preferred_height)
            if (form.ClientSize.Width, form.ClientSize.Height) != (width, height):
                form.ClientSize = self.Size(width, height)
        if not self.placed:
            x, y = restore_position(self.position, str(screen.DeviceName), area,
                                    (form.Width, form.Height), max(1, form.DeviceDpi) / 96)
        else:
            top = bottom - form.Height if self.preferred_height is None and self.layout and self.layout.anchor == "bottom" else form.Top
            x, y = fit_rectangle(form.Left, top, form.Width, form.Height, area)
        if (form.Left, form.Top) != (x, y):
            form.Location = self.Point(x, y)
        if self.layout and not self.placed:
            self.placed = True
            form.Show()
        self.on_moved()

    def begin_drag(self):
        if self.moving or not self.placed:
            return
        self.dismiss_menu()
        self.on_move_begin()
        try:
            native_drag(window_api(), self.window.native.Handle.ToInt64())
        finally:
            self.on_move_end()

    def on_move_begin(self, *_):
        self.moving = True
        self.timer.Stop()

    def on_move_end(self, *_):
        self.moving = False
        self.fit()
        self.save_position()

    def on_dpi(self, *_):
        self.host.dispatch(self.fit)

    def on_moved(self, *_):
        if self.placed and not self.moving:
            self.timer.Stop()
            self.timer.Start()

    def save_position(self, *_):
        self.timer.Stop()
        if not self.window or not self.placed or self.moving:
            return
        form = self.window.native
        screen = self.Screen.FromControl(form)
        self.position = {"version": 2, "monitor": str(screen.DeviceName),
                         "x": int(form.Left - screen.WorkingArea.Left),
                         "y": int(form.Top - screen.WorkingArea.Top)}
        value = dict(self.position)
        def save():
            try:
                self.host.store.set_setting("widget_position", value)
            except Exception:
                log.exception("Could not save widget position")
        self.writer.submit(save)

    def show_menu(self, keyboard=False):
        if not self.menu:
            self.menu = self.host.Menu()
            controller = self.host.controller
            def item(label, callback):
                control = self.host.MenuItem(label)
                control.Click += lambda *_: callback()
                self.menu.Items.Add(control)
                return control
            item("Open dashboard", lambda: controller.command("show_dashboard"))
            item("Settings", lambda: controller.command("show_settings"))
            item("Fit to content", lambda: controller.background_update({"widget_height_css_px": None}))
            self.pin_item = item("Keep on top", lambda: controller.background_update(
                {"always_on_top": not controller.value["always_on_top"]}))
            item("Hide widget", lambda: controller.background_update({"widget_enabled": False}))
        self.pin_item.Checked = self.host.controller.value["always_on_top"]
        form = self.window.native
        form.Activate()
        point = self.Point(6, 6) if keyboard else form.PointToClient(self.Cursor.Position)
        # Give WinForms the originating window so its normal menu dismissal
        # follows focus and mouse clicks through the embedded WebView2 control.
        self.menu.Show(form, point)

    def dismiss_menu(self, *_):
        if self.menu:
            self.menu.Close()

    def on_closing(self, sender, args):
        if self.window and not self.host.controller.quitting:
            if args.CloseReason != self.host.CloseReason.UserClosing:
                self.host.controller.command("quit")
            else:
                args.Cancel = True
                self.host.controller.background_update({"widget_enabled": False})

    def on_closed(self, sender, _):
        if self.window and sender == self.window.native:
            self.window = None
            self.placed = False
            self.timer.Stop()

    def remove(self):
        if self.window:
            self.resize.finish()
            self.save_position()
            window, self.window = self.window, None
            self.placed = False
            self.timer.Stop()
            if self.menu:
                self.menu.Close()
            window.native.Close()

    def dispose(self):
        if self.disposed:
            return
        self.remove()
        self.disposed = True
        self.timer.Dispose()
        self.resize.dispose()
        if self.menu:
            self.menu.Dispose()
        self.writer.shutdown(wait=True)
