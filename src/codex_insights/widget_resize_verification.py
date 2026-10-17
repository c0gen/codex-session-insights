"""Exercise real native widget geometry with a synthetic cursor; never move the user's mouse."""
import ctypes
from ctypes import wintypes


class SyntheticCursor:
    y, pressed = 400, True

    def GetAsyncKeyState(self, key):
        return 0x8000 if key == 1 and self.pressed else 0

    def GetCursorPos(self, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents.y = self.y
        return True


def verify_widget_resize(controller, widget, ui, wait_for, result, fits):
    host = controller.native.widget_host
    original_api = host.resize.api
    original_height = controller.value.get('widget_height_css_px')
    original_details = controller.value['widget_details_expanded']
    try:
        controller.update({'widget_height_css_px': 240})
        scale = widget.evaluate_js('devicePixelRatio')
        wait_for(lambda: abs(ui(lambda: widget.native.Height) / scale - 240) < 2)
        wait_for(fits)
        for edge in ('top', 'bottom'):
            cursor = SyntheticCursor()
            ui(lambda: setattr(host.resize, 'api', cursor))
            before = ui(lambda: (widget.native.Top, widget.native.Height, widget.native.Width))
            widget.evaluate_js(f"document.querySelector('[data-resize={edge}]').dispatchEvent(new MouseEvent('mousedown', {{button:0,bubbles:true}}))")
            wait_for(lambda: ui(lambda: host.moving))
            cursor.y += round(30 * scale)
            wait_for(lambda: abs(ui(lambda: widget.native.Height) - before[1]) > 10)
            cursor.pressed = False
            wait_for(lambda: not ui(lambda: host.moving))
            after = ui(lambda: (widget.native.Top, widget.native.Height, widget.native.Width))
            assert after[2] == before[2]
            assert after[0] + after[1] == before[0] + before[1] if edge == 'top' else after[0] == before[0]
            assert abs(controller.value['widget_height_css_px'] - after[1] / scale) < 1
            wait_for(fits)

        fixed = ui(lambda: (widget.native.Top, widget.native.Height))
        widget.evaluate_js("document.querySelector('.widget-details-toggle').click()")
        wait_for(lambda: controller.value['widget_details_expanded'] != original_details)
        wait_for(lambda: widget.evaluate_js("document.querySelector('#widget-details').getBoundingClientRect().height") == 0)
        assert ui(lambda: (widget.native.Top, widget.native.Height)) == fixed
        assert widget.evaluate_js("document.querySelector('#widget-scroll').scrollHeight > document.querySelector('#widget-scroll').clientHeight")

        controller.update({'widget_height_css_px': 5000})
        wait_for(lambda: ui(lambda: widget.native.Height == host.Screen.FromControl(widget.native).WorkingArea.Height))
        assert controller.value['widget_height_css_px'] == 5000
        widget.evaluate_js("window.pywebview.api.call('widget_command', {command:'fit_content'})")
        wait_for(lambda: controller.value['widget_height_css_px'] is None)
        wait_for(fits)
        result['checks'].append('top/bottom edge gestures preserve width and opposite edge, persist custom height, keep height on details toggle, clamp without overwriting preference and restore Fit to content')
    finally:
        ui(lambda: setattr(host.resize, 'api', original_api))
        controller.update({'widget_height_css_px': original_height, 'widget_details_expanded': original_details})
