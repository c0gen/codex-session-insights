import ctypes
from ctypes import wintypes
from math import ceil
from types import SimpleNamespace as NS

import pytest

from codex_insights.widget_geometry import WidgetLayout, restore_position, resize_vertical
from codex_insights.widget_resize import VerticalResize
from codex_insights.windows_widget import WindowsWidget, WidgetBridge, native_drag


def test_widget_bridge_exposes_only_the_call_entrypoint():
    bridge = WidgetBridge(NS(host=NS()), 1)
    assert [name for name in dir(bridge) if not name.startswith('_')] == ['call']


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 1.75, 1.7875, 2])
def test_browser_render_scale_includes_windows_text_size(scale):
    layout = WidgetLayout.read({"width": 260, "height": 120, "scale": scale})
    width, height = layout.pixels(1920, 1040)
    assert width / scale >= 260 and height / scale >= 120
    assert width == ceil(260 * scale)
    assert height == ceil(120 * scale)


@pytest.mark.parametrize("value", [None, {}, {"width": True, "height": 120, "scale": 1},
                                   {"width": 260, "height": -1, "scale": 1},
                                   {"width": 260, "height": 120, "scale": float('nan')},
                                   {"width": 260, "height": float('inf'), "scale": 1}])
def test_invalid_layout_never_reaches_native_sizing(value):
    with pytest.raises(ValueError):
        WidgetLayout.read(value)


def test_saved_position_compatibility_and_disconnected_monitor():
    area = (-1920, -200, 0, 1040)
    legacy = {"monitor": "left", "x": 200, "y": 300}
    assert restore_position(legacy, "left", area, (465, 215), 1.25) == (-1670, 175)
    current = {"version": 2, "monitor": "left", "x": 200, "y": 300}
    assert restore_position(current, "left", area, (465, 215), 2) == (-1720, 100)
    assert restore_position(current, "primary", (0, 0, 1920, 1040), (465, 215)) == (1439, 809)
    assert restore_position({**current, "x": 5000, "y": -900}, "left", area, (465, 215)) == (-465, -200)
    assert restore_position({**current, "x": float('nan')}, "left", area, (465, 215)) == (-481, 809)


