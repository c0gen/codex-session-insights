"""Widget geometry in browser CSS pixels and native screen pixels."""
from dataclasses import dataclass
import math

from .desktop_preferences import fit_rectangle


@dataclass(frozen=True)
class WidgetLayout:
    width: float
    height: float
    scale: float
    anchor: str = "top"

    @classmethod
    def read(cls, value):
        if not isinstance(value, dict) or not {"width", "height", "scale"} <= set(value) or set(value) - {"width", "height", "scale", "anchor"}:
            raise ValueError("Expected widget width, height and rendering scale")
        if value.get("anchor", "top") not in {"top", "bottom"}:
            raise ValueError("Invalid widget anchor")
        for key, limit in (("width", 1024), ("height", 65536), ("scale", 8)):
            number = value[key]
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 < number <= limit:
                raise ValueError("Invalid widget dimensions")
        return cls(**value)

    def pixels(self, work_width, work_height, preferred_height=None):
        # DeviceDpi can be 96 while WebView2 renders at 125% plus text scaling.
        # Round up, so fractional pixel sizes cannot clip the final row/border.
        return (min(math.ceil(self.width * self.scale), work_width),
                min(math.ceil((self.height if preferred_height is None else preferred_height) * self.scale), work_height))


def resize_vertical(edge, top, height, delta, work, scale):
    """Resize one edge in physical pixels while the opposite edge stays put."""
    _, work_top, _, work_bottom = work
    bottom = top + height
    minimum = math.ceil(120 * scale)
    if edge == "top":
        available = max(1, bottom - work_top)
        size = max(min(minimum, available), min(height - delta, available))
        return bottom - size, size
    if edge == "bottom":
        available = max(1, work_bottom - top)
        size = max(min(minimum, available), min(height + delta, available))
        return top, size
    raise ValueError("Unknown resize edge")


def restore_position(saved, monitor, work, size, legacy_scale=1):
    left, top, right, bottom = work
    width, height = size
    x, y = right - width - 16, bottom - height - 16
    if isinstance(saved, dict) and saved.get("monitor") == monitor:
        try:
            # Old positions were divided by WinForms DeviceDpi, not WebView DPI.
            # Apply that same conversion once; all new positions are physical.
            scale = 1 if saved.get("version") == 2 else legacy_scale
            x = left + round(float(saved["x"]) * scale)
            y = top + round(float(saved["y"]) * scale)
        except (KeyError, TypeError, ValueError, OverflowError):
            x, y = right - width - 16, bottom - height - 16
    return fit_rectangle(x, y, width, height, work)
