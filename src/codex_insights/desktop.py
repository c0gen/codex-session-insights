"""Native window lifecycle and packaged-app verification."""
import json
import logging
import os
import platform
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def verify_native(window, destination, exporter=False):
    result = {"ok": False}
    minimum = int(os.environ.get("CODEX_INSIGHTS_SMOKE_MIN_TOKENS", "0"))
    try:
        for _ in range(150):
            window.evaluate_js("window.pywebview.api.call('dashboard',{}).then(d=>window.__nativeSmoke={tokens:d.summary.total_tokens,bridge:true,running:d.job.running});")
            value = window.evaluate_js("({heading:document.querySelector('h1')?.textContent,bridge:window.__nativeSmoke,canvas:!!document.querySelector('canvas'),sources:!!document.querySelector('.source-cards'),exportControl:!!document.querySelector('#export-snapshot')})")
            content_ready = value and (value.get('heading') == 'Mac Exporter' and value.get('sources') and value.get('exportControl') if exporter else value.get('canvas'))
            if value and value.get("heading") and value.get("bridge", {}).get("tokens", -1) >= minimum and not value['bridge'].get('running', True) and content_ready:
                result = {"ok": True, **value}
                break
            time.sleep(.2)
    except Exception as error:
        log.exception("Native verification failed")
        result["error"] = str(error)
    finally:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result), encoding="utf-8")
        window.destroy()


def run_desktop(engine, url, smoke_result=None, instance=None):
    log.info("Loading native window dependencies")
    import webview
    from .summary_image_clipboard import SummaryImageBridge, IMAGE_ACTIONS
    from .summary_image_preferences import SummaryImagePreferences
    images = SummaryImageBridge(lambda: engine.window, engine.stop.is_set,
                                SummaryImagePreferences(engine.store.directory / "summary-image-preferences.json"))

    class Bridge:
        def call(self, action, args=None):
            if action in IMAGE_ACTIONS:
                if platform.system() != "Windows" or engine.exporter:
                    raise ValueError("Image copying is available in the Windows dashboard")
                return images.call(action, args)
            return engine.call(action, args)

    smoke = smoke_result or os.environ.get("CODEX_INSIGHTS_SMOKE_RESULT")
    smoke = Path(smoke) if smoke else None
    desktop_check = os.environ.get("CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT")
    log.info("Creating desktop window")
    window = engine.window = webview.create_window(
        "Codex Session Insights", url, js_api=Bridge(),
        width=1000 if engine.exporter else 1500,
        height=720 if engine.exporter else 960, min_size=(850, 600),
        background_color="#10171c", hidden=bool(smoke or desktop_check),
    )
    started = threading.Event()
    native_ready = threading.Event()
    controller = None
    if platform.system() == "Windows" and not engine.exporter and not smoke:
        from .desktop_controller import DesktopController
        # `loaded` fires again for every page reload ("Try again" after a
        # startup error); the tray, widget and activation listener exist once.
        prepared = threading.Event()

        def prepare_native():
            nonlocal controller
            if prepared.is_set():
                return
            prepared.set()
            try:
                controller = engine.desktop = DesktopController(engine)
                from .windows_desktop import WindowsDesktop
                controller.attach(WindowsDesktop(window, url, Bridge(), engine.store))
                if instance:
                    instance.listen(lambda: controller.command("show_dashboard"))
                native_ready.set()
            except Exception:
                log.exception("Optional desktop integration unavailable")
                engine.desktop = None
                if instance:
                    instance.listen(window.show)
                native_ready.set()
        if hasattr(engine, 'when_ready'):
            def prepare_when_ready():
                if prepared.is_set():
                    return
                def dispatch():
                    if engine.stop.is_set():
                        return
                    from System import Action
                    window.native.BeginInvoke(Action(prepare_native))
                engine.when_ready(dispatch)
            window.events.loaded += prepare_when_ready
        else:
            window.events.before_show += prepare_native

    def loaded():
        log.info("Dashboard loaded")
        first_load = not started.is_set()
        if first_load and not engine.stop.is_set():
            started.set()
            # Show the UI before starting an initial session scan.
            engine.start()
        if smoke:
            verify_native(window, smoke, exporter=engine.exporter)
        elif desktop_check and first_load:
            if hasattr(engine, 'ready'):
                engine.ready.wait(30)
                native_ready.wait(10)
            from .desktop_verification import verify_desktop
            verify_desktop(engine, window, desktop_check, images)

    window.events.loaded += loaded
    window.events.shown += lambda: log.info("Native window shown")
    window.events.closed += lambda: log.info("Native window closed")
    try:
        webview.start(
            gui="edgechromium" if platform.system() == "Windows" else None,
            storage_path=str(engine.store.directory / "webview"),
        )
    finally:
        if instance:
            instance.stopped.set()
        if controller:
            controller.dispose()
        engine.desktop = None


def diagnose():
    """Check native prerequisites without scanning sessions or opening a window."""
    from . import __version__
    from .report import ui_directory
    result = {
        "app_version": __version__, "python": platform.python_version(),
        "platform": platform.system(), "architecture": platform.machine(),
        "frontend_present": (ui_directory() / "index.html").is_file(),
    }
    from .sqlite_runtime import diagnostic as sqlite_diagnostic
    result['sqlite'] = sqlite_diagnostic()
    try:
        from webview.guilib import initialize
        backend = initialize("edgechromium" if platform.system() == "Windows" else None)
        result["renderer"] = backend.renderer
        result["ok"] = result["frontend_present"] and (
            platform.system() != "Windows" or backend.renderer == "edgechromium")
    except Exception as error:
        log.exception("Native prerequisite check failed")
        result.update(ok=False, error=str(error))
    return result
