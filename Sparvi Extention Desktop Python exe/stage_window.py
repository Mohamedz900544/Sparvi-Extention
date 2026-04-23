import ctypes
import ctypes.wintypes

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from desktop_utils import get_virtual_desktop_rect


STAGE_BORDER = 8
STAGE_BAR_HEIGHT = 32
STAGE_BAR_GAP = 8
STAGE_MIN_WIDTH = 280
STAGE_MIN_HEIGHT = 180
STAGE_MARGIN = 12
STAGE_TOP_RESERVE = 64
STAGE_RIGHT_RESERVE = 84


class InstructorStageWindow(QWidget):
    geometry_changed = Signal(dict)

    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        self._interaction_mode = ""
        self._interaction_start_pos = QPoint()
        self._interaction_start_geometry = QRect()
        self._desktop_rect = get_virtual_desktop_rect()
        self._stage_active = False

        self._configure_window()
        self._restore_geometry()
        self._update_mask()
        self.hide()

    def _configure_window(self):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        if hasattr(Qt.WindowType, "WindowDoesNotAcceptFocus"):
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle("Sparvi Instructor Stage")

    def _restore_geometry(self):
        left = self._settings.value("stage/left", None)
        top = self._settings.value("stage/top", None)
        width = self._settings.value("stage/width", None)
        height = self._settings.value("stage/height", None)

        if None in (left, top, width, height):
            self._apply_default_geometry()
            return

        try:
            next_rect = QRect(
                int(left),
                int(top),
                max(STAGE_MIN_WIDTH, int(width)),
                max(STAGE_MIN_HEIGHT, int(height))
            )
        except (TypeError, ValueError):
            self._apply_default_geometry()
            return

        next_rect = self._constrain_geometry(next_rect)
        self.setGeometry(next_rect)

    def _apply_default_geometry(self):
        desktop_rect = self._desktop_rect
        width = min(760, max(STAGE_MIN_WIDTH, desktop_rect["width"] - 80))
        height = min(440, max(STAGE_MIN_HEIGHT, desktop_rect["height"] - 120))
        left = desktop_rect["left"] + max(STAGE_MARGIN, (desktop_rect["width"] - width) // 2)
        top = desktop_rect["top"] + max(72, (desktop_rect["height"] - height) // 2)
        self.setGeometry(self._constrain_geometry(QRect(left, top, width, height)))

    def set_stage_visible(self, visible):
        if visible:
            self._desktop_rect = get_virtual_desktop_rect()
            self.setGeometry(self._constrain_geometry(self.geometry()))
            self._update_mask()
            self.show()
            self.raise_()
        else:
            self.hide()
            self.set_stage_active(False)

    def stage_rect(self):
        rect = self.geometry()
        return {
            "left": rect.x(),
            "top": rect.y(),
            "width": rect.width(),
            "height": rect.height()
        }

    def is_interacting(self):
        return bool(self._interaction_mode)

    def center_point(self):
        rect = self.geometry()
        return {
            "x": rect.x() + (rect.width() / 2),
            "y": rect.y() + (rect.height() / 2)
        }

    def content_rect(self):
        local_rect = self._content_rect_local()
        rect = self.geometry()
        return {
            "left": rect.x() + local_rect.x(),
            "top": rect.y() + local_rect.y(),
            "width": local_rect.width(),
            "height": local_rect.height()
        }

    def native_content_rect(self):
        native_rect = self._native_window_rect()
        if not native_rect:
            return self.content_rect()

        local_rect = self._content_rect_local()
        logical_width = max(1, self.width())
        logical_height = max(1, self.height())

        scale_x = native_rect["width"] / logical_width
        scale_y = native_rect["height"] / logical_height

        return {
            "left": native_rect["left"] + int(round(local_rect.x() * scale_x)),
            "top": native_rect["top"] + int(round(local_rect.y() * scale_y)),
            "width": max(1, int(round(local_rect.width() * scale_x))),
            "height": max(1, int(round(local_rect.height() * scale_y)))
        }

    def content_center_point(self):
        rect = self.content_rect()
        return {
            "x": rect["left"] + (rect["width"] / 2),
            "y": rect["top"] + (rect["height"] / 2)
        }

    def native_content_center_point(self):
        rect = self.native_content_rect()
        return {
            "x": rect["left"] + (rect["width"] / 2),
            "y": rect["top"] + (rect["height"] / 2)
        }

    def set_stage_active(self, active):
        next_value = bool(active)
        if self._stage_active == next_value:
            return
        self._stage_active = next_value
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()
        self._emit_geometry_changed()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._emit_geometry_changed()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        mode = self._hit_test_mode(event.position().toPoint())
        if not mode:
            event.accept()
            return

        self._interaction_mode = mode
        self._interaction_start_pos = event.globalPosition().toPoint()
        self._interaction_start_geometry = QRect(self.geometry())
        event.accept()

    def mouseMoveEvent(self, event):
        local_pos = event.position().toPoint()
        global_pos = event.globalPosition().toPoint()

        if self._interaction_mode:
            delta = global_pos - self._interaction_start_pos
            next_geometry = QRect(self._interaction_start_geometry)

            if self._interaction_mode == "move":
                next_geometry.moveTopLeft(self._interaction_start_geometry.topLeft() + delta)
            else:
                self._apply_resize_delta(next_geometry, delta)

            self.setGeometry(self._constrain_geometry(next_geometry))
            event.accept()
            return

        self.setCursor(self._cursor_for_mode(self._hit_test_mode(local_pos)))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._interaction_mode:
            self._interaction_mode = ""
            self._save_geometry()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        event.accept()

    def leaveEvent(self, event):
        if not self._interaction_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body_rect = self._body_rect_local()
        bar_rect = self._bar_rect_local()

        border_color = QColor(20, 184, 166, 235) if self._stage_active else QColor(37, 99, 235, 230)
        header_color = QColor(15, 118, 110, 236) if self._stage_active else QColor(15, 23, 42, 236)
        hint_color = QColor(15, 118, 110, 210) if self._stage_active else QColor(37, 99, 235, 180)
        body_color = QColor(232, 250, 246, 252) if self._stage_active else QColor(237, 244, 255, 252)

        painter.setBrush(body_color)
        painter.drawRoundedRect(body_rect, 8, 8)

        painter.setPen(QPen(border_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body_rect, 10, 10)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(header_color)
        painter.drawRoundedRect(bar_rect, 8, 8)

        title_font = QFont("Segoe UI", 10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            bar_rect.adjusted(12, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Live Pointer Area"
        )

        painter.setPen(hint_color)
        painter.drawText(
            QRect(
                body_rect.left() + 12,
                body_rect.bottom() - 24,
                max(100, body_rect.width() - 24),
                18
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Move inside this frame to teach"
        )

        painter.end()

    def _update_mask(self):
        self.setMask(QRegion(self._body_rect_local()).united(QRegion(self._bar_rect_local())))

    def _hit_test_mode(self, pos):
        body_rect = self._body_rect_local()
        bar_rect = self._bar_rect_local()
        x = pos.x()
        y = pos.y()
        edge = STAGE_BORDER + 4

        left_edge = abs(x - body_rect.left()) <= edge and body_rect.top() - edge <= y <= body_rect.bottom() + edge
        right_edge = abs(x - body_rect.right()) <= edge and body_rect.top() - edge <= y <= body_rect.bottom() + edge
        top_edge = abs(y - body_rect.top()) <= edge and body_rect.left() - edge <= x <= body_rect.right() + edge
        bottom_edge = abs(y - body_rect.bottom()) <= edge and body_rect.left() - edge <= x <= body_rect.right() + edge

        if top_edge and left_edge:
            return "nw"
        if top_edge and right_edge:
            return "ne"
        if bottom_edge and left_edge:
            return "sw"
        if bottom_edge and right_edge:
            return "se"
        if left_edge:
            return "w"
        if right_edge:
            return "e"
        if top_edge:
            return "n"
        if bottom_edge:
            return "s"
        if bar_rect.contains(pos):
            return "move"
        return ""

    def _cursor_for_mode(self, mode):
        mapping = {
            "move": Qt.CursorShape.SizeAllCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor
        }
        return mapping.get(mode, Qt.CursorShape.ArrowCursor)

    def _apply_resize_delta(self, rect, delta):
        mode = self._interaction_mode
        if "w" in mode:
            rect.setLeft(rect.left() + delta.x())
        if "e" in mode:
            rect.setRight(rect.right() + delta.x())
        if "n" in mode:
            rect.setTop(rect.top() + delta.y())
        if "s" in mode:
            rect.setBottom(rect.bottom() + delta.y())

        if rect.width() < STAGE_MIN_WIDTH:
            if "w" in mode:
                rect.setLeft(rect.right() - STAGE_MIN_WIDTH + 1)
            else:
                rect.setWidth(STAGE_MIN_WIDTH)

        if rect.height() < STAGE_MIN_HEIGHT:
            if "n" in mode:
                rect.setTop(rect.bottom() - STAGE_MIN_HEIGHT + 1)
            else:
                rect.setHeight(STAGE_MIN_HEIGHT)

    def _constrain_geometry(self, rect):
        desktop_rect = get_virtual_desktop_rect()
        self._desktop_rect = desktop_rect

        max_width = max(
            STAGE_MIN_WIDTH,
            desktop_rect["width"] - (STAGE_MARGIN * 2) - STAGE_RIGHT_RESERVE
        )
        max_height = max(
            STAGE_MIN_HEIGHT,
            desktop_rect["height"] - STAGE_MARGIN - STAGE_TOP_RESERVE
        )

        width = min(max(rect.width(), STAGE_MIN_WIDTH), max_width)
        height = min(max(rect.height(), STAGE_MIN_HEIGHT), max_height)

        left_min = desktop_rect["left"] + STAGE_MARGIN
        top_min = desktop_rect["top"] + STAGE_TOP_RESERVE
        left_max = desktop_rect["left"] + desktop_rect["width"] - width - STAGE_MARGIN - STAGE_RIGHT_RESERVE
        top_max = desktop_rect["top"] + desktop_rect["height"] - height - STAGE_MARGIN

        left = min(max(rect.x(), left_min), max(left_min, left_max))
        top = min(max(rect.y(), top_min), max(top_min, top_max))

        return QRect(int(left), int(top), int(width), int(height))

    def _save_geometry(self):
        rect = self.geometry()
        self._settings.setValue("stage/left", rect.x())
        self._settings.setValue("stage/top", rect.y())
        self._settings.setValue("stage/width", rect.width())
        self._settings.setValue("stage/height", rect.height())

    def _emit_geometry_changed(self):
        rect = self.stage_rect()
        self.geometry_changed.emit(rect)

    def _bar_rect_local(self):
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance("Live Pointer Area")
        width = max(176, text_width + 28)
        return QRect(
            12,
            2,
            min(width, max(120, self.width() - 24)),
            STAGE_BAR_HEIGHT
        )

    def _body_rect_local(self):
        top = STAGE_BAR_HEIGHT + STAGE_BAR_GAP + 2
        return QRect(
            2,
            top,
            max(1, self.width() - 4),
            max(1, self.height() - top - 2)
        )

    def _content_rect_local(self):
        return self._body_rect_local().adjusted(
            STAGE_BORDER,
            STAGE_BORDER,
            -STAGE_BORDER,
            -STAGE_BORDER
        )

    def _native_window_rect(self):
        if not self.isVisible():
            return None

        if not hasattr(ctypes, "windll") or not hasattr(ctypes.windll, "user32"):
            return None

        hwnd = int(self.winId())
        if not hwnd:
            return None

        rect = ctypes.wintypes.RECT()
        try:
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
        except Exception:
            return None

        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "width": max(1, int(rect.right - rect.left)),
            "height": max(1, int(rect.bottom - rect.top))
        }
