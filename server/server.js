"use strict";

const crypto = require("crypto");
const WebSocket = require("ws");

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || "0.0.0.0";
const HEARTBEAT_INTERVAL_MS = 30000;
const MAX_URL_LENGTH = 2048;
const MAX_ROOM_ID_LENGTH = 100;

const rooms = new Map();
const clientsBySocket = new Map();

const wss = new WebSocket.Server({ host: HOST, port: PORT }, () => {
  console.log(`[server] Sparvi Live Pointer listening on ws://${HOST}:${PORT}`);
});

wss.on("connection", (ws, request) => {
  const client = {
    clientId: createClientId(),
    ws,
    role: null,
    roomId: null,
    currentUrl: "",
    pointerEnabled: false,
    joinedAt: null,
    remoteAddress: request.socket.remoteAddress
  };

  ws.isAlive = true;
  clientsBySocket.set(ws, client);
  console.log(`[server] client connected ${client.clientId} from ${client.remoteAddress}`);

  ws.on("pong", () => {
    ws.isAlive = true;
  });

  ws.on("message", (raw) => {
    handleRawMessage(client, raw);
  });

  ws.on("close", () => {
    removeClientFromRoom(client);
    clientsBySocket.delete(ws);
    console.log(`[server] client disconnected ${client.clientId}`);
  });

  ws.on("error", (error) => {
    console.warn(`[server] websocket error for ${client.clientId}: ${error.message}`);
  });
});

const heartbeatTimer = setInterval(() => {
  for (const ws of wss.clients) {
    if (ws.isAlive === false) {
      const client = clientsBySocket.get(ws);
      if (client) {
        console.warn(`[server] terminating stale client ${client.clientId}`);
      }
      ws.terminate();
      continue;
    }

    ws.isAlive = false;
    ws.ping();
  }
}, HEARTBEAT_INTERVAL_MS);

function handleRawMessage(client, raw) {
  let message;
  try {
    message = JSON.parse(raw.toString());
  } catch (error) {
    sendError(client, "Malformed JSON message.", "malformed_json");
    return;
  }

  if (!message || typeof message.type !== "string") {
    sendError(client, "Message must include a type field.", "missing_type");
    return;
  }

  switch (message.type) {
    case "join":
      handleJoin(client, message);
      break;

    case "cursor_move":
      handleCursorMove(client, message);
      break;

    case "click_pulse":
      handleClickPulse(client, message);
      break;

    case "page_update":
      handlePageUpdate(client, message);
      break;

    case "pointer_state":
      handlePointerState(client, message);
      break;

    case "leave":
      removeClientFromRoom(client);
      safeSend(client, { type: "peer_status", roomId: null, instructorConnected: false, studentCount: 0 });
      break;

    case "ping":
      safeSend(client, { type: "pong", timestamp: Date.now() });
      break;

    default:
      sendError(client, `Unsupported message type: ${message.type}`, "unsupported_type");
  }
}

function handleJoin(client, message) {
  const roomId = normalizeRoomId(message.roomId);
  const role = normalizeRole(message.role);

  if (!roomId) {
    sendError(client, "Session ID is required and must be 100 characters or fewer.", "invalid_room");
    return;
  }

  if (!role) {
    sendError(client, "Role must be instructor or student.", "invalid_role");
    return;
  }

  const room = getOrCreateRoom(roomId);
  const existingInstructor = findInstructor(roomId);
  if (role === "instructor" && existingInstructor && existingInstructor.clientId !== client.clientId) {
    sendError(client, "This room already has an instructor connected.", "instructor_exists");
    return;
  }

  removeClientFromRoom(client);

  client.roomId = roomId;
  client.role = role;
  client.currentUrl = normalizeUrl(message.currentUrl);
  client.pointerEnabled = role === "instructor" && Boolean(message.pointerEnabled);
  client.joinedAt = Date.now();
  room.set(client.clientId, client);

  safeSend(client, {
    type: "joined",
    clientId: client.clientId,
    roomId,
    role
  });

  console.log(`[server] ${client.clientId} joined room ${roomId} as ${role}`);
  broadcastPeerStatus(roomId);
  sendPageMismatchForRoom(roomId);
}

function handleCursorMove(client, message) {
  if (!isJoinedInstructor(client)) {
    sendError(client, "Only the joined instructor can send cursor movement.", "not_instructor");
    return;
  }

  if (!client.pointerEnabled) {
    return;
  }

  const xRatio = normalizeRatio(message.xRatio);
  const yRatio = normalizeRatio(message.yRatio);
  if (xRatio === null || yRatio === null) {
    sendError(client, "Cursor coordinates must be ratios between 0 and 1.", "invalid_coordinates");
    return;
  }

  const previousUrl = client.currentUrl;
  client.currentUrl = normalizeUrl(message.currentUrl || client.currentUrl);

  broadcastToStudents(client.roomId, {
    type: "cursor_move",
    instructorId: client.clientId,
    xRatio,
    yRatio,
    currentUrl: client.currentUrl,
    timestamp: Date.now()
  });

  if (client.currentUrl !== previousUrl) {
    broadcastPeerStatus(client.roomId);
    sendPageMismatchForRoom(client.roomId);
  }
}

