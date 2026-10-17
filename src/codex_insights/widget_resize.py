"""Vertical edge gestures using native cursor coordinates, independent of WebView zoom."""
import ctypes
from ctypes import wintypes
import logging

from .widget_geometry import resize_vertical


class VerticalResize:
    def __init__(self, owner, api, timer):
        self.owner, self.api, self.timer = owner, api, timer
        self.gesture = None
        timer.Interval = 16
        timer.Tick += self.tick

    def start(self, edge):
        owner = self.owner
        if owner.moving or not owner.placed or not owner.layout or not self.api.GetAsyncKeyState(1) & 0x8000:
            return
        point = wintypes.POINT()
        if not self.api.GetCursorPos(ctypes.byref(point)):
            return
        owner.dismiss_menu()
        form = owner.window.native
        work = owner.Screen.FromControl(form).WorkingArea
        self.gesture = (edge, point.y, form.Top, form.Height, owner.layout.scale,
                        (work.Left, work.Top, work.Right, work.Bottom), form.Left)
        owner.on_move_begin()
        self.timer.Start()

    def tick(self, *_):
        if not self.gesture:
            return
        if self.api.GetAsyncKeyState(0x1B) & 0x8000:
            self.finish(cancel=True)
            return
        if not self.api.GetAsyncKeyState(1) & 0x8000:
            self.finish()
            return
        point = wintypes.POINT()
        if not self.api.GetCursorPos(ctypes.byref(point)):
            self.finish(cancel=True)
            return
        edge, cursor, top, height, scale, work, left = self.gesture
        owner = self.owner
        try:
            new_top, new_height = resize_vertical(edge, top, height, point.y - cursor, work, scale)
            form = owner.window.native
            form.ClientSize = owner.Size(form.ClientSize.Width, new_height)
            form.Location = owner.Point(left, new_top)
        except Exception:
            logging.getLogger(__name__).exception("Could not resize widget")
            self.finish(cancel=True)

    def finish(self, cancel=False):
        self.timer.Stop()
        if not self.gesture:
            return
        _, _, top, height, scale, _, left = self.gesture
        self.gesture = None
        owner = self.owner
        if not owner.window:
            owner.moving = False
            return
        form = owner.window.native
        if cancel:
            form.ClientSize = owner.Size(form.ClientSize.Width, height)
            form.Location = owner.Point(left, top)
        else:
            # Only a user gesture changes the preferred size. Monitor clamps,
            # polling and DPI changes must never overwrite it.
            owner.preferred_height = max(120, min(65536, form.ClientSize.Height / scale))
            owner.host.controller.background_update({"widget_height_css_px": owner.preferred_height})
        owner.on_move_end()

    def dispose(self):
        self.finish(cancel=True)
        self.timer.Dispose()