class MoveAPI:
    def __init__(self, pressed=True):
        self.pressed, self.calls = pressed, []

    def GetAsyncKeyState(self, _): return 0x8000 if self.pressed else 0

    def GetCursorPos(self, pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = -1234, 567
        return True

    def ReleaseCapture(self): self.calls.append('release')

    def SendMessageW(self, *args): self.calls.append(args)


def test_drag_hands_native_cursor_coordinates_to_os_without_css_scaling():
    api = MoveAPI()
    native_drag(api, 123)
    assert api.calls[0] == 'release'
    handle, message, hit, packed = api.calls[1]
    assert (handle, message, hit) == (123, 0xA1, 2)
    assert ctypes.c_short(packed & 0xffff).value == -1234
    assert ctypes.c_short(packed >> 16).value == 567
    released = MoveAPI(pressed=False)
    native_drag(released, 123)
    assert released.calls == []


class Form:
    def __init__(self):
        self.Left, self.Top, self.Width, self.Height = -1500, 100, 260, 120
        self.DeviceDpi = 96
        self.writes = []
        self.Visible = False

    @property
    def ClientSize(self): return NS(Width=self.Width, Height=self.Height)

    @ClientSize.setter
    def ClientSize(self, size):
        self.Width, self.Height = size
        self.writes.append(('size', size))

    @property
    def Location(self): return self.Left, self.Top

    @Location.setter
    def Location(self, point):
        self.Left, self.Top = point
        self.writes.append(('position', point))

    def Show(self): self.Visible = True


def widget():
    form = Form()
    owner = WindowsWidget.__new__(WindowsWidget)
    owner.window = NS(native=form)
    screen = NS(DeviceName='left', WorkingArea=NS(Left=-1920, Top=0, Right=0, Bottom=1040,
                                                Width=1920, Height=1040))
    owner.Screen = NS(FromControl=lambda _: screen, AllScreens=[screen])
    owner.Point = owner.Size = lambda x, y: (x, y)
    owner.host = NS(window=owner.window, dispatch=lambda fn: fn())
    owner.layout = WidgetLayout(260, 120, 1.7875)
    owner.disposed = owner.moving = False
    owner.placed = True
    owner.timer = NS(Stop=lambda: None, Start=lambda: None)
    owner.position = None
    owner.preferred_height = None
    owner.generation = 2
    return owner, form


def test_fit_uses_effective_scale_without_moving_or_resizing_repeatedly():
    owner, form = widget()
    owner.fit()
    assert (form.Width, form.Height) == (465, 215)  # DeviceDpi incorrectly says 96.
    assert form.Location == (-1500, 100)
    assert form.writes == [('size', (465, 215))]
    owner.fit()
    assert len(form.writes) == 1
    owner.update_layout(WidgetLayout(260, 146, 1.7875))
    assert form.Location == (-1500, 100)


def test_dpi_and_layout_changes_wait_until_drag_finishes():
    owner, form = widget()
    owner.moving = True
    owner.update_layout(WidgetLayout(260, 146, 2))
    assert form.writes == []
    owner.moving = False
    owner.fit()
    assert (form.Width, form.Height) == (520, 292)
    assert form.Location == (-1500, 100)


def test_details_expand_upward_and_collapse_back_to_the_same_usage_position():
    owner, form = widget()
    owner.update_layout(WidgetLayout.read({"width": 240, "height": 120, "scale": 1, "anchor": "bottom"}))
    bottom = form.Top + form.Height
    owner.update_layout(WidgetLayout(240, 180, 1, "bottom"))
    assert (form.Top, form.Top + form.Height) == (bottom - 180, bottom)
    owner.update_layout(WidgetLayout(240, 120, 1, "bottom"))
    assert (form.Top, form.Top + form.Height) == (bottom - 120, bottom)


def test_upward_expansion_stays_inside_the_monitor_work_area():
    owner, form = widget()
    form.Top = 10
    owner.update_layout(WidgetLayout(240, 800, 1, "bottom"))
    assert form.Top == 0
    assert form.Top + form.Height <= 1040


def test_layout_rejects_unknown_anchors():
    with pytest.raises(ValueError):
        WidgetLayout.read({"width": 240, "height": 120, "scale": 1, "anchor": "left"})


def test_first_placement_legacy_restore_and_new_physical_position_save():
    owner, form = widget()
    owner.placed = False
    owner.position = {"monitor": "left", "x": 300, "y": 100}
    owner.fit()
    assert form.Location == (-1620, 100) and form.Visible
    saved = {}
    owner.writer = NS(submit=lambda fn: fn())
    owner.host.store = NS(set_setting=lambda key, value: saved.update({key: value}))
    owner.save_position()
    assert saved['widget_position'] == {"version": 2, "monitor": "left", "x": 300, "y": 100}


def test_old_webview_cannot_resize_reopened_widget():
    owner, form = widget()
    owner.request('widget_layout', {'width': 260, 'height': 500, 'scale': 2}, generation=1)
    assert form.writes == []
    assert owner.layout.height == 120


def test_menu_dismissal_is_safe_before_opening_and_ignores_an_old_widget():
    owner, _ = widget()
    owner.menu = None
    owner.request('widget_command', {'command': 'dismiss_menu'}, generation=2)
    closed = []
    owner.menu = NS(Close=lambda: closed.append(True))
    owner.request('widget_command', {'command': 'dismiss_menu'}, generation=1)
    assert closed == []
    owner.request('widget_command', {'command': 'dismiss_menu'}, generation=2)
    assert closed == [True]


def test_custom_height_survives_content_changes_dpi_and_monitor_clamping():
    owner, form = widget()
    owner.preferred_height = 700
    owner.fit()
    assert form.Height == 1040
    assert owner.preferred_height == 700
    owner.update_layout(WidgetLayout(240, 90, 1, "bottom"))
    assert form.Height == 700
    top = form.Top
    owner.update_layout(WidgetLayout(240, 5000, 1, "bottom"))
    assert form.Height == 700 and form.Top == top
    owner.preferred_height = None
    owner.update_layout(WidgetLayout(240, 90, 1, "bottom"))
    assert form.Height == 90


@pytest.mark.parametrize("edge,delta,expected", [
    ("top", 50, (150, 250)), ("top", 1000, (280, 120)),
    ("top", -1000, (0, 400)), ("bottom", 200, (100, 500)),
    ("bottom", 1000, (100, 940)), ("bottom", -1000, (100, 120)),
])
def test_edge_resize_keeps_opposite_edge_fixed(edge, delta, expected):
    assert resize_vertical(edge, 100, 300, delta, (0, 0, 1920, 1040), 1) == expected


def test_resize_minimum_uses_browser_scale_and_small_work_areas():
    assert resize_vertical("bottom", -100, 400, -1000, (-1920, -200, 0, 1040), 2) == (-100, 240)
    assert resize_vertical("top", 0, 80, -100, (0, 0, 240, 80), 2) == (0, 80)


class TimerEvent:
    def __iadd__(self, _): return self


class ResizeMouse:
    y, pressed, escape = 200, True, False
    def GetAsyncKeyState(self, key): return 0x8000 if (self.escape if key == 0x1B else self.pressed) else 0
    def GetCursorPos(self, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents.y = self.y
        return True


@pytest.mark.parametrize("edge", ["top", "bottom"])
def test_resize_gesture_commits_only_on_release_and_can_be_cancelled(edge):
    owner, form = widget()
    owner.layout = WidgetLayout(240, 300, 1)
    owner.menu = None
    owner.fit()
    saved = []
    owner.host.controller = NS(background_update=lambda value: saved.append(value))
    owner.host.store = NS(set_setting=lambda *_: None)
    owner.writer = NS(submit=lambda fn: fn())
    api = ResizeMouse()
    timer = NS(Tick=TimerEvent(), Start=lambda: None, Stop=lambda: None, Dispose=lambda: None)
    gesture = VerticalResize(owner, api, timer)
    gesture.start(edge)
    assert owner.moving
    api.y += 60
    gesture.tick()
    assert saved == []
    expected = 240 if edge == "top" else 360
    assert form.Height == expected
    owner.update_layout(WidgetLayout(240, 900, 1, "bottom"))
    assert form.Height == expected
    api.pressed = False
    gesture.tick()
    assert saved == [{"widget_height_css_px": expected}]
    assert not owner.moving and form.Height == expected
    original = (form.Top, form.Height)
    api.pressed = True
    gesture.start(edge)
    api.y += 40
    gesture.tick()
    api.escape = True
    gesture.tick()
    assert (form.Top, form.Height) == original
    assert len(saved) == 1 and not owner.moving
