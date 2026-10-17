"""Actual mouse/keyboard dismissal checks against the isolated native demo."""
import ctypes
from ctypes import wintypes


def click_browser(window):
    """Deliver real window mouse messages without moving the user's cursor."""
    api = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    api.PostMessageW.restype = wintypes.BOOL
    handles = []
    def collect(handle, _):
        name = ctypes.create_unicode_buffer(128)
        api.GetClassNameW(handle, name, len(name))
        if name.value == 'Chrome_RenderWidgetHostHWND':
            handles.append(handle)
        return True
    api.EnumChildWindows(window.native.Handle.ToInt64(), callback(collect), 0)
    if not handles:
        raise AssertionError('WebView2 mouse-input window not found')
    rectangle = wintypes.RECT()
    api.GetClientRect(handles[-1], ctypes.byref(rectangle))
    packed = (rectangle.right - 12) | ((rectangle.bottom - 12) << 16)
    for message, buttons in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):
        if not api.PostMessageW(handles[-1], message, buttons, packed):
            raise OSError('Could not deliver a native widget click')


def verify_widget_menu(host, widget, ui, wait_for, result):
    from System.Windows.Forms import Form, FormStartPosition
    original_position = ui(lambda: (widget.native.Left, widget.native.Top))
    def position_for_check():
        work = host.Screen.FromControl(widget.native).WorkingArea
        widget.native.Location = host.Point(work.Left + 400, work.Top + 180)
        widget.native.BringToFront()
    ui(position_for_check)
    position = ui(lambda: (widget.native.Left, widget.native.Top))
    preferences = dict(host.host.controller.value)
    target = None

    def open_menu():
        ui(widget.native.Activate)
        widget.evaluate_js("document.querySelector('#widget').dispatchEvent(new KeyboardEvent('keydown', {key:'F10',shiftKey:true,bubbles:true}))")
        wait_for(lambda: ui(lambda: host.menu is not None and host.menu.Visible), timeout=4)

    def outside_point():
        form = widget.native
        for x, y in ((form.ClientSize.Width - 12, form.ClientSize.Height - 12),
                     (12, form.ClientSize.Height - 12)):
            point = form.PointToScreen(host.Point(x, y))
            if not host.menu.Bounds.Contains(point):
                return point
        raise AssertionError("No widget area outside the popup")

    try:
        result['menu_step'] = 'opening the context menu'
        open_menu()
        result['menu_step'] = 'clicking the widget outside the menu'
        ui(outside_point)
        ui(lambda: click_browser(widget))
        wait_for(lambda: ui(lambda: not host.menu.Visible), timeout=4)
        assert dict(host.host.controller.value) == preferences, 'Menu dismissal ran an action'
        current = ui(lambda: (widget.native.Left, widget.native.Top))
        assert current == position, f'Widget moved during dismissal: {position} -> {current}'
        result['checks'].append('right-click menu dismisses on a click in the widget without running an action')

        def make_target():
            form = Form()
            form.Text = "Widget menu smoke test"
            form.StartPosition = FormStartPosition.Manual
            work = host.Screen.FromControl(widget.native).WorkingArea
            form.Location = host.Point(work.Left + 24, work.Top + 24)
            form.ClientSize = host.Size(200, 100)
            form.Show()
            return form
        target = ui(make_target)
        result['menu_step'] = 'opening before switching windows'
        open_menu()
        result['menu_step'] = 'switching to another window'
        ui(target.Activate)
        wait_for(lambda: ui(lambda: not host.menu.Visible), timeout=4)
        result['checks'].append('right-click menu dismisses when another window gains focus')

        result['menu_step'] = 'opening with the keyboard'
        widget.evaluate_js("document.querySelector('#widget').dispatchEvent(new KeyboardEvent('keydown', {key:'F10',shiftKey:true,bubbles:true}))")
        wait_for(lambda: ui(lambda: host.menu.Visible), timeout=4)
        result['menu_step'] = 'pressing Escape'
        widget.evaluate_js("document.querySelector('#widget').dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true}))")
        wait_for(lambda: ui(lambda: not host.menu.Visible), timeout=4)
        result['checks'].append('keyboard menu dismisses with Escape and reopens normally')

        result['menu_step'] = 'choosing a menu action'
        open_menu()
        ui(lambda: host.pin_item.PerformClick())
        ui(host.menu.Close)
        wait_for(lambda: host.host.controller.value['always_on_top'] != preferences['always_on_top'], timeout=4)
        wait_for(lambda: ui(lambda: not host.menu.Visible), timeout=4)
        host.host.controller.update({'always_on_top': preferences['always_on_top']})
        wait_for(lambda: ui(lambda: widget.native.TopMost) == preferences['always_on_top'], timeout=4)
        result['checks'].append('menu actions still work and close the popup')
        result.pop('menu_step', None)
    finally:
        ui(lambda: host.menu.Close() if host.menu else None)
        if host.host.controller.value['always_on_top'] != preferences['always_on_top']:
            host.host.controller.update({'always_on_top': preferences['always_on_top']})
        if target:
            ui(target.Dispose)
        ui(lambda: setattr(widget.native, 'Location', host.Point(*original_position)))
