import asyncio
import json
import os
import signal
import ssl
import sys
import time
import uuid
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

import websockets


def first_env(*names):
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


TEST_INSTRUCTOR_AUTH_URL = "https://sparvilab.alwaysdata.net/api/sparvi/verify-password"
TEST_INSTRUCTOR_SHARED_SECRET = "fdvdvfd5v0fv0fv5df0vfd5v5fd0vd"


HOST = os.getenv("HOST") or os.getenv("IP") or "0.0.0.0"
PORT = int(os.getenv("PORT", "8790"))
INSTRUCTOR_AUTH_URL = first_env("INSTRUCTOR_AUTH_URL", "SPARVI_INSTRUCTOR_AUTH_URL") or TEST_INSTRUCTOR_AUTH_URL
INSTRUCTOR_AUTH_BEARER_TOKEN = first_env(
    "INSTRUCTOR_AUTH_BEARER_TOKEN",
    "SPARVI_SERVER_SHARED_SECRET",
    "SPARVI_SHARED_SECRET"
) or TEST_INSTRUCTOR_SHARED_SECRET
INSTRUCTOR_AUTH_TIMEOUT_SECONDS = max(1.0, float(os.getenv("INSTRUCTOR_AUTH_TIMEOUT_SECONDS", "8")))
INSTRUCTOR_AUTH_VERIFY_TLS = str(os.getenv("INSTRUCTOR_AUTH_VERIFY_TLS", "true")).strip().lower() not in {
    "0", "false", "no", "off"
}
MAX_ROOM_ID_LENGTH = 100
rooms = {}


@dataclass
class ClientState:
    websocket: object
    client_id: str
    room_id: str = ""
    role: str = "student"
    current_context: str = "Desktop"
    pointer_enabled: bool = False
    pointer_target_client_id: str = "all"
    avatar_index: int = 0
    joined_at: int = 0
    instructor_authorized: bool = False


async def handle_connection(websocket):
    state = ClientState(
        websocket=websocket,
        client_id=str(uuid.uuid4())
    )

    print(f"[connect] socket opened clientId={state.client_id}")

    try:
        async for raw_message in websocket:
            await handle_raw_message(state, raw_message)
    except websockets.ConnectionClosed:
        pass
    finally:
        await remove_client(state)


async def handle_raw_message(state, raw_message):
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        await send_json(state.websocket, {
            "type": "error",
            "message": "Malformed JSON message."
        })
        return

    message_type = message.get("type")

    if message_type == "join":
        await handle_join(state, message)
        return

    if message_type == "cursor_move":
        await handle_cursor_move(state, message)
        return

    if message_type == "click_pulse":
        await handle_click_pulse(state, message)
        return

    if message_type == "tool_event":
        await handle_tool_event(state, message)
        return

    if message_type == "context_update":
        await handle_context_update(state, message)
        return

    if message_type == "pointer_state":
        await handle_pointer_state(state, message)
        return

    if message_type == "pointer_target":
        await handle_pointer_target(state, message)
        return

    if message_type == "leave":
        await remove_client(state)
        return

    if message_type == "ping":
        await send_json(state.websocket, {"type": "pong"})
        return

    await send_json(state.websocket, {
        "type": "error",
        "message": f"Unsupported message type: {message_type or 'missing'}"
    })


