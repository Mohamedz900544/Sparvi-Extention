import io
import math
import struct
import sys
import threading
import time
import wave

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from desktop_utils import denormalize_point, get_virtual_desktop_rect, shorten_label


POINTER_EASING = 0.55
TROPHY_TEXT_CAST_PREFIX = "SPARVI_REWARD_TROPHY|"
HEART_TEXT_CAST_PREFIX = "SPARVI_REWARD_HEART|"
TROPHY_DURATION_SECONDS = 2.8
TROPHY_CONFETTI_COLORS = [
    QColor(37, 99, 235),
    QColor(239, 68, 68),
    QColor(16, 185, 129),
    QColor(245, 158, 11),
    QColor(217, 70, 239),
    QColor(14, 165, 233)
]


class TextCastPopupWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._desktop_rect = get_virtual_desktop_rect()
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Sparvi Text Cast")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("TextCastPopupFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Text Cast")
        title.setObjectName("TextCastPopupTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("TextCastCloseButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(8)

        self.text_field = QLineEdit()
        self.text_field.setReadOnly(True)
        self.text_field.setMinimumWidth(320)
        self.text_field.setMaximumWidth(520)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("TextCastCopyButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_text)

        body.addWidget(self.text_field, 1)
        body.addWidget(self.copy_button)
        layout.addLayout(body)

        outer.addWidget(frame)

        self.setStyleSheet(
            """
            QFrame#TextCastPopupFrame {
                background: rgba(255, 255, 255, 248);
                border: 1px solid #cbd5e1;
                border-radius: 10px;
            }
            QLabel#TextCastPopupTitle {
                color: #0f172a;
                font-size: 13px;
                font-weight: 800;
            }
            QLineEdit {
                min-height: 34px;
                padding: 0 10px;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                background: #f8fafc;
                color: #111827;
                font-size: 13px;
            }
            QPushButton {
                min-height: 34px;
                padding: 0 12px;
                border-radius: 7px;
                font-weight: 800;
            }
            QPushButton#TextCastCopyButton {
                border: 1px solid #1d4ed8;
                background: #2563eb;
                color: #ffffff;
            }
            QPushButton#TextCastCopyButton:hover {
                background: #1d4ed8;
            }
            QPushButton#TextCastCloseButton {
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
            }
            QPushButton#TextCastCloseButton:hover {
                background: #f8fafc;
            }
            """
        )

    def show_text(self, text):
        self.text_field.setText(str(text or ""))
        self.copy_button.setText("Copy")
        self._position_near_top()
        self.show()
        self.raise_()

    def _copy_text(self):
        text = self.text_field.text()
        if not text:
            return

        QGuiApplication.clipboard().setText(text)
        self.copy_button.setText("Copied")
        QTimer.singleShot(1200, lambda: self.copy_button.setText("Copy"))

    def _position_near_top(self):
        self._desktop_rect = get_virtual_desktop_rect()
        self.adjustSize()

        width = max(self.width(), self.sizeHint().width())
        height = max(self.height(), self.sizeHint().height())
        left = self._desktop_rect["left"]
        top = self._desktop_rect["top"]
        desktop_width = self._desktop_rect["width"]
        desktop_height = self._desktop_rect["height"]

        x = left + max(12, int((desktop_width - width) / 2))
        y = top + 24
        max_x = left + desktop_width - width - 12
        max_y = top + desktop_height - height - 12
        self.move(min(max(x, left + 12), max(left + 12, max_x)), min(max(y, top + 12), max(top + 12, max_y)))


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
        self._trophy_rewards = []
        self._mismatch_visible = False
        self._mismatch_message = "Teacher is on a different app or window"
        self._text_popup = TextCastPopupWindow()

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
            if self._text_popup.isVisible():
                self._text_popup._position_near_top()
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
        elif kind == "trophy_reward":
            self._render_reward(event, "trophy")
        elif kind == "heart_reward":
            self._render_reward(event, "heart")
        elif kind == "text_cast":
            self._render_text_cast(event)
        elif kind == "clear_tools":
            self.clear_teaching_artifacts()

    def clear_teaching_artifacts(self):
        self._laser_points = []
        self._drawings = []
        self._freeze_markers = []
        self._hotspots = []
        self._highlights = []
        self._trophy_rewards = []
        self._text_popup.hide()
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
                self._current_x += (self._target_x - self._current_x) * POINTER_EASING
                self._current_y += (self._target_y - self._current_y) * POINTER_EASING
                needs_repaint = True

        needs_repaint = self._prune_timed_items(now) or needs_repaint

        if needs_repaint:
            self.update()

    def _prune_timed_items(self, now):
        before_counts = (
            len(self._click_pulses),
            len(self._laser_points),
            len(self._highlights),
            len(self._trophy_rewards)
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
        self._trophy_rewards = [
            item for item in self._trophy_rewards
            if (now - item["created_at"]) <= TROPHY_DURATION_SECONDS
        ]

        after_counts = (
            len(self._click_pulses),
            len(self._laser_points),
            len(self._highlights),
            len(self._trophy_rewards)
        )

        return before_counts != after_counts or bool(
            self._click_pulses
            or self._laser_points
            or self._highlights
            or self._trophy_rewards
        )

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
        self._draw_trophy_rewards(painter)

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

    def _draw_trophy_rewards(self, painter):
        now = time.monotonic()
        for reward in self._trophy_rewards:
            age = max(0.0, now - reward["created_at"])
            progress = min(1.0, age / TROPHY_DURATION_SECONDS)
            intro = min(1.0, age / 0.42)
            outro = min(1.0, max(0.0, (TROPHY_DURATION_SECONDS - age) / 0.55))
            opacity = int(255 * min(intro, outro))
            scale = 0.72 + (0.3 * ease_out_back(intro)) + (0.04 * math.sin(age * 14))
            lift = 22 * progress
            center_x = reward["x"]
            center_y = reward["y"] - lift

            self._draw_trophy_confetti(painter, reward, progress, opacity)

            painter.save()
            painter.translate(center_x, center_y)
            painter.scale(scale, scale)
            painter.setOpacity(max(0.0, min(1.0, opacity / 255.0)))
            if reward.get("kind") == "heart":
                self._draw_heart_shape(painter)
            else:
                self._draw_trophy_shape(painter)
            painter.restore()

            message = reward.get("message") or ("Nice work!" if reward.get("kind") == "heart" else "Great answer!")
            font = QFont("Segoe UI", 18)
            font.setBold(True)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            label_width = min(max(190, metrics.horizontalAdvance(message) + 36), 420)
            label_rect = QRectF(
                center_x - (label_width / 2),
                center_y + (76 * scale),
                label_width,
                42
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 23, 42, max(0, int(opacity * 0.88))))
            painter.drawRoundedRect(label_rect, 18, 18)
            painter.setPen(QColor(255, 255, 255, max(0, opacity)))
            painter.drawText(label_rect.adjusted(14, 0, -14, 0), Qt.AlignmentFlag.AlignCenter, message)

    def _draw_heart_shape(self, painter):
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor(244, 63, 94, 62))
        painter.drawEllipse(QPointF(0, 4), 86, 78)

        path = QPainterPath()
        path.moveTo(0, 58)
        path.cubicTo(-68, 12, -70, -38, -28, -42)
        path.cubicTo(-12, -44, -4, -34, 0, -24)
        path.cubicTo(4, -34, 12, -44, 28, -42)
        path.cubicTo(70, -38, 68, 12, 0, 58)
        path.closeSubpath()
        painter.setBrush(QColor(244, 63, 94))
        painter.drawPath(path)

        painter.setBrush(QColor(251, 113, 133, 180))
        painter.drawEllipse(QPointF(-22, -22), 10, 13)
        painter.drawEllipse(QPointF(20, -23), 10, 13)

        painter.setBrush(QColor(136, 19, 55, 90))
        painter.drawRoundedRect(QRectF(-38, 56, 76, 12), 6, 6)

    def _draw_trophy_shape(self, painter):
        painter.setPen(Qt.PenStyle.NoPen)

        glow = QColor(250, 204, 21, 70)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 4), 82, 82)

        shadow = QColor(120, 53, 15, 90)
        painter.setBrush(shadow)
        painter.drawRoundedRect(QRectF(-44, 55, 88, 14), 7, 7)

        cup_path = QPainterPath()
        cup_path.moveTo(-42, -42)
        cup_path.cubicTo(-36, 10, -24, 36, 0, 36)
        cup_path.cubicTo(24, 36, 36, 10, 42, -42)
        cup_path.closeSubpath()
        painter.setBrush(QColor(250, 204, 21))
        painter.drawPath(cup_path)

        painter.setBrush(QColor(245, 158, 11))
        painter.drawRoundedRect(QRectF(-12, 32, 24, 26), 8, 8)
        painter.drawRoundedRect(QRectF(-34, 54, 68, 16), 8, 8)

        painter.setPen(QPen(QColor(245, 158, 11), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(-68, -34, 42, 52), 76 * 16, 212 * 16)
        painter.drawArc(QRectF(26, -34, 42, 52), -108 * 16, 212 * 16)

        painter.setPen(QPen(QColor(255, 247, 237, 160), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(-20, -28), QPointF(-14, 14))

    def _draw_trophy_confetti(self, painter, reward, progress, opacity):
        burst = ease_out_cubic(min(1.0, progress / 0.62))
        drift = min(1.0, progress)
        for index in range(28):
            angle = (index * 2.3999632297) + reward["seed"]
            radius = 36 + (142 * burst) + (index % 5) * 8
            x = reward["x"] + math.cos(angle) * radius
            y = reward["y"] + math.sin(angle) * radius + (88 * drift * drift) - 40
            if reward.get("kind") == "heart":
                color = QColor(244, 63, 94) if index % 2 else QColor(251, 113, 133)
            else:
                color = TROPHY_CONFETTI_COLORS[index % len(TROPHY_CONFETTI_COLORS)]
            color = QColor(color.red(), color.green(), color.blue(), max(0, int(opacity * (1.0 - progress * 0.35))))

            painter.save()
            painter.translate(x, y)
            painter.rotate((angle * 57.2958) + (progress * 280))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            if reward.get("kind") == "heart" and index % 3 != 0:
                self._draw_small_heart(painter)
            elif index % 3 == 0:
                painter.drawEllipse(QPointF(0, 0), 4, 4)
            else:
                painter.drawRoundedRect(QRectF(-4, -2, 8, 4), 2, 2)
            painter.restore()

    def _draw_small_heart(self, painter):
        path = QPainterPath()
        path.moveTo(0, 5)
        path.cubicTo(-9, -1, -8, -8, -3, -8)
        path.cubicTo(-1, -8, 0, -6, 0, -4)
        path.cubicTo(0, -6, 1, -8, 3, -8)
        path.cubicTo(8, -8, 9, -1, 0, 5)
        path.closeSubpath()
        painter.drawPath(path)

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

    def _render_text_cast(self, event):
        text = str((event or {}).get("text") or "").strip()
        if not text:
            return

        if text.startswith(TROPHY_TEXT_CAST_PREFIX):
            self._render_reward({
                "message": text[len(TROPHY_TEXT_CAST_PREFIX):] or "Great answer!"
            }, "trophy")
            return

        if text.startswith(HEART_TEXT_CAST_PREFIX):
            self._render_reward({
                "message": text[len(HEART_TEXT_CAST_PREFIX):] or "Nice work!"
            }, "heart")
            return

        self._text_popup.show_text(text[:2000])

    def _render_reward(self, event, reward_kind):
        point = self._ratios_to_local_point(event.get("xRatio"), event.get("yRatio"))
        if point is None:
            point = (self.width() / 2, self.height() / 2)

        default_message = "Nice work!" if reward_kind == "heart" else "Great answer!"
        message = str((event or {}).get("message") or default_message).strip() or default_message
        self._trophy_rewards.append({
            "kind": reward_kind,
            "x": point[0],
            "y": point[1],
            "message": shorten_label(message, 42),
            "seed": (time.monotonic() * 3.1) % math.tau,
            "created_at": time.monotonic()
        })
        self._play_reward_sound(reward_kind)
        self.update()

    def _play_reward_sound(self, reward_kind):
        if sys.platform == "win32":
            threading.Thread(target=play_windows_reward_sound, args=(reward_kind,), daemon=True).start()
            return

        QGuiApplication.beep()

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

    def closeEvent(self, event):
        self._text_popup.close()
        super().closeEvent(event)


def ease_out_cubic(value):
    value = max(0.0, min(1.0, value))
    return 1 - pow(1 - value, 3)


def ease_out_back(value):
    value = max(0.0, min(1.0, value))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(value - 1, 3) + c1 * pow(value - 1, 2)


def play_windows_reward_sound(reward_kind):
    try:
        import winsound

        winsound.PlaySound(build_reward_wav_bytes(reward_kind), winsound.SND_MEMORY)
    except Exception:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            QGuiApplication.beep()


def build_reward_wav_bytes(reward_kind):
    sample_rate = 44100
    notes = (
        (659.25, 0.08),
        (783.99, 0.08),
        (987.77, 0.1),
        (1318.51, 0.16),
    )
    if reward_kind == "heart":
        notes = (
            (523.25, 0.08),
            (659.25, 0.08),
            (783.99, 0.12),
            (1046.5, 0.16),
        )

    frames = bytearray()
    for frequency, duration in notes:
        total_samples = int(sample_rate * duration)
        for index in range(total_samples):
            phase = index / sample_rate
            envelope = min(1.0, index / max(1, total_samples * 0.12))
            envelope *= min(1.0, (total_samples - index) / max(1, total_samples * 0.18))
            value = math.sin(2 * math.pi * frequency * phase)
            value += 0.28 * math.sin(2 * math.pi * frequency * 2 * phase)
            sample = int(max(-1.0, min(1.0, value * 0.34 * envelope)) * 32767)
            frames.extend(struct.pack("<h", sample))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()
