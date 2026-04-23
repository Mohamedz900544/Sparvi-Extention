import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from desktop_utils import denormalize_point, get_virtual_desktop_rect, shorten_label


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._desktop_rect = get_virtual_desktop_rect()
        self._pointer_visible = False
        self._pointer_enabled = False
        self._current_x = 0.0
        self._current_y = 0.0
        self._target_x = 0.0
        self._target_y = 0.0
        self._pointer_label = "Teacher"
        self._pointer_last_update = 0.0
        self._click_pulses = []
        self._laser_points = []
        self._drawings = []
        self._freeze_markers = []
        self._hotspots = []
        self._highlights = []
        self._mismatch_visible = False
        self._mismatch_message = "Teacher is on a different app or window"

        self._configure_window()
        self._apply_geometry()

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._tick)
        self._animation_timer.start(16)

        self._geometry_timer = QTimer(self)
        self._geometry_timer.timeout.connect(self._refresh_geometry_if_needed)
        self._geometry_timer.start(2000)

        self.show()

    def _configure_window(self):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Sparvi Desktop Overlay")

    def _apply_geometry(self):
        rect = self._desktop_rect
        self.setGeometry(
            int(rect["left"]),
            int(rect["top"]),
            int(rect["width"]),
            int(rect["height"])
        )

    def _refresh_geometry_if_needed(self):
        next_rect = get_virtual_desktop_rect()
        if next_rect != self._desktop_rect:
            self._desktop_rect = next_rect
            self._apply_geometry()
            self.update()

    def set_remote_pointer(self, x_ratio, y_ratio, label="Teacher"):
        point = self._ratios_to_local_point(x_ratio, y_ratio)
        if point is None:
            return

        local_x, local_y = point

        if not self._pointer_visible:
            self._current_x = local_x
            self._current_y = local_y

        self._target_x = local_x
        self._target_y = local_y
        self._pointer_label = shorten_label(label, max_length=24)
        self._pointer_visible = True
        self._pointer_last_update = time.monotonic()
        self.update()

    def show_click_pulse(self, x_ratio, y_ratio):
        point = self._ratios_to_local_point(x_ratio, y_ratio)
        if point is None:
            return

        self._click_pulses.append({
            "x": point[0],
            "y": point[1],
            "created_at": time.monotonic()
        })
        self.update()

    def render_teaching_tool_event(self, event):
        kind = str((event or {}).get("kind") or "").strip()
        if not kind:
            return

        if kind == "laser_point":
            self._render_laser_point(event)
        elif kind in {"draw_arrow", "draw_circle", "draw_underline"}:
            self._render_drawing(event)
        elif kind == "highlight_element":
            self._render_highlight(event)
        elif kind == "freeze_marker":
            self._render_freeze_marker(event)
        elif kind == "guided_hotspot":
            self._render_hotspot(event)
        elif kind == "clear_tools":
            self.clear_teaching_artifacts()

    def clear_teaching_artifacts(self):
        self._laser_points = []
        self._drawings = []
        self._freeze_markers = []
        self._hotspots = []
        self._highlights = []
        self.update()

    def set_context_mismatch(self, mismatch, teacher_context=""):
        self._mismatch_visible = bool(mismatch)
        if teacher_context:
            self._mismatch_message = f"Teacher is on: {shorten_label(teacher_context, 48)}"
        else:
            self._mismatch_message = "Teacher is on a different app or window"
        self.update()

    def set_teacher_pointer_enabled(self, enabled):
        self._pointer_enabled = bool(enabled)
        if not self._pointer_enabled:
            self.clear_pointer()

    def clear_pointer(self):
        self._pointer_visible = False
        self.update()

    def _tick(self):
        now = time.monotonic()
        needs_repaint = False

        if self._pointer_visible:
            if (now - self._pointer_last_update) > 1.5:
                self._pointer_visible = False
                needs_repaint = True
            else:
                self._current_x += (self._target_x - self._current_x) * 0.28
                self._current_y += (self._target_y - self._current_y) * 0.28
                needs_repaint = True

        needs_repaint = self._prune_timed_items(now) or needs_repaint

        if needs_repaint:
            self.update()

    def _prune_timed_items(self, now):
        before_counts = (
            len(self._click_pulses),
            len(self._laser_points),
            len(self._highlights)
        )

        self._click_pulses = [
            pulse for pulse in self._click_pulses
            if (now - pulse["created_at"]) <= 0.8
        ]
        self._laser_points = [
            point for point in self._laser_points
            if (now - point["created_at"]) <= 0.9
        ]
        self._highlights = [
            item for item in self._highlights
            if (now - item["created_at"]) <= 3.5
        ]

        after_counts = (
            len(self._click_pulses),
            len(self._laser_points),
            len(self._highlights)
        )

        return before_counts != after_counts or bool(self._click_pulses or self._laser_points or self._highlights)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self._draw_highlights(painter)
        self._draw_saved_drawings(painter)
        self._draw_saved_markers(painter)
        self._draw_saved_hotspots(painter)
        self._draw_laser_points(painter)
        self._draw_click_pulses(painter)

        if self._pointer_visible:
            self._draw_pointer(painter)

        if self._mismatch_visible:
            self._draw_mismatch_badge(painter)

        painter.end()

    def _draw_click_pulses(self, painter):
        for pulse in self._click_pulses:
            age = max(0.0, time.monotonic() - pulse["created_at"])
            progress = min(1.0, age / 0.8)
            radius = 12 + (38 * progress)
            opacity = int(255 * (1.0 - progress))

            color = QColor(249, 115, 22, max(0, opacity))
            fill_color = QColor(249, 115, 22, max(0, int(opacity * 0.18)))

            painter.setPen(QPen(color, 3))
            painter.setBrush(fill_color)
            painter.drawEllipse(QPointF(pulse["x"], pulse["y"]), radius, radius)

    def _draw_laser_points(self, painter):
        now = time.monotonic()
        for point in self._laser_points:
            age = max(0.0, now - point["created_at"])
            progress = min(1.0, age / 0.9)
            opacity = int(255 * (1.0 - progress))
            radius = 7 + (5 * (1 - progress))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(239, 68, 68, max(0, opacity)))
            painter.drawEllipse(QPointF(point["x"], point["y"]), radius, radius)

            painter.setBrush(QColor(239, 68, 68, max(0, int(opacity * 0.18))))
            painter.drawEllipse(QPointF(point["x"], point["y"]), radius + 6, radius + 6)

    def _draw_saved_drawings(self, painter):
        for drawing in self._drawings:
            if drawing["kind"] == "draw_circle":
                painter.setPen(QPen(QColor(249, 115, 22), 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(drawing["rect"])
                continue

            if drawing["kind"] == "draw_underline":
                painter.setPen(QPen(QColor(37, 99, 235), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            else:
                painter.setPen(QPen(QColor(249, 115, 22), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(drawing["start"], drawing["end"])

            if drawing["kind"] == "draw_arrow":
                self._draw_arrow_head(painter, drawing["start"], drawing["end"])

    def _draw_arrow_head(self, painter, start, end):
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        arrow_length = 18
        left = QPointF(
            end.x() - arrow_length * math.cos(angle - math.pi / 6),
            end.y() - arrow_length * math.sin(angle - math.pi / 6)
        )
        right = QPointF(
            end.x() - arrow_length * math.cos(angle + math.pi / 6),
            end.y() - arrow_length * math.sin(angle + math.pi / 6)
        )
        polygon = QPolygonF([end, left, right])
        painter.setBrush(QColor(249, 115, 22))
        painter.drawPolygon(polygon)

    def _draw_saved_markers(self, painter):
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)

        for marker in self._freeze_markers:
            rect = QRectF(marker["x"] - 42, marker["y"] - 16, 84, 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 23, 42, 238))
            painter.drawRoundedRect(rect, 16, 16)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Look here")

    def _draw_saved_hotspots(self, painter):
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)

        for hotspot in self._hotspots:
            center = QPointF(hotspot["x"], hotspot["y"])
            painter.setPen(QPen(QColor(255, 255, 255), 3))
            painter.setBrush(QColor(37, 99, 235))
            painter.drawEllipse(center, 18, 18)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                QRectF(hotspot["x"] - 18, hotspot["y"] - 18, 36, 36),
                Qt.AlignmentFlag.AlignCenter,
                str(hotspot["stepNumber"])
            )

    def _draw_highlights(self, painter):
        now = time.monotonic()
        for item in self._highlights:
            age = max(0.0, now - item["created_at"])
            progress = min(1.0, age / 3.5)
            opacity = int(255 * (1.0 - progress))
            rect = item["rect"]

            painter.setPen(QPen(QColor(250, 204, 21, max(0, opacity)), 3))
            painter.setBrush(QColor(250, 204, 21, max(0, int(opacity * 0.14))))
            painter.drawRoundedRect(rect, 8, 8)

    def _draw_pointer(self, painter):
        x = self._current_x
        y = self._current_y

        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x, y + 26)
        path.lineTo(x + 8, y + 20)
        path.lineTo(x + 12, y + 32)
        path.lineTo(x + 18, y + 29)
        path.lineTo(x + 13, y + 17)
        path.lineTo(x + 24, y + 17)
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(37, 99, 235, 245))
        painter.drawPath(path)

        label_text = self._pointer_label or "Teacher"
        label_font = QFont("Segoe UI", 10)
        label_font.setBold(True)
        painter.setFont(label_font)

        metrics = painter.fontMetrics()
        label_width = metrics.horizontalAdvance(label_text) + 18
        label_height = 28
        label_x = x + 28
        label_y = y + 16

        painter.setBrush(QColor(15, 23, 42, 236))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(label_x, label_y, label_width, label_height), 8, 8)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QRectF(label_x, label_y, label_width, label_height),
            Qt.AlignmentFlag.AlignCenter,
            label_text
        )

    def _draw_mismatch_badge(self, painter):
        text = self._mismatch_message
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        badge_width = min(max(280, metrics.horizontalAdvance(text) + 28), 520)
        badge_height = 42
        badge_x = self.width() - badge_width - 18
        badge_y = 18

        painter.setPen(QPen(QColor(217, 119, 6, 90), 1))
        painter.setBrush(QColor(255, 247, 237, 244))
        painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_width, badge_height), 10, 10)

        painter.setPen(QColor(146, 64, 14))
        painter.drawText(
            QRectF(badge_x + 14, badge_y + 8, badge_width - 28, badge_height - 16),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text
        )

    def _render_laser_point(self, event):
        point = self._ratios_to_local_point(event.get("xRatio"), event.get("yRatio"))
        if point is None:
            return

        self._laser_points.append({
            "x": point[0],
            "y": point[1],
            "created_at": time.monotonic()
        })
        self.update()

    def _render_drawing(self, event):
        if event.get("kind") == "draw_circle":
            rect = self._ratios_to_rect(
                event.get("x1Ratio"),
                event.get("y1Ratio"),
                event.get("x2Ratio"),
                event.get("y2Ratio")
            )
            if rect is None:
                return
            self._drawings.append({
                "kind": "draw_circle",
                "rect": rect
            })
            self.update()
            return

        start = self._ratios_to_local_point(event.get("x1Ratio"), event.get("y1Ratio"))
        end = self._ratios_to_local_point(event.get("x2Ratio"), event.get("y2Ratio"))
        if start is None or end is None:
            return

        y1 = end[1] if event.get("kind") == "draw_underline" else start[1]
        self._drawings.append({
            "kind": event.get("kind"),
            "start": QPointF(start[0], y1),
            "end": QPointF(end[0], end[1])
        })
        self.update()

    def _render_highlight(self, event):
        point = self._ratios_to_local_point(event.get("xRatio"), event.get("yRatio"))
        if point is None:
            return

        self._highlights.append({
            "rect": QRectF(point[0] - 90, point[1] - 55, 180, 110),
            "created_at": time.monotonic()
        })
        self.update()

    def _render_freeze_marker(self, event):
        point = self._ratios_to_local_point(event.get("xRatio"), event.get("yRatio"))
        if point is None:
            return

        self._freeze_markers.append({
            "x": point[0],
            "y": point[1]
        })
        self.update()

    def _render_hotspot(self, event):
        point = self._ratios_to_local_point(event.get("xRatio"), event.get("yRatio"))
        if point is None:
            return

        self._hotspots.append({
            "x": point[0],
            "y": point[1],
            "stepNumber": int(event.get("stepNumber") or 1)
        })
        self.update()

    def _ratios_to_local_point(self, x_ratio, y_ratio):
        point = denormalize_point(x_ratio, y_ratio, self._desktop_rect)
        if point is None:
            return None
        return (
            point["x"] - self._desktop_rect["left"],
            point["y"] - self._desktop_rect["top"]
        )

    def _ratios_to_rect(self, x1_ratio, y1_ratio, x2_ratio, y2_ratio):
        first = self._ratios_to_local_point(x1_ratio, y1_ratio)
        second = self._ratios_to_local_point(x2_ratio, y2_ratio)
        if first is None or second is None:
            return None

        left = min(first[0], second[0])
        top = min(first[1], second[1])
        width = abs(second[0] - first[0])
        height = abs(second[1] - first[1])
        if width < 8 or height < 8:
            return None
        return QRectF(left, top, width, height)