async def handle_join(state, message):
    room_id = normalize_room_id(message.get("roomId"))
    role = normalize_role(message.get("role"))

    if not room_id:
        await send_error(state.websocket, "roomId is required.", fatal=True)
        return

    if not role:
        await send_error(state.websocket, "role must be instructor or student.", fatal=True)
        return

    room = rooms.get(room_id, {})
    existing_instructor = find_instructor(room_id)
    if role == "instructor" and existing_instructor and existing_instructor.client_id != state.client_id:
        await send_error(state.websocket, "This room already has an instructor connected.", fatal=True)
        return

    instructor_authorized = False
    if role == "instructor":
        instructor_authorized, error_message = await verify_instructor_access(
            room_id=room_id,
            client_id=state.client_id,
            password=message.get("instructorPassword")
        )
        if not instructor_authorized:
            await send_error(state.websocket, error_message, fatal=True)
            return

    if state.room_id:
        await remove_client(state, announce=False)

    room = rooms.setdefault(room_id, {})
    state.room_id = room_id
    state.role = role
    state.current_context = normalize_context(message.get("currentContext"))
    state.pointer_enabled = bool(message.get("pointerEnabled")) if role == "instructor" else False
    state.pointer_target_client_id = (
        resolve_pointer_target(room_id, normalize_target(message.get("targetClientId")))
        if role == "instructor"
        else "all"
    )
    state.instructor_authorized = instructor_authorized if role == "instructor" else False
    state.joined_at = current_millis()
    state.avatar_index = sum(1 for client in room.values() if client.role == "student") % 8
    room[state.client_id] = state

    print(
        f"[join] room={room_id} role={role} clientId={state.client_id} "
        f"context={state.current_context!r}"
    )

    await send_json(state.websocket, {
        "type": "joined",
        "clientId": state.client_id,
        "roomId": room_id,
        "features": {
            "desktopOverlay": True,
            "toolEvent": True,
            "instructorAuth": bool(INSTRUCTOR_AUTH_URL)
        }
    })
    await broadcast_peer_status(room_id)
    await broadcast_context_mismatch(room_id)


async def handle_cursor_move(state, message):
    if not is_authorized_instructor(state) or not state.pointer_enabled:
        return

    x_ratio = normalize_ratio(message.get("xRatio"))
    y_ratio = normalize_ratio(message.get("yRatio"))
    if x_ratio is None or y_ratio is None:
        return

    state.current_context = normalize_context(message.get("currentContext"), fallback=state.current_context)
    state.pointer_target_client_id = resolve_pointer_target(
        state.room_id,
        normalize_target(message.get("targetClientId") or state.pointer_target_client_id)
    )

    payload = {
        "type": "cursor_move",
        "xRatio": x_ratio,
        "yRatio": y_ratio,
        "currentContext": state.current_context,
        "targetClientId": state.pointer_target_client_id,
        "timestamp": int(message.get("timestamp") or current_millis())
    }
    await relay_to_target_students(state.room_id, state.pointer_target_client_id, payload)
    await broadcast_context_mismatch(state.room_id)


async def handle_click_pulse(state, message):
    if not is_authorized_instructor(state):
        return

    x_ratio = normalize_ratio(message.get("xRatio"))
    y_ratio = normalize_ratio(message.get("yRatio"))
    if x_ratio is None or y_ratio is None:
        return

    state.current_context = normalize_context(message.get("currentContext"), fallback=state.current_context)
    state.pointer_target_client_id = resolve_pointer_target(
        state.room_id,
        normalize_target(message.get("targetClientId") or state.pointer_target_client_id)
    )

    payload = {
        "type": "click_pulse",
        "xRatio": x_ratio,
        "yRatio": y_ratio,
        "currentContext": state.current_context,
        "targetClientId": state.pointer_target_client_id,
        "timestamp": int(message.get("timestamp") or current_millis())
    }
    await relay_to_target_students(state.room_id, state.pointer_target_client_id, payload)
    await broadcast_context_mismatch(state.room_id)


async def handle_tool_event(state, message):
    if not is_authorized_instructor(state) or not state.pointer_enabled:
        return

    event = normalize_tool_event(message.get("event"))
    if not event:
        await send_json(state.websocket, {
            "type": "error",
            "message": "Invalid teaching tool event."
        })
        return

    state.current_context = normalize_context(event.get("currentContext"), fallback=state.current_context)
    state.pointer_target_client_id = resolve_pointer_target(
        state.room_id,
        normalize_target(event.get("targetClientId") or state.pointer_target_client_id)
    )

    payload = {
        "type": "tool_event",
        "event": {
            **event,
            "currentContext": state.current_context,
            "targetClientId": state.pointer_target_client_id,
            "timestamp": int(event.get("timestamp") or current_millis())
        }
    }
    await relay_to_target_students(state.room_id, state.pointer_target_client_id, payload)


async def handle_context_update(state, message):
    if not state.room_id:
        return

    state.current_context = normalize_context(message.get("currentContext"), fallback=state.current_context)
    await broadcast_peer_status(state.room_id)
    await broadcast_context_mismatch(state.room_id)


