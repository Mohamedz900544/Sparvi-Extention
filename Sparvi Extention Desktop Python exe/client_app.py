import ctypes
import os
import sys
import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget
)

from desktop_utils import (
    get_active_surface_name,
    get_virtual_desktop_rect,
    normalize_point_in_rect,
    rect_contains_point,
    shorten_label
)
from mouse_capture import GlobalMouseCapture
from network_client import NetworkClient
from overlay_window import OverlayWindow
from stage_controls_window import StageTargetWindow, StageTextCastWindow, StageToolWindow
from stage_window import InstructorStageWindow


SEND_INTERVAL_SECONDS = 1 / 45
TOOL_SEND_INTERVAL_SECONDS = 1 / 30
HARDCODED_SERVER_URL = "wss://sparvishare.alwaysdata.net"
DRAW_TOOL_MODES = {"arrow", "circle", "underline"}
TOOL_KIND_MAP = {
    "arrow": "draw_arrow",
    "circle": "draw_circle",
    "underline": "draw_underline"
}
TROPHY_TEXT_CAST_PREFIX = "SPARVI_REWARD_TROPHY|"
HEART_TEXT_CAST_PREFIX = "SPARVI_REWARD_HEART|"
ROLE_VARIANT_ENV = "SPARVI_DESKTOP_ROLE"


def detect_role_variant():
    explicit_role = str(os.getenv(ROLE_VARIANT_ENV) or "").strip().lower()
    if explicit_role in {"student", "teacher", "instructor"}:
        return "instructor" if explicit_role == "teacher" else explicit_role

    executable_name = os.path.basename(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).lower()
    if "student" in executable_name:
        return "student"
    if "teacher" in executable_name or "instructor" in executable_name:
        return "instructor"
    return ""


APP_ROLE_VARIANT = detect_role_variant()


def resource_path(filename):
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, filename)


def load_logo_pixmap():
    logo_path = resource_path("logo.png")
    if not os.path.exists(logo_path):
        return QPixmap()
    return QPixmap(logo_path)


def load_app_icon():
    icon_path = resource_path("icon.png")
    if not os.path.exists(icon_path):
        return QIcon()
    return QIcon(icon_path)