function handleClickPulse(client, message) {
  if (!isJoinedInstructor(client)) {
    sendError(client, "Only the joined instructor can send click pulses.", "not_instructor");
    return;
  }

  const xRatio = normalizeRatio(message.xRatio);
  const yRatio = normalizeRatio(message.yRatio);
  if (xRatio === null || yRatio === null) {
    sendError(client, "Click pulse coordinates must be ratios between 0 and 1.", "invalid_coordinates");
    return;
  }

  client.currentUrl = normalizeUrl(message.currentUrl || client.currentUrl);

  broadcastToStudents(client.roomId, {
    type: "click_pulse",
    instructorId: client.clientId,
    xRatio,
    yRatio,
    currentUrl: client.currentUrl,
    timestamp: Date.now()
  });
}

function handlePageUpdate(client, message) {
  if (!client.roomId) {
    sendError(client, "Join a room before sending page updates.", "not_joined");
    return;
  }

  client.currentUrl = normalizeUrl(message.currentUrl);
  broadcastPeerStatus(client.roomId);
  sendPageMismatchForRoom(client.roomId);
}

function handlePointerState(client, message) {
  if (!isJoinedInstructor(client)) {
    sendError(client, "Only the instructor can change pointer state.", "not_instructor");
    return;
  }

  client.pointerEnabled = Boolean(message.enabled);
  client.currentUrl = normalizeUrl(message.currentUrl || client.currentUrl);

  broadcastToRoom(client.roomId, {
    type: "pointer_state",
    instructorId: client.clientId,
    enabled: client.pointerEnabled,
    currentUrl: client.currentUrl,
    timestamp: Date.now()
  });

  broadcastPeerStatus(client.roomId);
  sendPageMismatchForRoom(client.roomId);
}

function removeClientFromRoom(client) {
  if (!client.roomId) {
    return;
  }

  const oldRoomId = client.roomId;
  const room = rooms.get(oldRoomId);
  if (room) {
    room.delete(client.clientId);
    if (room.size === 0) {
      rooms.delete(oldRoomId);
    }
  }

  client.roomId = null;
  client.role = null;
  client.currentUrl = "";
  client.pointerEnabled = false;
  client.joinedAt = null;

  broadcastPeerStatus(oldRoomId);
  sendPageMismatchForRoom(oldRoomId);
}

function broadcastPeerStatus(roomId) {
  const room = rooms.get(roomId);
  if (!room) {
    return;
  }

  const clients = Array.from(room.values());
  const instructor = clients.find((client) => client.role === "instructor") || null;
  const students = clients.filter((client) => client.role === "student");

  broadcastToRoom(roomId, {
    type: "peer_status",
    roomId,
    instructorConnected: Boolean(instructor),
    instructorUrl: instructor ? instructor.currentUrl : "",
    pointerEnabled: instructor ? instructor.pointerEnabled : false,
    studentCount: students.length,
    clientCount: clients.length
  });
}

function sendPageMismatchForRoom(roomId) {
  const room = rooms.get(roomId);
  if (!room) {
    return;
  }

  const instructor = findInstructor(roomId);
  for (const client of room.values()) {
    if (client.role !== "student") {
      continue;
    }

    const mismatch = Boolean(
      instructor &&
      instructor.currentUrl &&
      client.currentUrl &&
      instructor.currentUrl !== client.currentUrl
    );

    safeSend(client, {
      type: "page_mismatch",
      roomId,
      mismatch,
      instructorConnected: Boolean(instructor),
      instructorUrl: instructor ? instructor.currentUrl : "",
      studentUrl: client.currentUrl
    });
  }
}

function broadcastToRoom(roomId, message) {
  const room = rooms.get(roomId);
  if (!room) {
    return;
  }

  for (const client of room.values()) {
    safeSend(client, message);
  }
}

function broadcastToStudents(roomId, message) {
  const room = rooms.get(roomId);
  if (!room) {
    return;
  }

  for (const client of room.values()) {
    if (client.role === "student") {
      safeSend(client, message);
    }
  }
}

function getOrCreateRoom(roomId) {
  if (!rooms.has(roomId)) {
    rooms.set(roomId, new Map());
  }
  return rooms.get(roomId);
}

function findInstructor(roomId) {
  const room = rooms.get(roomId);
  if (!room) {
    return null;
  }

  for (const client of room.values()) {
    if (client.role === "instructor") {
      return client;
    }
  }

  return null;
}

function isJoinedInstructor(client) {
  return Boolean(client.roomId && client.role === "instructor");
}

function safeSend(client, message) {
  if (!client || !client.ws || client.ws.readyState !== WebSocket.OPEN) {
    return false;
  }

  try {
    client.ws.send(JSON.stringify(message));
    return true;
  } catch (error) {
    console.warn(`[server] send failed for ${client.clientId}: ${error.message}`);
    return false;
  }
}

function sendError(client, message, code) {
  safeSend(client, {
    type: "error",
    code,
    message
  });
}

function createClientId() {
  if (crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return crypto.randomBytes(16).toString("hex");
}

function normalizeRoomId(value) {
  if (typeof value !== "string") {
    return "";
  }

  const roomId = value.trim().slice(0, MAX_ROOM_ID_LENGTH);
  return roomId;
}

function normalizeRole(value) {
  return value === "instructor" || value === "student" ? value : null;
}

function normalizeRatio(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return null;
  }

  return Math.max(0, Math.min(1, number));
}

function normalizeUrl(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.slice(0, MAX_URL_LENGTH);
}

function shutdown(signal) {
  console.log(`[server] received ${signal}, shutting down`);
  clearInterval(heartbeatTimer);

  for (const client of clientsBySocket.values()) {
    safeSend(client, { type: "error", code: "server_shutdown", message: "Server is shutting down." });
    client.ws.close(1001, "Server shutdown");
  }

  wss.close(() => {
    process.exit(0);
  });
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
