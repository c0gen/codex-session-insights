"""Small, version-independent desktop preferences stored separately from pricing."""
import threading
import logging
import copy
import math
from concurrent.futures import ThreadPoolExecutor
from .account_storage import connection_id

METRICS = ("tokens", "cost", "lines", "chats")
DEFAULTS = {"tray_enabled": True, "widget_enabled": False, "always_on_top": True,
            "metrics": ["tokens", "cost", "lines"], "show_usage_remaining": False,
            "widget_details_expanded": True, "widget_height_css_px": None,
            "usage_remaining_bucket": "codex", "widget_account_ids": ["current"],
            "widget_account_buckets": {}}


class DesktopPreferences:
    def __init__(self, store, background=False):
        self.store = store
        self.lock = threading.RLock()
        self.revision = 0
        self.error = None
        self.writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insights-preferences") if background else None
        self.value = self._load()
        self.closed = False

    def _load(self):
        saved = self.store.setting("desktop_preferences", {})
        result = copy.deepcopy(DEFAULTS)
        if isinstance(saved, dict):
            for key in ("tray_enabled", "widget_enabled", "always_on_top", "show_usage_remaining", "widget_details_expanded"):
                if type(saved.get(key)) is bool:
                    result[key] = saved[key]
            if isinstance(saved.get("metrics"), list):
                result["metrics"] = [key for key in METRICS if key in saved["metrics"]]
            if valid_widget_height(saved.get("widget_height_css_px")):
                result["widget_height_css_px"] = saved.get("widget_height_css_px")
            if isinstance(saved.get("usage_remaining_bucket"), str):
                result["usage_remaining_bucket"] = saved["usage_remaining_bucket"]
            if isinstance(saved.get("widget_account_ids"), list):
                result["widget_account_ids"] = list(dict.fromkeys(
                    item for item in saved["widget_account_ids"] if connection_id(item)))
            if isinstance(saved.get("widget_account_buckets"), dict):
                result["widget_account_buckets"] = {key: value for key, value in saved["widget_account_buckets"].items()
                    if connection_id(key) and isinstance(value, str) and 0 < len(value) <= 200}
        return result

    def read(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def _save(self, value):
        try:
            self.store.set_setting("desktop_preferences", value)
            self.error = None
        except Exception:
            logging.getLogger(__name__).exception("Could not save desktop preferences")
            self.error = "Desktop preferences could not be saved. Try changing them again in Settings."

    def update(self, changes):
        if not isinstance(changes, dict) or changes.keys() - DEFAULTS.keys():
            raise ValueError("Unknown desktop preference")
        for key, value in changes.items():
            if key == "widget_height_css_px":
                if not valid_widget_height(value):
                    raise ValueError("Widget height must be automatic or 120–65536 CSS pixels")
            elif key == "metrics":
                if not isinstance(value, list) or any(item not in METRICS for item in value):
                    raise ValueError("Choose supported widget metrics")
            elif key == "widget_account_ids":
                if not isinstance(value, list) or len(value) > 100 or any(not connection_id(item) for item in value) or len(set(value)) != len(value):
                    raise ValueError("Choose distinct widget accounts in display order")
            elif key == "widget_account_buckets":
                if not isinstance(value, dict) or len(value) > 100 or any(not connection_id(k) or not isinstance(v, str) or not 0 < len(v) <= 200 for k, v in value.items()):
                    raise ValueError("Choose an allowance bucket for each account")
            elif key == "usage_remaining_bucket":
                if not isinstance(value, str) or not 0 < len(value) <= 200:
                    raise ValueError("Choose an allowance bucket")
            elif type(value) is not bool:
                raise ValueError("Desktop switches must be true or false")
        with self.lock:
            if self.closed:
                raise ValueError("Desktop is closing")
            value = {**self.read(), **copy.deepcopy(changes)}
            value["metrics"] = [key for key in METRICS if key in value["metrics"]]
            if self.writer:
                # A long index transaction must not block window switches.
                # Serialize durable writes separately and drain them on exit.
                self.writer.submit(self._save, value)
            else:
                self.store.set_setting("desktop_preferences", value)
            self.value = value
            self.revision += 1
            return self.read()

    def close(self):
        with self.lock:
            self.closed = True
        if self.writer:
            self.writer.shutdown(wait=True)


def valid_widget_height(value):
    return value is None or (type(value) in (int, float) and math.isfinite(value) and 120 <= value <= 65536)


def fit_rectangle(x, y, width, height, work_area):
    """Clamp a widget rectangle into an OS work area, including negative origins."""
    left, top, right, bottom = work_area
    return (max(left, min(x, right - width)), max(top, min(y, bottom - height)))
