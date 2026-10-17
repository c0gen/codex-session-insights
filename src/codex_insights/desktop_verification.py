"""Opt-in native integration checks using an isolated demo index, never real chats."""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def verify_desktop(engine, window, destination, images=None):
    result = {"ok": False, "checks": []}
    controller = engine.desktop

    def wait_for(check, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.1)
        raise AssertionError("Native check timed out")

    def ui(fn):
        done, values = threading.Event(), []
        def invoke():
            try:
                values.append(fn())
            except Exception as error:
                values.append(error)
            finally:
                done.set()
        controller.native.dispatch(invoke)
        if not done.wait(10):
            raise AssertionError("GUI dispatch timed out")
        if isinstance(values[0], Exception):
            raise values[0]
        return values[0]

    try:
        if not engine.store.setting("demo", False):
            raise ValueError("Desktop verification requires --demo and an isolated --data-dir")
        wait_for(lambda: controller and controller.tray_active)
        assert not controller.value["widget_enabled"]
        result["checks"].append("default tray on, widget off")
        if images and not os.environ.get('CODEX_INSIGHTS_WIDGET_SMOKE_ONLY'):
            from .summary_image_verification import verify_summary_image
            verify_summary_image(window, images, ui, wait_for, destination, result)
        elif images:
            result['image_checks'] = 'skipped for widget-only verification'
        window.destroy()
        wait_for(lambda: not ui(lambda: window.native.Visible))
        assert not engine.stop.is_set()
        result["checks"].append("close hides without stopping engine")

        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command += ["-m", "codex_insights"]
        command += ["--data-dir", str(engine.store.directory), "gui"]
        child = subprocess.run(command, capture_output=True, timeout=20,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        assert child.returncode == 0
        wait_for(lambda: ui(lambda: window.native.Visible))
        result["checks"].append("relaunch activates the existing process")

        controller.command("show_settings")
        wait_for(lambda: window.evaluate_js("!!document.querySelector('[data-desktop=widget_height_mode]') && !!document.querySelector('[data-desktop=widget_enabled]')"))
        window.evaluate_js("document.querySelector('[data-desktop=widget_enabled]').click()")
        wait_for(lambda: controller.native.widget is not None)
        widget = controller.native.widget
        assert widget.events.loaded.wait(15)
        wait_for(lambda: widget.evaluate_js("document.querySelectorAll('tbody tr').length") == 3)
        assert ui(lambda: widget.native.TopMost and controller.native.is_tool_window(widget.native))
        result["checks"].append("settings toggle opens populated native widget")

        from .widget_verification import verify_widget
        widget = verify_widget(controller, widget, ui, wait_for, result)
        controller.update({"metrics": []})
        wait_for(lambda: widget.evaluate_js("!!document.querySelector('.empty button')"))
        controller.update({"metrics": ["cost", "chats"]})
        wait_for(lambda: widget.evaluate_js("document.querySelectorAll('tbody tr').length") == 2)
        result["checks"].append("pin and configurable metrics apply immediately")

        def offscreen():
            widget.native.Location = controller.native.Point(100000, 100000)
            controller.native.fit_widget()
            work = controller.native.Screen.FromControl(widget.native).WorkingArea
            return work.Contains(widget.native.Bounds)
        assert ui(offscreen)
        widget.destroy()
        wait_for(lambda: controller.native.widget is None and not controller.value["widget_enabled"])
        result["checks"].append("offscreen position recovery and widget close")

        for tray, show in ((False, True), (False, False), (True, True), (True, False)):
            controller.update({"tray_enabled": tray, "widget_enabled": show})
            wait_for(lambda: controller.tray_active == tray and bool(controller.native.widget) == show)
        window.destroy()
        wait_for(lambda: not ui(lambda: window.native.Visible))
        controller.update({"tray_enabled": False})
        wait_for(lambda: ui(lambda: window.native.Visible) and not controller.tray_active)
        result["checks"].append("independent switches and hidden-dashboard recovery")

        ensure = controller.native.ensure_tray
        def fail():
            raise OSError("Injected tray initialization failure for verification")
        controller.native.ensure_tray = fail
        controller.update({"tray_enabled": True})
        wait_for(lambda: controller.error is not None)
        assert not controller.tray_active and ui(lambda: window.native.Visible)
        controller.native.ensure_tray = ensure
        controller.update({"tray_enabled": True, "widget_enabled": True})
        wait_for(lambda: controller.tray_active and controller.native.widget is not None)
        result["checks"].append("tray failure leaves dashboard accessible")

        assert engine.submit("Verification job", lambda: engine.cancel.wait(10))["status"] == "started"
        controller.command("quit")
        wait_for(lambda: engine.stop.is_set() and engine.cancel.is_set())
        result["checks"].append("quit cancels active work and closes desktop surfaces")
        result["ok"] = True
    except Exception as error:
        log.exception("Desktop verification failed")
        result["error"] = str(error)
    finally:
        if controller and controller.native and not controller.quitting:
            controller.command("quit")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