async def handle_pointer_state(state, message):
    if not is_authorized_instructor(state):
        return

    state.pointer_enabled = bool(message.get("enabled"))
    state.current_context = normalize_context(message.get("currentContext"), fallback=state.current_context)
    state.pointer_target_client_id = resolve_pointer_target(
        state.room_id,
        normalize_target(message.get("targetClientId") or state.pointer_target_client_id)
    )

    payload = {
        "type": "pointer_state",
        "enabled": state.pointer_enabled,
        "currentContext": state.current_context,
        "targetClientId": state.pointer_target_client_id
    }
    await broadcast_room(state.room_id, payload)
    await broadcast_peer_status(state.room_id)
    await broadcast_context_mismatch(state.room_id)


async def handle_pointer_target(state, message):
    if not is_authorized_instructor(state):
        return

    state.pointer_target_client_id = resolve_pointer_target(
        state.room_id,
        normalize_target(message.get("targetClientId"))
    )

    payload = {
        "type": "pointer_target",
        "targetClientId": state.pointer_target_client_id,
        "timestamp": current_millis()
    }
    await broadcast_room(state.room_id, payload)
    await broadcast_peer_status(state.room_id)


async def broadcast_peer_status(room_id):
    room = rooms.get(room_id, {})
    if not room:
        return

    clients = list(room.values())
    instructor = find_instructor(room_id)
    students = [
        client for client in clients
        if client.role == "student"
    ]
    students.sort(key=lambda client: client.joined_at)

    payload = {
        "type": "peer_status",
        "instructorConnected": instructor is not None,
        "instructorContext": instructor.current_context if instructor else "",
        "pointerEnabled": instructor.pointer_enabled if instructor else False,
        "pointerTargetClientId": instructor.pointer_target_client_id if instructor else "all",
        "studentCount": len(students),
        "students": [
            {
                "clientId": student.client_id,
                "displayName": f"Student {index + 1}",
                "avatarIndex": index % 8,
                "currentContext": student.current_context
            }
            for index, student in enumerate(students)
        ]
    }

    await broadcast_room(room_id, payload)


async def broadcast_context_mismatch(room_id):
    room = rooms.get(room_id, {})
    if not room:
        return

    instructor = find_instructor(room_id)
    instructor_context = instructor.current_context if instructor else ""

    for student in [client for client in room.values() if client.role == "student"]:
        mismatch = False
        if instructor and instructor_context and student.current_context:
            mismatch = instructor_context.strip().casefold() != student.current_context.strip().casefold()

        await send_json(student.websocket, {
            "type": "context_mismatch",
            "mismatch": mismatch,
            "instructorContext": instructor_context
        })


async def relay_to_target_students(room_id, target_client_id, payload):
    room = rooms.get(room_id, {})
    if not room:
        return

    resolved_target = resolve_pointer_target(room_id, target_client_id)
    await asyncio.gather(*[
        send_json(client.websocket, {
            **payload,
            "targetClientId": resolved_target
        })
        for client in room.values()
        if client.role == "student" and (resolved_target == "all" or client.client_id == resolved_target)
    ], return_exceptions=True)


async def broadcast_room(room_id, payload):
    room = rooms.get(room_id, {})
    if not room:
        return

    await asyncio.gather(*[
        send_json(client.websocket, payload)
        for client in room.values()
    ], return_exceptions=True)


async def remove_client(state, announce=True):
    room_id = state.room_id
    if not room_id:
        return

    room = rooms.get(room_id)
    if not room:
        state.room_id = ""
        return

    room.pop(state.client_id, None)
    if not room:
        rooms.pop(room_id, None)

    print(f"[leave] room={room_id} role={state.role} clientId={state.client_id}")

    instructor = find_instructor(room_id)
    if state.role == "student" and instructor and instructor.pointer_target_client_id == state.client_id:
        instructor.pointer_target_client_id = "all"
        await broadcast_room(room_id, {
            "type": "pointer_target",
            "targetClientId": "all",
            "timestamp": current_millis()
        })

    if announce and state.role == "instructor":
        await broadcast_room(room_id, {
            "type": "pointer_state",
            "enabled": False,
            "currentContext": "",
            "targetClientId": "all"
        })

    state.room_id = ""
    state.pointer_enabled = False
    state.pointer_target_client_id = "all"
    state.joined_at = 0
    state.instructor_authorized = False

    if announce:
        await broadcast_peer_status(room_id)
        await broadcast_context_mismatch(room_id)


