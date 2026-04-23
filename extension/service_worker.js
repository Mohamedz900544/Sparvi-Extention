"use strict";

const DEFAULT_SERVER_URL = "ws://localhost:8787";
const NORMAL_TAB_URLS = ["http://*/*", "https://*/*"];
const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;
const KEEPALIVE_INTERVAL_MS = 25000;

let socket = null;
let reconnectTimer = null;
let keepAliveTimer = null;
let manualDisconnect = false;
let restorePromise = null;

const state = {
  serverUrl: DEFAULT_SERVER_URL,
  sessionId: "",
  role: "student",
  connectionStatus: "disconnected",
  connected: false,
  pointerEnabled: false,
  clientId: null,
  lastError: "",
  reconnectAttempt: 0,
  activeTab: {
    id: null,
    title: "",
    url: "",
    supported: false,
    contentReady: false,
    reason: "No active tab checked yet."
  },
  peer: {
    instructorConnected: false,
    instructorUrl: "",
    pointerEnabled: false,
    studentCount: 0,
    mismatch: false
  }
};

restoreStoredState();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleRuntimeMessage(message || {}, sender)
    .then((response) => sendResponse(response))
    .catch((error) => {
      console.error("[Sparvi] Message handling failed:", error);
      sendResponse({ ok: false, error: error.message || "Unexpected extension error." });
    });

  return true;
});

chrome.tabs.onActivated.addListener(() => {
  refreshActiveTabAndNotifyServer();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.url || changeInfo.status === "complete")) {
    refreshActiveTabAndNotifyServer();
  }
});

chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId !== chrome.windows.WINDOW_ID_NONE) {
    refreshActiveTabAndNotifyServer();
  }
});

async function handleRuntimeMessage(message, sender) {
  await restoreStoredState();

  switch (message.type) {
    case "GET_STATE":
      return { ok: true, state: getPublicState() };

    case "TAB_STATUS_REQUEST": {
      const tabStatus = await getActiveTabStatus();
      notifyPopup();
      return { ok: true, tabStatus, state: getPublicState() };
    }

    case "CONNECT":
      return connect(message);

    case "DISCONNECT":
      disconnect();
      return { ok: true, state: getPublicState() };

    case "START_POINTER":
      return setPointerEnabled(true);

    case "STOP_POINTER":
      return setPointerEnabled(false);

    case "CURSOR_MOVE":
      return handleCursorMove(message, sender);

    case "CLICK_PULSE":
      return handleClickPulse(message, sender);

    case "PAGE_UPDATE":
      return handlePageUpdate(message, sender);

    default:
      return { ok: false, error: `Unknown message type: ${message.type || "missing"}` };
  }
}

