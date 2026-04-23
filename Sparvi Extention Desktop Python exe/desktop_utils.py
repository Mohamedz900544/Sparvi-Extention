import ctypes
import platform

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


def get_virtual_desktop_rect():
    app = QGuiApplication.instance()
    screens = app.screens() if app else []

    if not screens:
        return {
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080
        }

    rect = QRect(screens[0].geometry())
    for screen in screens[1:]:
        rect = rect.united(screen.geometry())

    return {
        "left": rect.left(),
        "top": rect.top(),
        "width": max(1, rect.width()),
        "height": max(1, rect.height())
    }


def clamp_ratio(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def normalize_point(x, y, desktop_rect):
    width = max(1, int(desktop_rect["width"]))
    height = max(1, int(desktop_rect["height"]))
    left = int(desktop_rect["left"])
    top = int(desktop_rect["top"])

    x_ratio = clamp_ratio((float(x) - left) / width)
    y_ratio = clamp_ratio((float(y) - top) / height)
    if x_ratio is None or y_ratio is None:
        return None

    return {
        "xRatio": x_ratio,
        "yRatio": y_ratio
    }


def normalize_point_in_rect(x, y, rect):
    width = max(1, int(rect["width"]))
    height = max(1, int(rect["height"]))
    left = int(rect["left"])
    top = int(rect["top"])

    local_x = float(x) - left
    local_y = float(y) - top
    if local_x < 0 or local_x > width or local_y < 0 or local_y > height:
        return None

    x_ratio = clamp_ratio(local_x / width)
    y_ratio = clamp_ratio(local_y / height)
    if x_ratio is None or y_ratio is None:
        return None

    return {
        "xRatio": x_ratio,
        "yRatio": y_ratio
    }


def rect_contains_point(x, y, rect):
    left = int(rect["left"])
    top = int(rect["top"])
    width = max(1, int(rect["width"]))
    height = max(1, int(rect["height"]))
    return (
        float(x) >= left
        and float(x) <= (left + width)
        and float(y) >= top
        and float(y) <= (top + height)
    )


def denormalize_point(x_ratio, y_ratio, desktop_rect):
    normalized_x = clamp_ratio(x_ratio)
    normalized_y = clamp_ratio(y_ratio)
    if normalized_x is None or normalized_y is None:
        return None

    left = int(desktop_rect["left"])
    top = int(desktop_rect["top"])
    width = max(1, int(desktop_rect["width"]))
    height = max(1, int(desktop_rect["height"]))

    return {
        "x": left + (normalized_x * width),
        "y": top + (normalized_y * height)
    }


def get_active_surface_name():
    if platform.system() != "Windows":
        return "Desktop"

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "Desktop"

        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        return title or "Desktop"
    except Exception:
        return "Desktop"


def same_context(local_context, remote_context):
    local_value = str(local_context or "").strip().casefold()
    remote_value = str(remote_context or "").strip().casefold()
    return bool(local_value and remote_value and local_value == remote_value)


def shorten_label(value, max_length=64):
    text = str(value or "").strip()
    if not text:
        return "Desktop"
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3]}..."