async def send_json(websocket, payload):
    try:
        await websocket.send(json.dumps(payload))
    except websockets.ConnectionClosed:
        return
    except Exception as error:
        print(f"[send-error] {error}")


async def send_error(websocket, message, fatal=False):
    await send_json(websocket, {
        "type": "error",
        "message": str(message or "Server returned an error."),
        "fatal": bool(fatal)
    })


def normalize_room_id(value):
    text = str(value or "").strip()
    return text[:MAX_ROOM_ID_LENGTH]


def normalize_role(value):
    if value in ("instructor", "student"):
        return value
    return ""


def normalize_target(value):
    text = str(value or "").strip()
    return text if text else "all"


def resolve_pointer_target(room_id, target_client_id):
    normalized = normalize_target(target_client_id)
    if normalized == "all":
        return "all"

    room = rooms.get(room_id, {})
    target = room.get(normalized)
    if target and target.role == "student":
        return normalized
    return "all"


def normalize_context(value, fallback="Desktop"):
    text = str(value or "").strip()
    return text[:160] if text else str(fallback or "Desktop")


def normalize_ratio(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def normalize_tool_event(value):
    if not isinstance(value, dict):
        return None

    kind = str(value.get("kind") or "").strip()
    if kind not in {
        "laser_point",
        "draw_arrow",
        "draw_circle",
        "draw_underline",
        "highlight_element",
        "freeze_marker",
        "guided_hotspot",
        "clear_tools"
    }:
        return None

    event = {
        "kind": kind,
        "id": str(value.get("id") or "")[:128],
        "currentContext": normalize_context(value.get("currentContext"), fallback="Desktop"),
        "targetClientId": normalize_target(value.get("targetClientId"))
    }

    if kind in {"laser_point", "highlight_element", "freeze_marker", "guided_hotspot"}:
        x_ratio = normalize_ratio(value.get("xRatio"))
        y_ratio = normalize_ratio(value.get("yRatio"))
        if x_ratio is None or y_ratio is None:
            return None
        event["xRatio"] = x_ratio
        event["yRatio"] = y_ratio

    if kind in {"draw_arrow", "draw_circle", "draw_underline"}:
        x1_ratio = normalize_ratio(value.get("x1Ratio"))
        y1_ratio = normalize_ratio(value.get("y1Ratio"))
        x2_ratio = normalize_ratio(value.get("x2Ratio"))
        y2_ratio = normalize_ratio(value.get("y2Ratio"))
        if None in {x1_ratio, y1_ratio, x2_ratio, y2_ratio}:
            return None
        event["x1Ratio"] = x1_ratio
        event["y1Ratio"] = y1_ratio
        event["x2Ratio"] = x2_ratio
        event["y2Ratio"] = y2_ratio

    if kind == "guided_hotspot":
        try:
            step_number = int(value.get("stepNumber") or 1)
        except (TypeError, ValueError):
            step_number = 1
        event["stepNumber"] = max(1, min(step_number, 999))

    return event


def current_millis():
    return int(time.time() * 1000)


async def verify_instructor_access(room_id, client_id, password):
    password_text = str(password or "").strip()
    if not password_text:
        return False, "Enter the instructor password first."

    if not INSTRUCTOR_AUTH_URL:
        return False, (
            "Instructor access is disabled until INSTRUCTOR_AUTH_URL "
            "(or SPARVI_INSTRUCTOR_AUTH_URL) is configured on the server."
        )

    try:
        return await asyncio.to_thread(
            request_instructor_auth,
            room_id,
            client_id,
            password_text
        )
    except Exception as error:
        print(f"[auth-error] {error}")
        return False, "Could not verify the instructor password right now."


def request_instructor_auth(room_id, client_id, password):
    payload = {
        "password": password,
        "roomId": room_id,
        "clientId": client_id,
        "role": "instructor",
        "source": "sparvi-desktop",
        "timestamp": current_millis()
    }
    encoded_payload = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SparviDesktopServer/1.0"
    }
    if INSTRUCTOR_AUTH_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {INSTRUCTOR_AUTH_BEARER_TOKEN}"
        headers["X-Sparvi-Server-Secret"] = INSTRUCTOR_AUTH_BEARER_TOKEN
        headers["X-Sparvi-Server-Shared-Secret"] = INSTRUCTOR_AUTH_BEARER_TOKEN
        headers["X-Shared-Secret"] = INSTRUCTOR_AUTH_BEARER_TOKEN
        headers["X-API-Key"] = INSTRUCTOR_AUTH_BEARER_TOKEN

    request = urllib_request.Request(
        INSTRUCTOR_AUTH_URL,
        data=encoded_payload,
        headers=headers,
        method="POST"
    )

    ssl_context = None
    if not INSTRUCTOR_AUTH_VERIFY_TLS:
        ssl_context = ssl._create_unverified_context()

    try:
        with urllib_request.urlopen(
            request,
            timeout=INSTRUCTOR_AUTH_TIMEOUT_SECONDS,
            context=ssl_context
        ) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            response_json = parse_auth_response_json(response_body)
            if is_auth_allowed(response_json):
                return True, ""

            denial_message = extract_auth_message(response_json)
            if denial_message:
                return False, denial_message
            return False, "Instructor password was rejected."
    except urllib_error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        response_snippet = " ".join(response_body.split())[:240]
        print(f"[auth-http-error] status={error.code} body={response_snippet!r}")
        response_json = parse_auth_response_json(response_body)
        denial_message = extract_auth_message(response_json)
        if denial_message:
            return False, denial_message
        if error.code in (401, 403):
            return False, "Instructor password was rejected."
        return False, f"Instructor auth endpoint returned HTTP {error.code}."
    except urllib_error.URLError as error:
        print(f"[auth-network-error] url={INSTRUCTOR_AUTH_URL!r} error={error}")
        return False, "The instructor auth endpoint is unreachable right now."


