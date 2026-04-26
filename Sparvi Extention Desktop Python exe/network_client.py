from collections import deque
import json
import socket
import threading
import time

import websocket
from PySide6.QtCore import QObject, QTimer, Signal


MAX_RECONNECT_ATTEMPTS = 6
BASE_RECONNECT_DELAY_SECONDS = 1
MAX_RECONNECT_DELAY_SECONDS = 15
MAX_CONTROL_QUEUE_SIZE = 120


class NetworkClient(QObject):
    connection_changed = Signal(str)
    error_received = Signal(str)
    joined_received = Signal(dict)
    peer_status_received = Signal(dict)
    cursor_move_received = Signal(dict)
    click_pulse_received = Signal(dict)
    tool_event_received = Signal(dict)
    context_mismatch_received = Signal(dict)
    pointer_state_received = Signal(dict)
    pointer_target_received = Signal(dict)

    def __init__(self):
        super().__init__()
        self._socket_app = None
        self._socket_thread = None
        self._reconnect_timer = None
        self._manual_disconnect = False
        self._send_lock = threading.Lock()
        self._send_condition = threading.Condition()
        self._send_queue = deque()
        self._latest_cursor_payload = None
        self._latest_laser_payload = None
        self._connected = False
        self._reconnect_attempt = 0
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            daemon=True
        )
        self._sender_thread.start()
        self._pending_cursor_message = None
        self._cursor_message_lock = threading.Lock()
        self._cursor_emit_timer = QTimer(self)
        self._cursor_emit_timer.timeout.connect(self._flush_pending_cursor_message)
        self._cursor_emit_timer.start(16)

        self._server_url = "ws://localhost:8790"
        self._room_id = ""
        self._role = "student"
        self._instructor_password = ""
        self._current_context = "Desktop"
        self._pointer_enabled = False
        self._pointer_target_client_id = "all"
        self._server_features = {
            "toolEvent": False
        }

    @property
    def connected(self):
        return self._connected

    def connect_to_server(self, server_url, room_id, role, current_context, pointer_enabled, target_client_id="all", instructor_password=""):
        self.disconnect(clear_room=False)

        self._server_url = str(server_url or "ws://localhost:8790").strip()
        self._room_id = str(room_id or "").strip()
        self._role = role if role in ("instructor", "student") else "student"
        self._instructor_password = str(instructor_password or "").strip() if self._role == "instructor" else ""
        self._current_context = str(current_context or "Desktop").strip() or "Desktop"
        self._pointer_enabled = bool(pointer_enabled)
        self._pointer_target_client_id = normalize_target(target_client_id)
        self._server_features = {
            "toolEvent": False
        }

        self._manual_disconnect = False
        self._reconnect_attempt = 0
        self._clear_pending_sends()
        self._clear_pending_cursor_message()
        self._open_socket(is_reconnect=False)

    def disconnect(self, clear_room=True):
        self._manual_disconnect = True
        self._clear_reconnect_timer()

        socket_app = self._socket_app
        self._socket_app = None

        if socket_app is not None:
            try:
                self._safe_send({"type": "leave"}, socket_app=socket_app)
            except Exception:
                pass

            try:
                socket_app.close()
            except Exception:
                pass

        self._connected = False
        self._clear_pending_sends()
        self._clear_pending_cursor_message()

        if clear_room:
            self._room_id = ""
            self._instructor_password = ""
        self._server_features = {
            "toolEvent": False
        }

        self.connection_changed.emit("disconnected")

    def send_cursor_move(self, x_ratio, y_ratio, current_context, target_client_id="all"):
        self._current_context = str(current_context or self._current_context).strip() or "Desktop"
        self._pointer_target_client_id = normalize_target(target_client_id)
        self._queue_latest_cursor({
            "type": "cursor_move",
            "xRatio": x_ratio,
            "yRatio": y_ratio,
            "currentContext": self._current_context,
            "targetClientId": self._pointer_target_client_id,
            "timestamp": int(time.time() * 1000)
        })

    def send_click_pulse(self, x_ratio, y_ratio, current_context, target_client_id="all"):
        self._current_context = str(current_context or self._current_context).strip() or "Desktop"
        self._pointer_target_client_id = normalize_target(target_client_id)
        self._safe_send({
            "type": "click_pulse",
            "xRatio": x_ratio,
            "yRatio": y_ratio,
            "currentContext": self._current_context,
            "targetClientId": self._pointer_target_client_id,
            "timestamp": int(time.time() * 1000)
        })

    def send_context_update(self, current_context):
        self._current_context = str(current_context or "Desktop").strip() or "Desktop"
        self._safe_send({
            "type": "context_update",
            "currentContext": self._current_context
        })

    def send_pointer_state(self, enabled, current_context, target_client_id="all"):
        self._pointer_enabled = bool(enabled)
        self._current_context = str(current_context or self._current_context).strip() or "Desktop"
        self._pointer_target_client_id = normalize_target(target_client_id)
        self._safe_send({
            "type": "pointer_state",
            "enabled": self._pointer_enabled,
            "currentContext": self._current_context,
            "targetClientId": self._pointer_target_client_id
        })

    def send_pointer_target(self, target_client_id):
        self._pointer_target_client_id = normalize_target(target_client_id)
        self._safe_send({
            "type": "pointer_target",
            "targetClientId": self._pointer_target_client_id
        })

    def send_teaching_tool_event(self, event):
        if not isinstance(event, dict):
            return False
        if not self.supports_tool_events:
            self.error_received.emit("Teaching tools need the updated desktop backend. Restart the Python server, then reconnect.")
            return False

        event_payload = {
            **event,
            "currentContext": str(event.get("currentContext") or self._current_context).strip() or "Desktop",
            "targetClientId": normalize_target(event.get("targetClientId") or self._pointer_target_client_id),
            "timestamp": int(time.time() * 1000)
        }
        payload = {
            "type": "tool_event",
            "event": event_payload
        }
        if event_payload.get("kind") == "laser_point":
            return self._queue_latest_laser(payload)
        return self._safe_send(payload)

    def _open_socket(self, is_reconnect):
        self._clear_reconnect_timer()

        if self._socket_app is not None or not self._room_id:
            return

        self.connection_changed.emit("reconnecting" if is_reconnect else "connecting")

        self._socket_app = websocket.WebSocketApp(
            self._server_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        self._socket_thread = threading.Thread(
            target=self._run_socket_forever,
            daemon=True
        )
        self._socket_thread.start()

    def _run_socket_forever(self):
        socket_app = self._socket_app
        if socket_app is None:
            return

        try:
            socket_app.run_forever(
                ping_interval=25,
                ping_timeout=10,
                skip_utf8_validation=True,
                sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),)
            )
        except Exception as error:
            self.error_received.emit(f"Socket failed: {error}")

    def _on_open(self, _socket):
        self._connected = True
        self._reconnect_attempt = 0
        self.connection_changed.emit("connected")
        self._safe_send({
            "type": "join",
            "roomId": self._room_id,
            "role": self._role,
            "instructorPassword": self._instructor_password if self._role == "instructor" else "",
            "currentContext": self._current_context,
            "pointerEnabled": self._pointer_enabled,
            "targetClientId": self._pointer_target_client_id
        })

    def _on_message(self, _socket, raw_message):
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            self.error_received.emit("Received malformed server message.")
            return

        message_type = message.get("type")
        if message_type == "joined":
            features = message.get("features") or {}
            self._server_features = {
                "toolEvent": bool(features.get("toolEvent"))
            }
            self.joined_received.emit(message)
            return

        if message_type == "peer_status":
            self.peer_status_received.emit(message)
            return

        if message_type == "cursor_move":
            self._queue_cursor_message(message)
            return

        if message_type == "click_pulse":
            self.click_pulse_received.emit(message)
            return

        if message_type == "tool_event":
            self.tool_event_received.emit(message.get("event", message))
            return

        if message_type == "context_mismatch":
            self.context_mismatch_received.emit(message)
            return

        if message_type == "pointer_state":
            self.pointer_state_received.emit(message)
            return

        if message_type == "pointer_target":
            self.pointer_target_received.emit(message)
            return

        if message_type == "error":
            error_message = message.get("message", "Server returned an error.")
            self.error_received.emit(error_message)
            if message.get("fatal"):
                self._stop_after_fatal_error()

    def _stop_after_fatal_error(self):
        self._manual_disconnect = True
        self._clear_reconnect_timer()

        socket_app = self._socket_app
        self._socket_app = None
        self._connected = False
        self._notify_sender()
        self._clear_pending_cursor_message()

        if socket_app is not None:
            try:
                socket_app.close()
            except Exception:
                pass

        self.connection_changed.emit("disconnected")

    def _on_error(self, _socket, error):
        if self._manual_disconnect:
            return
        self.error_received.emit(f"Connection error: {error}")

    def _on_close(self, _socket, _status_code, reason):
        self._socket_app = None
        was_manual = self._manual_disconnect
        self._connected = False

        if was_manual:
            self.connection_changed.emit("disconnected")
            return

        if reason:
            self.error_received.emit(str(reason))

        self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._manual_disconnect or not self._room_id:
            self.connection_changed.emit("disconnected")
            return

        if self._reconnect_attempt >= MAX_RECONNECT_ATTEMPTS:
            self.connection_changed.emit("disconnected")
            self.error_received.emit("Connection lost. Reopen the room when the server is available.")
            return

        delay = min(
            MAX_RECONNECT_DELAY_SECONDS,
            BASE_RECONNECT_DELAY_SECONDS * (2 ** self._reconnect_attempt)
        )
        self._reconnect_attempt += 1
        self.connection_changed.emit("reconnecting")
        self.error_received.emit(f"Connection lost. Reconnecting in {delay} seconds.")

        self._reconnect_timer = threading.Timer(delay, self._reconnect_now)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

    def _reconnect_now(self):
        self._open_socket(is_reconnect=True)

    def _clear_reconnect_timer(self):
        if self._reconnect_timer is None:
            return

        self._reconnect_timer.cancel()
        self._reconnect_timer = None

    def _safe_send(self, payload, socket_app=None):
        app = socket_app or self._socket_app
        if socket_app is not None:
            return self._send_now(payload, socket_app, emit_errors=False)

        if app is None or not self._connected:
            return False

        with self._send_condition:
            self._send_queue.append(payload)
            while len(self._send_queue) > MAX_CONTROL_QUEUE_SIZE:
                self._send_queue.popleft()
            self._send_condition.notify()
        return True

    def _queue_latest_cursor(self, payload):
        if self._socket_app is None or not self._connected:
            return False

        with self._send_condition:
            self._latest_cursor_payload = payload
            self._send_condition.notify()
        return True

    def _queue_latest_laser(self, payload):
        if self._socket_app is None or not self._connected:
            return False

        with self._send_condition:
            self._latest_laser_payload = payload
            self._send_condition.notify()
        return True

    def _sender_loop(self):
        while True:
            with self._send_condition:
                while not self._has_send_work_locked():
                    self._send_condition.wait(timeout=0.25)

                app = self._socket_app
                if self._send_queue:
                    payload = self._send_queue.popleft()
                elif self._latest_cursor_payload is not None:
                    payload = self._latest_cursor_payload
                    self._latest_cursor_payload = None
                else:
                    payload = self._latest_laser_payload
                    self._latest_laser_payload = None

            if app is None:
                continue

            self._send_now(payload, app)

    def _has_send_work_locked(self):
        return bool(
            self._connected
            and self._socket_app is not None
            and (
                self._send_queue
                or self._latest_cursor_payload is not None
                or self._latest_laser_payload is not None
            )
        )

    def _send_now(self, payload, socket_app, emit_errors=True):
        with self._send_lock:
            try:
                socket_app.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                return True
            except Exception as error:
                if emit_errors and self._connected and socket_app is self._socket_app:
                    self.error_received.emit(f"Failed to send message: {error}")
                return False

    def _clear_pending_sends(self):
        with self._send_condition:
            self._send_queue.clear()
            self._latest_cursor_payload = None
            self._latest_laser_payload = None
            self._send_condition.notify()

    def _notify_sender(self):
        with self._send_condition:
            self._send_condition.notify()

    def _queue_cursor_message(self, message):
        with self._cursor_message_lock:
            self._pending_cursor_message = message

    def _flush_pending_cursor_message(self):
        with self._cursor_message_lock:
            message = self._pending_cursor_message
            self._pending_cursor_message = None

        if message is not None:
            self.cursor_move_received.emit(message)

    def _clear_pending_cursor_message(self):
        with self._cursor_message_lock:
            self._pending_cursor_message = None

    @property
    def supports_tool_events(self):
        return bool(self._server_features.get("toolEvent"))


def normalize_target(value):
    text = str(value or "").strip()
    return text if text else "all"
