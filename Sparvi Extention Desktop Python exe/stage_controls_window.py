from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget
)

from desktop_utils import get_virtual_desktop_rect


AVATAR_COLORS = [
    "#2563eb",
    "#db2777",
    "#16a34a",
    "#9333ea",
    "#ea580c",
    "#0891b2",
    "#4f46e5",
    "#be123c",
    "#111827"
]

TOOLS = [
    ("pointer", "Ptr", "Pointer"),
    ("laser", "Laser", "Laser"),
    ("trophy", "Trophy", "Send Trophy"),
    ("arrow", "Arrow", "Arrow"),
    ("circle", "Circle", "Circle"),
    ("underline", "Line", "Underline"),
    ("highlight", "HL", "Highlight"),
    ("freeze", "Pin", "Freeze"),
    ("hotspot", "Step", "Hotspot"),
    ("text_cast", "Text", "Text Cast"),
    ("clear", "Clear", "Clear")
]


class StageTargetWindow(QWidget):
    target_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("StageTargetWindow")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("StageControlFrame")
        outer_frame = QHBoxLayout(frame)
        outer_frame.setContentsMargins(8, 8, 8, 8)
        outer_frame.setSpacing(8)
        self.button_layout = QHBoxLayout()
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(8)
        outer_frame.addLayout(self.button_layout)
        outer.addWidget(frame)

        self.setStyleSheet(
            """
            QFrame#StageControlFrame {
                background: rgba(255, 255, 255, 250);
                border: 1px solid #d7deea;
                border-radius: 10px;
            }
            QPushButton[role="target"] {
                min-width: 38px;
                max-width: 38px;
                min-height: 38px;
                max-height: 38px;
                border-radius: 19px;
                border: 2px solid #ffffff;
                color: #ffffff;
                font-weight: 800;
            }
            QPushButton[role="target"][selected="true"] {
                border-color: #facc15;
            }
            """
        )

    def sync_to_stage(self, stage_rect):
        self.adjustSize()
        desktop_rect = get_virtual_desktop_rect()
        width = max(self.width(), self.sizeHint().width())
        height = max(self.height(), self.sizeHint().height())

        min_x = desktop_rect["left"] + 12
        max_x = desktop_rect["left"] + desktop_rect["width"] - width - 12
        preferred_x = int(stage_rect["left"])
        x = min(max(preferred_x, min_x), max(min_x, max_x))

        preferred_y = int(stage_rect["top"] - height - 10)
        if preferred_y < desktop_rect["top"] + 8:
            preferred_y = int(stage_rect["top"] + 10)

        min_y = desktop_rect["top"] + 8
        max_y = desktop_rect["top"] + desktop_rect["height"] - height - 8
        y = min(max(preferred_y, min_y), max(min_y, max_y))
        self.move(x, y)

    def update_students(self, students, selected_target):
        while self.button_layout.count():
            item = self.button_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.button_layout.addWidget(self._create_target_button("all", "All", 8, selected_target == "all"))

        for index, student in enumerate(students):
            label = self._avatar_label(student.get("displayName") or f"Student {index + 1}")
            selected = student.get("clientId") == selected_target
            self.button_layout.addWidget(
                self._create_target_button(
                    student.get("clientId", "all"),
                    label,
                    int(student.get("avatarIndex", index)) % len(AVATAR_COLORS),
                    selected
                )
            )

        self.adjustSize()

    def _create_target_button(self, client_id, text, avatar_index, selected):
        button = QPushButton(text)
        button.setProperty("role", "target")
        button.setProperty("selected", "true" if selected else "false")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("All students" if client_id == "all" else f"Target {text}")
        button.setStyleSheet(
            f"background: {AVATAR_COLORS[avatar_index % len(AVATAR_COLORS)]};"
        )
        button.clicked.connect(lambda _checked=False, cid=client_id: self.target_selected.emit(cid))
        return button

    def _avatar_label(self, display_name):
        parts = [part for part in str(display_name or "").strip().split(" ") if part]
        if not parts:
            return "S"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return f"{parts[0][0]}{parts[1][0]}".upper()