async function connect(message) {
  const sessionId = normalizeSessionId(message.sessionId);
  const role = normalizeRole(message.role);
  const serverUrl = normalizeServerUrl(message.serverUrl || state.serverUrl);

  if (!sessionId) {
    setLastError("Enter a session ID before connecting.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  if (!role) {
    setLastError("Choose instructor or student before connecting.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  state.sessionId = sessionId;
  state.role = role;
  state.serverUrl = serverUrl;
  state.lastError = "";

  await storageSet({ sessionId, role, serverUrl });
  await getActiveTabStatus();

  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    sendJoinMessage();
    notifyAllState();
    return { ok: true, state: getPublicState() };
  }

  manualDisconnect = false;
  state.reconnectAttempt = 0;
  openSocket(false);
  return { ok: true, state: getPublicState() };
}

async function setPointerEnabled(enabled) {
  if (state.role !== "instructor") {
    setLastError("Only the instructor can control Live Pointer.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  if (!state.connected) {
    setLastError("Connect to a session before starting Live Pointer.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  const tabStatus = await getActiveTabStatus();
  if (!tabStatus.supported) {
    setLastError(tabStatus.reason || "This page is not supported.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  if (!tabStatus.contentReady) {
    setLastError("This page is supported, but the content script is not active yet. Reload the page and try again.");
    return { ok: false, error: state.lastError, state: getPublicState() };
  }

  state.pointerEnabled = Boolean(enabled);
  state.lastError = "";
  sendToServer({
    type: "pointer_state",
    enabled: state.pointerEnabled,
    currentUrl: state.activeTab.url
  });
  notifyAllState();
  return { ok: true, state: getPublicState() };
}

async function handleCursorMove(message, sender) {
  if (state.role !== "instructor" || !state.connected || !state.pointerEnabled) {
    return { ok: true, ignored: true };
  }

  const xRatio = normalizeRatio(message.xRatio);
  const yRatio = normalizeRatio(message.yRatio);
  if (xRatio === null || yRatio === null) {
    return { ok: false, error: "Invalid cursor coordinates." };
  }

  const currentUrl = getMessageUrl(message, sender);
  sendToServer({
    type: "cursor_move",
    xRatio,
    yRatio,
    currentUrl,
    viewport: message.viewport || null,
    timestamp: Date.now()
  });

  return { ok: true };
}

async function handleClickPulse(message, sender) {
  if (state.role !== "instructor" || !state.connected) {
    return { ok: true, ignored: true };
  }

  let xRatio = normalizeRatio(message.xRatio);
  let yRatio = normalizeRatio(message.yRatio);
  let currentUrl = getMessageUrl(message, sender);

  if (xRatio === null || yRatio === null) {
    xRatio = 0.5;
    yRatio = 0.5;
    const tabStatus = await getActiveTabStatus();
    currentUrl = tabStatus.url || currentUrl;
  }

  sendToServer({
    type: "click_pulse",
    xRatio,
    yRatio,
    currentUrl,
    timestamp: Date.now()
  });

  return { ok: true };
}

async function handlePageUpdate(message, sender) {
  const currentUrl = getMessageUrl(message, sender);
  const supported = isNormalWebUrl(currentUrl);

  if (sender.tab && sender.tab.id) {
    const isActive = await isActiveTab(sender.tab.id);
    if (!isActive) {
      return { ok: true, ignored: true };
    }
  }

  state.activeTab = {
    id: sender.tab ? sender.tab.id : state.activeTab.id,
    title: sender.tab ? sender.tab.title || "" : state.activeTab.title,
    url: currentUrl,
    supported,
    contentReady: supported,
    reason: supported ? "" : unsupportedReason(currentUrl)
  };

  if (state.connected && supported) {
    sendToServer({
      type: "page_update",
      currentUrl
    });
  }

  notifyPopup();
  return { ok: true, state: getPublicState() };
}

function openSocket(isReconnect) {
  clearReconnectTimer();
  stopKeepAlive();

  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  setConnectionStatus(isReconnect ? "reconnecting" : "connecting");

  try {
    socket = new WebSocket(state.serverUrl);
  } catch (error) {
    setLastError(`Could not open WebSocket: ${error.message}`);
    scheduleReconnect();
    return;
  }

  socket.addEventListener("open", () => {
    state.reconnectAttempt = 0;
    state.clientId = null;
    state.lastError = "";
    setConnectionStatus("connected");
    sendJoinMessage();
    startKeepAlive();
  });

  socket.addEventListener("message", (event) => {
    handleServerMessage(event.data);
  });

  socket.addEventListener("close", (event) => {
    stopKeepAlive();
    socket = null;
    state.connected = false;
    state.clientId = null;

    if (manualDisconnect) {
      state.connectionStatus = "disconnected";
      state.lastError = "";
      notifyAllState();
      return;
    }

    state.lastError = event.reason || "WebSocket connection closed.";
    scheduleReconnect();
  });

  socket.addEventListener("error", () => {
    setLastError("Could not connect to the local WebSocket server.");
  });
}

function disconnect() {
  manualDisconnect = true;
  clearReconnectTimer();
  stopKeepAlive();

  const closingSocket = socket;
  socket = null;

  if (closingSocket && closingSocket.readyState === WebSocket.OPEN) {
    try {
      closingSocket.send(JSON.stringify({ type: "leave" }));
      closingSocket.close(1000, "User disconnected");
    } catch (error) {
      console.warn("[Sparvi] Error while closing socket:", error);
    }
  } else if (closingSocket) {
    try {
      closingSocket.close();
    } catch (error) {
      console.warn("[Sparvi] Error while closing pending socket:", error);
    }
  }

  state.connectionStatus = "disconnected";
  state.connected = false;
  state.pointerEnabled = false;
  state.clientId = null;
  state.lastError = "";
  state.peer = {
    instructorConnected: false,
    instructorUrl: "",
    pointerEnabled: false,
    studentCount: 0,
    mismatch: false
  };
  notifyAllState();
}

function scheduleReconnect() {
  clearReconnectTimer();

  if (manualDisconnect || !state.sessionId) {
    setConnectionStatus("disconnected");
    return;
  }

  if (state.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
    state.connectionStatus = "disconnected";
    state.connected = false;
    state.lastError = "Connection lost. Reconnect from the popup when the server is available.";
    notifyAllState();
    return;
  }

  state.reconnectAttempt += 1;
  const delay = Math.min(
    MAX_RECONNECT_DELAY_MS,
    BASE_RECONNECT_DELAY_MS * Math.pow(2, state.reconnectAttempt - 1)
  );

  state.connectionStatus = "reconnecting";
  state.connected = false;
  state.lastError = `Connection lost. Reconnecting in ${Math.ceil(delay / 1000)} seconds.`;
  notifyAllState();

  reconnectTimer = setTimeout(() => {
    openSocket(true);
  }, delay);
}

function sendJoinMessage() {
  if (!state.sessionId || !state.role) {
    return;
  }

  sendToServer({
    type: "join",
    roomId: state.sessionId,
    role: state.role,
    currentUrl: state.activeTab.url || "",
    pointerEnabled: state.role === "instructor" && state.pointerEnabled
  });
}

function handleServerMessage(rawData) {
  let message;
  try {
    message = JSON.parse(rawData);
  } catch (error) {
    console.warn("[Sparvi] Ignoring malformed server message:", rawData);
    return;
  }

  switch (message.type) {
    case "joined":
      state.clientId = message.clientId || null;
      state.lastError = "";
      notifyAllState();
      break;

    case "peer_status":
      state.peer.instructorConnected = Boolean(message.instructorConnected);
      state.peer.instructorUrl = message.instructorUrl || "";
      state.peer.pointerEnabled = Boolean(message.pointerEnabled);
      state.peer.studentCount = Number(message.studentCount || 0);
      notifyPopup();
      broadcastToContentScripts({ type: "PEER_STATUS", peer: state.peer });
      break;

    case "cursor_move":
      broadcastToContentScripts({ type: "REMOTE_CURSOR_MOVE", payload: message });
      break;

    case "click_pulse":
      broadcastToContentScripts({ type: "REMOTE_CLICK_PULSE", payload: message });
      break;

    case "page_mismatch":
      state.peer.mismatch = Boolean(message.mismatch);
      state.peer.instructorUrl = message.instructorUrl || state.peer.instructorUrl;
      notifyPopup();
      broadcastToContentScripts({ type: "PAGE_MISMATCH", payload: message });
      break;

    case "pointer_state":
      state.peer.pointerEnabled = Boolean(message.enabled);
      notifyPopup();
      broadcastToContentScripts({ type: "REMOTE_POINTER_STATE", payload: message });
      break;

    case "error":
      setLastError(message.message || "Server returned an error.");
      break;

    case "pong":
      break;

    default:
      console.warn("[Sparvi] Unknown server message type:", message.type);
  }
}

async function refreshActiveTabAndNotifyServer() {
  await restoreStoredState();
  const tabStatus = await getActiveTabStatus();
  notifyPopup();

  if (state.connected && tabStatus.supported) {
    sendToServer({
      type: "page_update",
      currentUrl: tabStatus.url
    });
  }
}

async function getActiveTabStatus() {
  const tabs = await queryTabs({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];

  if (!tab) {
    state.activeTab = {
      id: null,
      title: "",
      url: "",
      supported: false,
      contentReady: false,
      reason: "No active tab is available."
    };
    return state.activeTab;
  }

  const supported = isNormalWebUrl(tab.url);
  const baseStatus = {
    id: tab.id,
    title: tab.title || "",
    url: tab.url || "",
    supported,
    contentReady: false,
    reason: supported ? "" : unsupportedReason(tab.url)
  };

  if (!supported) {
    state.activeTab = baseStatus;
    return state.activeTab;
  }

  const contentResponse = await sendMessageToTab(tab.id, { type: "CONTENT_STATUS_REQUEST" });
  if (contentResponse.ok && contentResponse.response && contentResponse.response.supported) {
    state.activeTab = {
      ...baseStatus,
      contentReady: true,
      reason: ""
    };
  } else {
    state.activeTab = {
      ...baseStatus,
      contentReady: false,
      reason: "This page is supported, but the content script is not active yet. Reload the tab and try again."
    };
  }

  return state.activeTab;
}

async function isActiveTab(tabId) {
  try {
    const tab = await getTab(tabId);
    return Boolean(tab && tab.active);
  } catch (error) {
    return false;
  }
}

function sendToServer(message) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return false;
  }

  try {
    socket.send(JSON.stringify(message));
    return true;
  } catch (error) {
    setLastError(`Failed to send message: ${error.message}`);
    return false;
  }
}

function startKeepAlive() {
  stopKeepAlive();
  keepAliveTimer = setInterval(() => {
    sendToServer({ type: "ping", timestamp: Date.now() });
  }, KEEPALIVE_INTERVAL_MS);
}

function stopKeepAlive() {
  if (keepAliveTimer) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function setConnectionStatus(status) {
  state.connectionStatus = status;
  state.connected = status === "connected";
  notifyAllState();
}

function setLastError(message) {
  state.lastError = message || "";
  notifyPopup();
}

function notifyAllState() {
  notifyPopup();
  broadcastToContentScripts({ type: "STATE_UPDATE", state: getPublicState() });
}

function notifyPopup() {
  chrome.runtime.sendMessage({ type: "STATE_UPDATE", state: getPublicState() }, () => {
    void chrome.runtime.lastError;
  });
}

async function broadcastToContentScripts(message) {
  const tabs = await queryTabs({ url: NORMAL_TAB_URLS });
  await Promise.all(
    tabs.map((tab) => sendMessageToTab(tab.id, message))
  );
}

function getPublicState() {
  return JSON.parse(JSON.stringify(state));
}

async function restoreStoredState() {
  if (restorePromise) {
    return restorePromise;
  }

  restorePromise = storageGet(["sessionId", "role", "serverUrl"]).then((stored) => {
    state.sessionId = normalizeSessionId(stored.sessionId) || "";
    state.role = normalizeRole(stored.role) || "student";
    state.serverUrl = normalizeServerUrl(stored.serverUrl || DEFAULT_SERVER_URL);
  });

  return restorePromise;
}

function normalizeSessionId(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.trim().slice(0, 100);
}

function normalizeRole(value) {
  return value === "instructor" || value === "student" ? value : null;
}

function normalizeServerUrl(value) {
  if (typeof value !== "string" || !value.trim()) {
    return DEFAULT_SERVER_URL;
  }

  return value.trim();
}

function normalizeRatio(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return null;
  }

  return Math.max(0, Math.min(1, number));
}

function getMessageUrl(message, sender) {
  return String(message.currentUrl || message.url || (sender.tab && sender.tab.url) || state.activeTab.url || "");
}

function isNormalWebUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (error) {
    return false;
  }
}

function unsupportedReason(url) {
  if (!url) {
    return "This page URL is not available.";
  }

  try {
    const parsed = new URL(url);
    if (parsed.protocol === "chrome:" || parsed.protocol === "chrome-extension:" || parsed.protocol === "edge:" || parsed.protocol === "about:") {
      return "Browser internal pages do not allow regular extension content scripts.";
    }

    if (parsed.protocol === "file:") {
      return "Local file pages are not enabled for this MVP.";
    }

    return `The ${parsed.protocol} URL scheme is not supported. Open an http or https website.`;
  } catch (error) {
    return "This page URL could not be read.";
  }
}

function storageGet(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, resolve);
  });
}

function storageSet(items) {
  return new Promise((resolve) => {
    chrome.storage.local.set(items, resolve);
  });
}

function queryTabs(queryInfo) {
  return new Promise((resolve) => {
    chrome.tabs.query(queryInfo, resolve);
  });
}

function getTab(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.get(tabId, (tab) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(tab);
    });
  });
}

function sendMessageToTab(tabId, message) {
  return new Promise((resolve) => {
    if (!tabId) {
      resolve({ ok: false, error: "Missing tab id." });
      return;
    }

    chrome.tabs.sendMessage(tabId, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        resolve({ ok: false, error: error.message });
        return;
      }
      resolve({ ok: true, response });
    });
  });
}