def parse_auth_response_json(raw_text):
    try:
        parsed = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_auth_allowed(response_json):
    if not isinstance(response_json, dict):
        return False

    if any(bool(response_json.get(key)) for key in ("ok", "authorized", "allow", "valid")):
        return True

    status_text = str(response_json.get("status") or "").strip().lower()
    return status_text in {"ok", "authorized", "allowed", "valid", "success"}


def extract_auth_message(response_json):
    if not isinstance(response_json, dict):
        return ""

    for key in ("message", "error", "detail", "reason"):
        value = str(response_json.get(key) or "").strip()
        if value:
            return value
    return ""


def find_instructor(room_id):
    room = rooms.get(room_id, {})
    for client in room.values():
        if client.role == "instructor":
            return client
    return None


def is_authorized_instructor(state):
    return bool(state.room_id and state.role == "instructor" and state.instructor_authorized)


async def main():
    print(f"[boot] Python {sys.version}")
    print(f"[boot] Sparvi Desktop server listening on ws://{HOST}:{PORT}")
    print(
        "[boot] Instructor auth endpoint: "
        + (INSTRUCTOR_AUTH_URL if INSTRUCTOR_AUTH_URL else "disabled")
    )
    print(
        "[boot] Instructor auth shared secret: "
        + ("configured" if INSTRUCTOR_AUTH_BEARER_TOKEN else "not set")
    )

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _signal_handler():
        print("[shutdown] Received termination signal, shutting down gracefully...")
        stop_event.set()

    # Register signal handlers for graceful shutdown (Linux/AlwaysData)
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        # On Windows, only SIGINT (Ctrl+C) works via default KeyboardInterrupt
        pass

    server = await websockets.serve(
        handle_connection,
        HOST,
        PORT,
        ping_interval=20,
        ping_timeout=20
    )

    print(f"[boot] Server started successfully, waiting for connections...")

    await stop_event.wait()

    print("[shutdown] Closing server...")
    server.close()
    await server.wait_closed()
    print("[shutdown] Server stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as error:
        if getattr(error, "errno", None) == 10048 or getattr(error, "errno", None) == 98:
            print(
                f"[error] Port {PORT} is already in use. "
                f"Close the other server or run with a different PORT value."
            )
            sys.exit(1)
        else:
            raise
    except KeyboardInterrupt:
        print("\n[shutdown] Server stopped.")