class DesktopPointerWindow(QWidget):
    def __init__(self):
        super().__init__()
        settings_name = {
            "student": "DesktopPointerStudent",
            "instructor": "DesktopPointerTeacher"
        }.get(APP_ROLE_VARIANT, "DesktopPointer")
        self.settings = QSettings("Sparvi", settings_name)
        self.role_variant = APP_ROLE_VARIANT
        self.teacher_local_preview_enabled = self.role_variant != "instructor"
        self.network = NetworkClient()
        self.overlay = OverlayWindow()
        self.stage_window = InstructorStageWindow(self.settings)
        self.target_window = StageTargetWindow()
        self.tool_window = StageToolWindow()
        self.text_cast_window = StageTextCastWindow()
        self.mouse_capture = GlobalMouseCapture(
            on_move=self.handle_global_mouse_move,
            on_click=self.handle_global_mouse_click
        )

        self.connection_status = "disconnected"
        self.client_id = ""
        self.pointer_enabled = False
        self.pointer_target_client_id = "all"
        self.current_tool_mode = "pointer"
        self.hotspot_step_number = 1
        self.server_features = {
            "toolEvent": False,
            "instantReward": False,
            "trophyReward": False,
            "heartReward": False
        }
        self.local_error = ""
        self.current_context = "Desktop"
        self.last_context_sent = ""
        self.last_move_sent_at = 0.0
        self.last_tool_sent_at = 0.0
        self.desktop_rect = get_virtual_desktop_rect()
        self.stage_rect = self.stage_window.stage_rect()
        self.draw_interaction = None
        self.peer_state = {
            "instructorConnected": False,
            "instructorContext": "",
            "pointerEnabled": False,
            "pointerTargetClientId": "all",
            "studentCount": 0,
            "students": []
        }

        self.build_ui()
        self.apply_styles()
        self.bind_network_signals()
        self.bind_stage_signals()
        self.load_settings()
        self.refresh_current_context()
        self.mouse_capture.start()

        self.context_timer = QTimer(self)
        self.context_timer.timeout.connect(self.refresh_current_context)
        self.context_timer.start(800)

        self.update_ui()

    def build_ui(self):
        self.setWindowTitle(self.window_title())
        self.setMinimumSize(560, 460)
        app_icon = load_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.setSpacing(12)

        logo_label = QLabel()
        logo_label.setObjectName("LogoLabel")
        logo_pixmap = load_logo_pixmap()
        if not logo_pixmap.isNull():
            logo_label.setPixmap(
                logo_pixmap.scaledToHeight(42, Qt.TransformationMode.SmoothTransformation)
            )

        title_label = QLabel(self.window_title())
        title_font = QFont("Segoe UI", 17)
        title_font.setBold(True)
        title_label.setFont(title_font)

        subtitle_label = QLabel(self.subtitle_text())
        subtitle_label.setWordWrap(True)
        subtitle_label.setObjectName("SubtitleLabel")

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)
        header_text_layout.addWidget(title_label)
        header_text_layout.addWidget(subtitle_label)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        if not logo_pixmap.isNull():
            header_layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(header_text_layout, 1)
        outer_layout.addLayout(header_layout)

        self.status_card = self.create_card()
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(10)

        status_header = QHBoxLayout()
        status_header.setSpacing(8)
        status_title = QLabel("Live Status")
        status_title.setObjectName("SectionTitle")
        self.status_badge = QLabel("Offline")
        self.status_badge.setObjectName("StatusBadge")
        status_header.addWidget(status_title)
        status_header.addStretch(1)
        status_header.addWidget(self.status_badge)

        status_form = QFormLayout()
        status_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        status_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        status_form.setHorizontalSpacing(16)
        status_form.setVerticalSpacing(10)

        self.connection_value = QLabel("Disconnected")
        self.role_value = QLabel("Student")
        self.room_value = QLabel("Not joined")

        status_form.addRow("Connection", self.connection_value)
        status_form.addRow("Role", self.role_value)
        status_form.addRow("Room", self.room_value)

        status_layout.addLayout(status_header)
        status_layout.addLayout(status_form)
        outer_layout.addWidget(self.status_card)

        self.session_card = self.create_card()
        session_layout = QVBoxLayout(self.session_card)
        session_layout.setContentsMargins(14, 14, 14, 14)
        session_layout.setSpacing(10)

        session_title = QLabel("Session Setup")
        session_title.setObjectName("SectionTitle")

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(16)
        form_layout.setVerticalSpacing(10)

        self.session_input = QLineEdit()
        self.session_input.setPlaceholderText("class-demo-1")

        self.role_input = QComboBox()
        self.role_input.addItem("Student", "student")
        self.role_input.addItem("Instructor", "instructor")
        if self.role_variant:
            self.role_input.setEnabled(False)

        self.password_label = QLabel("Instructor Password")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your access password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form_layout.addRow("Session ID", self.session_input)
        form_layout.addRow("Role", self.role_input)
        form_layout.addRow(self.password_label, self.password_input)

        connection_buttons = QHBoxLayout()
        connection_buttons.setSpacing(8)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("PrimaryButton")
        self.disconnect_button = QPushButton("Disconnect")
        connection_buttons.addWidget(self.connect_button)
        connection_buttons.addWidget(self.disconnect_button)

        session_layout.addWidget(session_title)
        session_layout.addLayout(form_layout)
        session_layout.addLayout(connection_buttons)
        outer_layout.addWidget(self.session_card)

        self.instructor_card = self.create_card()
        instructor_layout = QVBoxLayout(self.instructor_card)
        instructor_layout.setContentsMargins(14, 14, 14, 14)
        instructor_layout.setSpacing(10)

        instructor_title = QLabel("Instructor Controls")
        instructor_title.setObjectName("SectionTitle")

        action_buttons = QHBoxLayout()
        action_buttons.setSpacing(8)
        self.pointer_button = QPushButton("Start Live Pointer")
        self.pointer_button.setObjectName("PrimaryButton")
        self.pulse_button = QPushButton("Send Pulse")
        action_buttons.addWidget(self.pointer_button)
        action_buttons.addWidget(self.pulse_button)

        instructor_layout.addWidget(instructor_title)
        instructor_layout.addLayout(action_buttons)
        outer_layout.addWidget(self.instructor_card)

        self.helper_card = self.create_card()
        helper_layout = QVBoxLayout(self.helper_card)
        helper_layout.setContentsMargins(14, 12, 14, 12)
        helper_layout.setSpacing(6)
        helper_title = QLabel("What happens next")
        helper_title.setObjectName("SectionTitle")
        self.helper_label = QLabel("Join the same room on the instructor and student devices.")
        self.helper_label.setWordWrap(True)
        helper_layout.addWidget(helper_title)
        helper_layout.addWidget(self.helper_label)
        outer_layout.addWidget(self.helper_card)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.hide()
        outer_layout.addWidget(self.error_label)

        outer_layout.addStretch(1)

        self.connect_button.clicked.connect(self.handle_connect_clicked)
        self.disconnect_button.clicked.connect(self.handle_disconnect_clicked)
        self.pointer_button.clicked.connect(self.handle_pointer_toggled)
        self.pulse_button.clicked.connect(self.handle_send_pulse_clicked)
        self.role_input.currentIndexChanged.connect(self.handle_role_changed)
        self.session_input.editingFinished.connect(self.save_settings)

    def window_title(self):
        if self.role_variant == "student":
            return "Sparvi Desktop Student"
        if self.role_variant == "instructor":
            return "Sparvi Desktop Teacher"
        return "Sparvi Desktop Pointer"

    def subtitle_text(self):
        if self.role_variant == "student":
            return "Student desktop receiver for live teacher pointer, pulses, and teaching marks."
        if self.role_variant == "instructor":
            return "Teacher desktop controller for live pointer, targeting, and teaching tools."
        return "Live instructor pointer over desktop apps, IDEs, docs, and tools."

    def create_card(self):
        card = QFrame()
        card.setObjectName("Card")
        return card

    def apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                background: #edf2f7;
                color: #172033;
                font-family: "Segoe UI";
                font-size: 13px;
            }
            QFrame#Card {
                background: #ffffff;
                border: 1px solid #d7deea;
                border-radius: 8px;
            }
            QLabel#SubtitleLabel {
                color: #55627a;
                font-size: 12px;
            }
            QLabel#LogoLabel {
                min-width: 54px;
                min-height: 54px;
                max-width: 150px;
                background: transparent;
            }
            QLabel#SectionTitle {
                color: #0f172a;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#StatusBadge {
                padding: 4px 10px;
                border-radius: 999px;
                border: 1px solid #cbd5e1;
                background: #f8fafc;
                color: #475569;
                font-weight: 700;
            }
            QLabel#StatusBadge[state="connected"] {
                background: #ecfdf5;
                border-color: rgba(13, 148, 136, 0.3);
                color: #0f766e;
            }
            QLabel#StatusBadge[state="connecting"], QLabel#StatusBadge[state="reconnecting"] {
                background: #eff6ff;
                border-color: rgba(37, 99, 235, 0.28);
                color: #1d4ed8;
            }
            QLabel#ErrorLabel {
                background: #fff1f2;
                border: 1px solid #fecaca;
                border-radius: 8px;
                padding: 10px 12px;
                color: #991b1b;
                font-weight: 600;
            }
            QLineEdit, QComboBox {
                min-height: 38px;
                padding: 0 10px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: #ffffff;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #2563eb;
            }
            QPushButton {
                min-height: 40px;
                padding: 0 14px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: #ffffff;
                font-weight: 700;
            }
            QPushButton:hover:!disabled {
                background: #f8fafc;
            }
            QPushButton#PrimaryButton {
                background: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
            QPushButton#PrimaryButton:hover:!disabled {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background: #eef1f6;
                color: #98a2b3;
                border-color: #dbe2ea;
            }
            """
        )

    def bind_network_signals(self):
        self.network.connection_changed.connect(self.handle_connection_changed)
        self.network.error_received.connect(self.handle_error_received)
        self.network.joined_received.connect(self.handle_joined_received)
        self.network.peer_status_received.connect(self.handle_peer_status_received)
        self.network.cursor_move_received.connect(self.handle_cursor_move_received)
        self.network.click_pulse_received.connect(self.handle_click_pulse_received)
        self.network.tool_event_received.connect(self.handle_tool_event_received)
        self.network.context_mismatch_received.connect(self.handle_context_mismatch_received)
        self.network.pointer_state_received.connect(self.handle_pointer_state_received)
        self.network.pointer_target_received.connect(self.handle_pointer_target_received)

    def bind_stage_signals(self):
        self.stage_window.geometry_changed.connect(self.handle_stage_geometry_changed)
        self.target_window.target_selected.connect(self.handle_target_selected)
        self.tool_window.tool_selected.connect(self.handle_tool_selected)
        self.tool_window.clear_requested.connect(self.handle_clear_tools)
        self.tool_window.reward_requested.connect(self.handle_send_reward_clicked)
        self.text_cast_window.text_submitted.connect(self.handle_text_cast_submitted)

    def load_settings(self):
        self.session_input.setText(self.settings.value("sessionId", ""))
        saved_role = self.role_variant or self.settings.value("role", "student")
        index = 1 if saved_role == "instructor" else 0
        self.role_input.setCurrentIndex(index)

    def save_settings(self):
        self.settings.setValue("sessionId", self.session_input.text().strip())
        self.settings.setValue("role", self.current_role())

    def current_role(self):
        if self.role_variant:
            return self.role_variant
        return self.role_input.currentData() or "student"

    def handle_connect_clicked(self):
        room_id = self.session_input.text().strip()
        server_url = HARDCODED_SERVER_URL
        role = self.current_role()
        instructor_password = self.password_input.text().strip() if role == "instructor" else ""

        if not room_id:
            self.set_error("Enter a session ID first.")
            return

        if role == "instructor" and not instructor_password:
            self.set_error("Enter the instructor password before connecting.")
            return

        self.save_settings()
        self.clear_error()
        self.client_id = ""
        self.pointer_enabled = False
        self.pointer_target_client_id = "all"
        self.current_tool_mode = "pointer"
        self.hotspot_step_number = 1
        self.overlay.clear_teaching_artifacts()
        self.desktop_rect = get_virtual_desktop_rect()
        self.stage_rect = self.stage_window.stage_rect()
        self.network.connect_to_server(
            server_url=server_url,
            room_id=room_id,
            role=role,
            instructor_password=instructor_password,
            current_context=self.current_context,
            pointer_enabled=self.pointer_enabled,
            target_client_id=self.pointer_target_client_id
        )
        self.update_ui()

    def handle_disconnect_clicked(self):
        self.pointer_enabled = False
        self.draw_interaction = None
        self.network.disconnect()
        self.overlay.clear_pointer()
        self.overlay.clear_teaching_artifacts()
        self.overlay.set_teacher_pointer_enabled(False)
        self.overlay.set_context_mismatch(False)
        self.stage_window.set_stage_active(False)
        self.stage_window.set_stage_visible(False)
        self.target_window.hide()
        self.tool_window.hide()
        self.text_cast_window.hide()
        self.update_mouse_capture_state()
        self.update_ui()

    def handle_pointer_toggled(self):
        if self.current_role() != "instructor" or not self.network.connected:
            return

        self.pointer_enabled = not self.pointer_enabled
        self.network.send_pointer_state(
            self.pointer_enabled,
            self.current_context,
            self.pointer_target_client_id
        )
        self.overlay.set_teacher_pointer_enabled(
            self.pointer_enabled if self.should_preview_teacher_output() else False
        )
        if not self.pointer_enabled:
            self.draw_interaction = None
        self.update_mouse_capture_state()
        self.update_ui()

    def handle_send_pulse_clicked(self):
        if self.current_role() != "instructor" or not self.network.connected:
            return

        cursor_pos = QCursor.pos()
        normalized = self.get_stage_normalized_point(cursor_pos.x(), cursor_pos.y())
        if not normalized:
            center = self.stage_window.native_content_center_point()
            normalized = self.get_stage_normalized_point(center["x"], center["y"])

        if not normalized:
            self.set_error("Move the mouse inside the Live Pointer Area first.")
            return

        self.network.send_click_pulse(
            normalized["xRatio"],
            normalized["yRatio"],
            self.current_context,
            self.pointer_target_client_id
        )
        self.show_local_teacher_pulse(normalized["xRatio"], normalized["yRatio"])

    def handle_send_reward_clicked(self, reward_key):
        if self.current_role() != "instructor" or not self.network.connected:
            return

        reward_key = str(reward_key or "").strip()
        is_hearts = reward_key == "hearts"
        event = {
            "kind": "heart_reward" if is_hearts else "trophy_reward",
            "message": "Nice work!" if is_hearts else "Great answer!"
        }

        if not self.supports_instant_reward(is_hearts):
            if not self.pointer_enabled:
                self.set_error("Start Live Pointer before sending rewards on this backend.")
                return
            event = {
                "kind": "text_cast",
                "text": (HEART_TEXT_CAST_PREFIX if is_hearts else TROPHY_TEXT_CAST_PREFIX)
                + ("Nice work!" if is_hearts else "Great answer!")
            }

        normalized = self.current_stage_point_or_none()
        if normalized:
            event["xRatio"] = normalized["xRatio"]
            event["yRatio"] = normalized["yRatio"]

        if self.send_teaching_tool_event(event):
            self.render_local_teacher_tool_event(event)

    def handle_role_changed(self):
        if self.current_role() != "instructor":
            self.password_input.clear()
        self.pointer_enabled = False
        self.pointer_target_client_id = "all"
        self.current_tool_mode = "pointer"
        self.draw_interaction = None
        self.server_features = {
            "toolEvent": False,
            "instantReward": False,
            "trophyReward": False,
            "heartReward": False
        }
        self.overlay.clear_teaching_artifacts()
        self.stage_window.set_stage_visible(False)
        self.stage_window.set_stage_active(False)
        self.target_window.hide()
        self.tool_window.hide()
        self.text_cast_window.hide()
        self.update_mouse_capture_state()
        self.save_settings()
        self.update_ui()

    def handle_connection_changed(self, status):
        self.connection_status = status
        if status != "connected":
            self.pointer_enabled = False
            self.draw_interaction = None
            self.server_features = {
                "toolEvent": False,
                "instantReward": False,
                "trophyReward": False,
                "heartReward": False
            }
            self.overlay.clear_pointer()
            self.overlay.clear_teaching_artifacts()
            self.stage_window.set_stage_active(False)
            self.stage_window.set_stage_visible(False)
            self.target_window.hide()
            self.tool_window.hide()
            self.text_cast_window.hide()
            if self.current_role() == "student":
                self.overlay.set_teacher_pointer_enabled(False)
                self.overlay.set_context_mismatch(False)
        self.update_mouse_capture_state()
        self.update_ui()

    def handle_error_received(self, message):
        self.set_error(message)

    def handle_joined_received(self, payload):
        self.client_id = payload.get("clientId", "")
        features = payload.get("features") or {}
        self.server_features = {
            "toolEvent": bool(features.get("toolEvent")),
            "instantReward": bool(features.get("instantReward")),
            "trophyReward": bool(features.get("trophyReward")),
            "heartReward": bool(features.get("heartReward"))
        }
        self.clear_error()
        self.update_ui()

    def handle_peer_status_received(self, payload):
        self.peer_state = {
            "instructorConnected": bool(payload.get("instructorConnected")),
            "instructorContext": payload.get("instructorContext", ""),
            "pointerEnabled": bool(payload.get("pointerEnabled")),
            "pointerTargetClientId": normalize_target(payload.get("pointerTargetClientId")),
            "studentCount": int(payload.get("studentCount", 0)),
            "students": payload.get("students", [])
        }

        if self.current_role() == "instructor":
            self.pointer_target_client_id = self.peer_state["pointerTargetClientId"]
            if not self._target_exists(self.pointer_target_client_id):
                self.pointer_target_client_id = "all"

        if self.current_role() == "student" and not self.peer_state["instructorConnected"]:
            self.overlay.clear_pointer()
            self.overlay.clear_teaching_artifacts()
            self.overlay.set_teacher_pointer_enabled(False)
            self.overlay.set_context_mismatch(False)

        self.update_stage_controls()
        self.update_ui()

    def handle_cursor_move_received(self, payload):
        if self.current_role() != "student":
            return

        if not self.is_this_student_targeted(payload.get("targetClientId")):
            self.overlay.clear_pointer()
            return

        self.overlay.set_remote_pointer(
            payload.get("xRatio"),
            payload.get("yRatio"),
            label="Teacher"
        )

    def handle_click_pulse_received(self, payload):
        if self.current_role() != "student":
            return

        if not self.is_this_student_targeted(payload.get("targetClientId")):
            return

        self.overlay.show_click_pulse(
            payload.get("xRatio"),
            payload.get("yRatio")
        )

    def handle_tool_event_received(self, payload):
        if self.current_role() != "student":
            return

        if not self.is_this_student_targeted(payload.get("targetClientId")):
            return

        self.overlay.render_teaching_tool_event(payload)

    def handle_context_mismatch_received(self, payload):
        if self.current_role() != "student":
            return

        self.overlay.set_context_mismatch(
            bool(payload.get("mismatch")),
            payload.get("instructorContext", "")
        )
        self.update_ui()

    def handle_pointer_state_received(self, payload):
        enabled = bool(payload.get("enabled"))
        self.peer_state["pointerEnabled"] = enabled
        self.peer_state["pointerTargetClientId"] = normalize_target(payload.get("targetClientId"))

        if self.current_role() == "student":
            self.overlay.set_teacher_pointer_enabled(enabled)
            if not enabled:
                self.overlay.clear_pointer()

        self.update_stage_controls()
        self.update_ui()

    def handle_pointer_target_received(self, payload):
        target_client_id = normalize_target(payload.get("targetClientId"))
        self.peer_state["pointerTargetClientId"] = target_client_id

        if self.current_role() == "instructor":
            self.pointer_target_client_id = target_client_id
            self.update_stage_controls()
        elif not self.is_this_student_targeted(target_client_id):
            self.overlay.clear_pointer()

        self.update_ui()

    def refresh_current_context(self):
        next_context = shorten_label(get_active_surface_name(), 80)
        if next_context.lower().startswith("sparvi "):
            if self.current_context and not self.current_context.lower().startswith("sparvi "):
                next_context = self.current_context
            else:
                next_context = "Desktop"

        self.current_context = next_context
        self.desktop_rect = get_virtual_desktop_rect()
        self.stage_rect = self.stage_window.stage_rect()

        if self.network.connected and self.current_context != self.last_context_sent:
            self.network.send_context_update(self.current_context)
            self.last_context_sent = self.current_context

        self.update_ui()

    def handle_stage_geometry_changed(self, rect):
        self.stage_rect = rect
        self.update_stage_controls()

    def handle_target_selected(self, target_client_id):
        if self.current_role() != "instructor":
            return

        normalized_target = normalize_target(target_client_id)
        if normalized_target != "all" and not self._target_exists(normalized_target):
            normalized_target = "all"

        self.pointer_target_client_id = normalized_target
        if self.network.connected:
            self.network.send_pointer_target(self.pointer_target_client_id)
        self.update_stage_controls()
        self.update_ui()

    def handle_tool_selected(self, tool_key):
        self.current_tool_mode = tool_key
        self.update_stage_controls()
        if tool_key == "text_cast":
            self.text_cast_window.show_and_focus()
        self.update_ui()

    def handle_clear_tools(self):
        self.hotspot_step_number = 1
        self.overlay.clear_teaching_artifacts()
        self.send_teaching_tool_event({"kind": "clear_tools"})

    def handle_text_cast_submitted(self, text):
        text_value = str(text or "").strip()
        if not text_value:
            return

        self.send_teaching_tool_event({
            "kind": "text_cast",
            "text": text_value
        })

    def handle_global_mouse_move(self, x, y):
        if not self.should_send_global_pointer():
            self.stage_window.set_stage_active(False)
            return

        if self.stage_window.is_interacting():
            self.stage_window.set_stage_active(False)
            return

        stage_point = self.get_stage_normalized_point(x, y)
        self.stage_window.set_stage_active(stage_point is not None)

        if self.draw_interaction:
            if stage_point:
                self.draw_interaction["endPoint"] = stage_point
                dx = abs(x - self.draw_interaction["startX"])
                dy = abs(y - self.draw_interaction["startY"])
                self.draw_interaction["moved"] = dx > 3 or dy > 3
            return

        if not stage_point:
            return

        now = time.monotonic()
        if (now - self.last_move_sent_at) >= SEND_INTERVAL_SECONDS:
            self.last_move_sent_at = now
            self.network.send_cursor_move(
                stage_point["xRatio"],
                stage_point["yRatio"],
                self.current_context,
                self.pointer_target_client_id
            )

        if self.current_tool_mode == "laser" and (now - self.last_tool_sent_at) >= TOOL_SEND_INTERVAL_SECONDS:
            self.last_tool_sent_at = now
            event = {
                "kind": "laser_point",
                "xRatio": stage_point["xRatio"],
                "yRatio": stage_point["yRatio"]
            }
            if self.send_teaching_tool_event(event):
                self.render_local_teacher_tool_event(event)

    def handle_global_mouse_click(self, x, y, button, pressed):
        if not self.should_send_global_pointer():
            return

        if self.stage_window.is_interacting():
            return

        if not is_left_button(button):
            return

        point = self.get_stage_normalized_point(x, y)

        if self.current_tool_mode in DRAW_TOOL_MODES:
            self._handle_draw_tool_click(x, y, point, pressed)
            return

        if not pressed or not point:
            return

        if self.current_tool_mode == "text_cast":
            return

        if self.current_tool_mode == "highlight":
            self._send_point_tool_event("highlight_element", point)
            return

        if self.current_tool_mode == "freeze":
            self._send_point_tool_event("freeze_marker", point)
            return

        if self.current_tool_mode == "hotspot":
            event = {
                "kind": "guided_hotspot",
                "xRatio": point["xRatio"],
                "yRatio": point["yRatio"],
                "stepNumber": self.hotspot_step_number
            }
            if self.send_teaching_tool_event(event):
                self.render_local_teacher_tool_event(event)
                self.hotspot_step_number += 1
            return

        self.network.send_click_pulse(
            point["xRatio"],
            point["yRatio"],
            self.current_context,
            self.pointer_target_client_id
        )
        self.show_local_teacher_pulse(point["xRatio"], point["yRatio"])

    def _handle_draw_tool_click(self, x, y, point, pressed):
        if pressed:
            if not point:
                return
            self.draw_interaction = {
                "toolMode": self.current_tool_mode,
                "startPoint": point,
                "endPoint": point,
                "startX": x,
                "startY": y,
                "moved": False
            }
            return

        if not self.draw_interaction:
            return

        interaction = self.draw_interaction
        self.draw_interaction = None

        if point:
            interaction["endPoint"] = point

        if not interaction["moved"]:
            return

        event = {
            "kind": TOOL_KIND_MAP[interaction["toolMode"]],
            "x1Ratio": interaction["startPoint"]["xRatio"],
            "y1Ratio": interaction["startPoint"]["yRatio"],
            "x2Ratio": interaction["endPoint"]["xRatio"],
            "y2Ratio": interaction["endPoint"]["yRatio"]
        }
        if self.send_teaching_tool_event(event):
            self.render_local_teacher_tool_event(event)

    def _send_point_tool_event(self, kind, point):
        event = {
            "kind": kind,
            "xRatio": point["xRatio"],
            "yRatio": point["yRatio"]
        }
        if self.send_teaching_tool_event(event):
            self.render_local_teacher_tool_event(event)

    def send_teaching_tool_event(self, event):
        if not self.server_features.get("toolEvent"):
            self.set_error("Teaching tools need the updated desktop backend. Restart server.py, then reconnect both devices.")
            return False

        payload = {
            **event,
            "currentContext": self.current_context,
            "targetClientId": self.pointer_target_client_id
        }
        return self.network.send_teaching_tool_event(payload)

    def supports_instant_reward(self, is_hearts=False):
        if self.server_features.get("instantReward"):
            return True
        if is_hearts:
            return bool(self.server_features.get("heartReward"))
        return bool(self.server_features.get("trophyReward"))

    def should_send_global_pointer(self):
        return (
            self.current_role() == "instructor"
            and self.network.connected
            and self.pointer_enabled
        )

    def should_preview_teacher_output(self):
        return self.current_role() == "instructor" and self.teacher_local_preview_enabled

    def show_local_teacher_pulse(self, x_ratio, y_ratio):
        if self.should_preview_teacher_output():
            self.overlay.show_click_pulse(x_ratio, y_ratio)

    def render_local_teacher_tool_event(self, event):
        if self.should_preview_teacher_output():
            self.overlay.render_teaching_tool_event(event)

    def should_show_stage(self):
        return (
            self.current_role() == "instructor"
            and self.network.connected
            and self.pointer_enabled
        )

    def get_stage_normalized_point(self, x, y):
        self.stage_rect = self.stage_window.native_content_rect()
        if not rect_contains_point(x, y, self.stage_rect):
            return None
        return normalize_point_in_rect(x, y, self.stage_rect)

    def current_stage_point_or_none(self):
        if not self.stage_window.isVisible():
            return None

        cursor_pos = QCursor.pos()
        normalized = self.get_stage_normalized_point(cursor_pos.x(), cursor_pos.y())
        if normalized:
            return normalized

        center = self.stage_window.native_content_center_point()
        return self.get_stage_normalized_point(center["x"], center["y"])

    def update_mouse_capture_state(self):
        self.mouse_capture.set_enabled(self.should_send_global_pointer())

    def update_stage_controls(self):
        visible = self.should_show_stage()
        self.stage_window.set_stage_visible(visible)
        if not visible:
            self.target_window.hide()
            self.tool_window.hide()
            self.text_cast_window.hide()
            return

        students = self.peer_state.get("students", [])
        self.target_window.update_students(students, self.pointer_target_client_id)
        self.target_window.sync_to_stage(self.stage_window.stage_rect())
        self.target_window.show()

        self.tool_window.set_selected_tool(self.current_tool_mode)
        self.tool_window.sync_to_stage(self.stage_window.stage_rect())
        self.tool_window.show()

        if self.current_tool_mode == "text_cast":
            self.text_cast_window.sync_to_stage(self.stage_window.stage_rect())
            self.text_cast_window.show()
        else:
            self.text_cast_window.hide()

    def is_this_student_targeted(self, target_client_id):
        normalized = normalize_target(target_client_id)
        return normalized == "all" or normalized == self.client_id

    def _target_exists(self, target_client_id):
        if target_client_id == "all":
            return True
        return any(
            student.get("clientId") == target_client_id
            for student in self.peer_state.get("students", [])
        )

    def set_error(self, message):
        self.local_error = str(message or "").strip()
        self.update_ui()

    def clear_error(self):
        self.local_error = ""
        self.update_ui()

    def format_helper_text(self):
        if self.connection_status != "connected":
            if self.current_role() == "instructor":
                return "Enter the room ID and your instructor password, then connect. The server will verify the password before opening the teaching session."
            return "Run the server, open the app on both devices, join the same room, then connect."

        if self.current_role() == "instructor":
            if not self.pointer_enabled:
                return "Connected. Start Live Pointer to show the floating frame, avatars, and tool bar on the desktop."
            if not self.teacher_local_preview_enabled:
                return "Live Pointer is on. Pointer movement and teaching marks are sent to the selected student view only."
            return "Live Pointer is on. Only movement and clicks inside the floating frame are sent, and you can target one student or all."

        if not self.peer_state.get("instructorConnected"):
            return "Connected. Keep this desktop open and wait for the instructor to join."
        if self.peer_state.get("pointerEnabled"):
            return "Teacher is live. You will see the pointer, pulses, and teaching marks on top of your desktop."
        return "Teacher is connected. Waiting for Live Pointer to start."

    def update_ui(self):
        role = self.current_role()
        room_text = self.session_input.text().strip() or "Not joined"

        self.role_value.setText(role.capitalize())
        self.connection_value.setText(self.connection_status.capitalize())
        self.room_value.setText(room_text)
        self.helper_label.setText(self.format_helper_text())

        badge_text = {
            "connected": "Connected",
            "connecting": "Connecting",
            "reconnecting": "Reconnecting"
        }.get(self.connection_status, "Offline")
        self.status_badge.setText(badge_text)
        self.status_badge.setProperty("state", self.connection_status)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        connected = self.connection_status == "connected"
        busy = self.connection_status in ("connecting", "reconnecting")
        is_instructor = role == "instructor"

        self.connect_button.setDisabled(connected or busy)
        self.disconnect_button.setDisabled(not connected and not busy)
        self.session_input.setDisabled(connected or busy)
        self.role_input.setDisabled(bool(self.role_variant) or connected or busy)
        self.password_label.setVisible(is_instructor)
        self.password_input.setVisible(is_instructor)
        self.password_input.setDisabled(connected or busy)

        self.instructor_card.setVisible(is_instructor)
        self.pointer_button.setDisabled(not connected or not is_instructor)
        self.pulse_button.setDisabled(not connected or not is_instructor)
        self.pointer_button.setText("Stop Live Pointer" if self.pointer_enabled else "Start Live Pointer")

        self.update_stage_controls()

        if self.local_error:
            self.error_label.setText(self.local_error)
            self.error_label.show()
        else:
            self.error_label.hide()

    def closeEvent(self, event):
        self.save_settings()
        self.mouse_capture.stop()
        self.network.disconnect()
        self.stage_window.close()
        self.target_window.close()
        self.tool_window.close()
        self.text_cast_window.close()
        self.overlay.close()
        event.accept()


def normalize_target(value):
    text = str(value or "").strip()
    return text if text else "all"


def is_left_button(button):
    return getattr(button, "name", "") == "left" or str(button).lower().endswith("left")


def enable_windows_dpi_awareness():
    if sys.platform != "win32":
        return

    user32 = getattr(ctypes.windll, "user32", None)
    shcore = getattr(ctypes.windll, "shcore", None)

    try:
        if user32 and hasattr(user32, "SetProcessDpiAwarenessContext"):
            # PER_MONITOR_AWARE_V2
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
    except Exception:
        pass

    try:
        if shcore and hasattr(shcore, "SetProcessDpiAwareness"):
            # PROCESS_PER_MONITOR_DPI_AWARE
            shcore.SetProcessDpiAwareness(2)
            return
    except Exception:
        pass

    try:
        if user32 and hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    enable_windows_dpi_awareness()
    app = QApplication(sys.argv)
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = DesktopPointerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