class StageToolWindow(QWidget):
    tool_selected = Signal(str)
    clear_requested = Signal()
    reward_requested = Signal()

    def __init__(self):
        super().__init__()
        self._buttons = {}
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("StageToolFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)

        title = QLabel("Tools")
        title.setObjectName("StageToolTitle")
        layout.addWidget(title)

        for tool_key, text, tip in TOOLS:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("role", "tool")
            button.setProperty("selected", "false")
            if tool_key == "clear":
                button.clicked.connect(self.clear_requested.emit)
            elif tool_key == "trophy":
                button.clicked.connect(self.reward_requested.emit)
            else:
                button.clicked.connect(lambda _checked=False, key=tool_key: self.tool_selected.emit(key))
            self._buttons[tool_key] = button
            layout.addWidget(button)

        outer.addWidget(frame)

        self.setStyleSheet(
            """
            QFrame#StageToolFrame {
                background: rgba(255, 255, 255, 250);
                border: 1px solid #d7deea;
                border-radius: 10px;
            }
            QLabel#StageToolTitle {
                color: #475467;
                font-size: 11px;
                font-weight: 800;
            }
            QPushButton[role="tool"] {
                min-width: 52px;
                min-height: 30px;
                border-radius: 6px;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #172033;
                font-weight: 700;
            }
            QPushButton[role="tool"][selected="true"] {
                background: #2563eb;
                border-color: #2563eb;
                color: #ffffff;
            }
            """
        )

    def sync_to_stage(self, stage_rect):
        self.adjustSize()
        desktop_rect = get_virtual_desktop_rect()
        width = max(self.width(), self.sizeHint().width())
        height = max(self.height(), self.sizeHint().height())

        preferred_x = int(stage_rect["left"] + stage_rect["width"] + 12)
        max_x = desktop_rect["left"] + desktop_rect["width"] - width - 12
        if preferred_x > max_x:
            preferred_x = int(stage_rect["left"] - width - 12)

        min_x = desktop_rect["left"] + 12
        x = min(max(preferred_x, min_x), max(min_x, max_x))

        preferred_y = int(stage_rect["top"] + max(0, (stage_rect["height"] - height) / 2))
        min_y = desktop_rect["top"] + 12
        max_y = desktop_rect["top"] + desktop_rect["height"] - height - 12
        y = min(max(preferred_y, min_y), max(min_y, max_y))
        self.move(x, y)

    def set_selected_tool(self, tool_key):
        for key, button in self._buttons.items():
            button.setProperty("selected", "true" if key == tool_key else "false")
            button.style().unpolish(button)
            button.style().polish(button)


class StageTextCastWindow(QWidget):
    text_submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("StageTextCastWindow")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("StageTextCastFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Text Cast")
        title.setObjectName("StageTextCastTitle")
        layout.addWidget(title)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Send text to student")
        self.text_input.setMaxLength(2000)
        self.text_input.returnPressed.connect(self._emit_text)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("TextCastSendButton")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._emit_text)

        input_row.addWidget(self.text_input, 1)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        outer.addWidget(frame)

        self.setStyleSheet(
            """
            QFrame#StageTextCastFrame {
                background: rgba(255, 255, 255, 250);
                border: 1px solid #d7deea;
                border-radius: 10px;
            }
            QLabel#StageTextCastTitle {
                color: #0f172a;
                font-size: 12px;
                font-weight: 800;
            }
            QLineEdit {
                min-width: 230px;
                min-height: 34px;
                padding: 0 10px;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                background: #ffffff;
                color: #172033;
            }
            QLineEdit:focus {
                border-color: #2563eb;
            }
            QPushButton#TextCastSendButton {
                min-width: 58px;
                min-height: 34px;
                border-radius: 7px;
                border: 1px solid #1d4ed8;
                background: #2563eb;
                color: #ffffff;
                font-weight: 800;
            }
            QPushButton#TextCastSendButton:hover {
                background: #1d4ed8;
            }
            """
        )

    def sync_to_stage(self, stage_rect):
        self.adjustSize()
        desktop_rect = get_virtual_desktop_rect()
        width = max(self.width(), self.sizeHint().width())
        height = max(self.height(), self.sizeHint().height())

        preferred_x = int(stage_rect["left"] + stage_rect["width"] + 84)
        max_x = desktop_rect["left"] + desktop_rect["width"] - width - 12
        if preferred_x > max_x:
            preferred_x = int(stage_rect["left"] - width - 12)

        min_x = desktop_rect["left"] + 12
        x = min(max(preferred_x, min_x), max(min_x, max_x))

        preferred_y = int(stage_rect["top"] + 8)
        min_y = desktop_rect["top"] + 12
        max_y = desktop_rect["top"] + desktop_rect["height"] - height - 12
        y = min(max(preferred_y, min_y), max(min_y, max_y))
        self.move(x, y)

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.text_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _emit_text(self):
        text = self.text_input.text().strip()
        if not text:
            return

        self.text_submitted.emit(text)
        self.text_input.clear()
