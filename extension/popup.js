"use strict";

const elements = {};
let currentState = null;
let currentTabStatus = null;
let localError = "";

document.addEventListener("DOMContentLoaded", init);

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "STATE_UPDATE") {
    currentState = message.state;
    render();
  }
});

async function init() {
  elements.sessionId = document.getElementById("sessionId");
  elements.connectionStatus = document.getElementById("connectionStatus");
  elements.connectButton = document.getElementById("connectButton");
  elements.disconnectButton = document.getElementById("disconnectButton");
  elements.pointerToggleButton = document.getElementById("pointerToggleButton");
  elements.pulseButton = document.getElementById("pulseButton");
  elements.instructorControls = document.getElementById("instructorControls");
  elements.pageUrl = document.getElementById("pageUrl");
  elements.pageSupport = document.getElementById("pageSupport");
  elements.roomInfo = document.getElementById("roomInfo");
  elements.errorArea = document.getElementById("errorArea");
  elements.roleInputs = Array.from(document.querySelectorAll("input[name='role']"));

  bindEvents();
  await restoreForm();
  await refreshState();
  await refreshTabStatus();
  render();
}

function bindEvents() {
  elements.connectButton.addEventListener("click", connect);
  elements.disconnectButton.addEventListener("click", disconnect);
  elements.pointerToggleButton.addEventListener("click", togglePointer);
  elements.pulseButton.addEventListener("click", sendPulse);

  elements.sessionId.addEventListener("change", () => {
    chrome.storage.local.set({ sessionId: elements.sessionId.value.trim() });
  });

  elements.roleInputs.forEach((input) => {
    input.addEventListener("change", () => {
      chrome.storage.local.set({ role: getSelectedRole() });
      render();
    });
  });
}

async function restoreForm() {
  const stored = await storageGet(["sessionId", "role"]);
  elements.sessionId.value = stored.sessionId || "";
  setSelectedRole(stored.role === "instructor" ? "instructor" : "student");
}

async function refreshState() {
  const response = await sendToWorker({ type: "GET_STATE" });
  if (response.ok) {
    currentState = response.state;
    if (currentState.sessionId) {
      elements.sessionId.value = currentState.sessionId;
    }
    setSelectedRole(currentState.role || getSelectedRole());
  } else {
    localError = response.error || "Could not read extension state.";
  }
}

async function refreshTabStatus() {
  const response = await sendToWorker({ type: "TAB_STATUS_REQUEST" });
  if (response.ok) {
    currentState = response.state || currentState;
    currentTabStatus = response.tabStatus;
  } else {
    localError = response.error || "Could not check the active page.";
  }
}

async function connect() {
  const sessionId = elements.sessionId.value.trim();
  const role = getSelectedRole();

  if (!sessionId) {
    localError = "Enter a session ID first.";
    render();
    return;
  }

  localError = "";
  const response = await sendToWorker({
    type: "CONNECT",
    sessionId,
    role
  });

  if (!response.ok) {
    localError = response.error || "Could not connect.";
  }

  currentState = response.state || currentState;
  await refreshTabStatus();
  render();
}

async function disconnect() {
  localError = "";
  const response = await sendToWorker({ type: "DISCONNECT" });
  currentState = response.state || currentState;
  render();
}

async function togglePointer() {
  if (!currentState) {
    return;
  }

  localError = "";
  const response = await sendToWorker({
    type: currentState.pointerEnabled ? "STOP_POINTER" : "START_POINTER"
  });

  if (!response.ok) {
    localError = response.error || "Could not update Live Pointer.";
  }

  currentState = response.state || currentState;
  await refreshTabStatus();
  render();
}

async function sendPulse() {
  localError = "";
  const response = await sendToWorker({ type: "CLICK_PULSE" });
  if (!response.ok) {
    localError = response.error || "Could not send click pulse.";
  }
  currentState = response.state || currentState;
  render();
}

function render() {
  const role = currentState ? currentState.role : getSelectedRole();
  const connected = Boolean(currentState && currentState.connected);
  const connecting = currentState && ["connecting", "reconnecting"].includes(currentState.connectionStatus);
  const isInstructor = role === "instructor";
  const tabReady = Boolean(currentTabStatus && currentTabStatus.supported && currentTabStatus.contentReady);

  elements.connectionStatus.textContent = formatConnectionStatus(currentState);
  elements.pageUrl.textContent = formatPageUrl(currentTabStatus);
  elements.pageSupport.textContent = formatPageSupport(currentTabStatus);
  elements.roomInfo.textContent = formatRoomInfo(currentState);

  elements.connectButton.disabled = connected || connecting;
  elements.disconnectButton.disabled = !connected && !connecting;
  elements.sessionId.disabled = connected || connecting;
  elements.roleInputs.forEach((input) => {
    input.disabled = connected || connecting;
  });

  elements.instructorControls.hidden = !isInstructor;
  elements.pointerToggleButton.disabled = !connected || !isInstructor || !tabReady;
  elements.pulseButton.disabled = !connected || !isInstructor;
  elements.pointerToggleButton.textContent = currentState && currentState.pointerEnabled
    ? "Stop Live Pointer"
    : "Start Live Pointer";

  const error = localError || (currentState && currentState.lastError) || "";
  elements.errorArea.hidden = !error;
  elements.errorArea.textContent = error;
}

function formatConnectionStatus(appState) {
  if (!appState) {
    return "Checking state...";
  }

  const status = appState.connectionStatus || "disconnected";
  const role = appState.role || "student";
  return `${capitalize(status)} as ${role}`;
}

function formatPageUrl(tabStatus) {
  if (!tabStatus || !tabStatus.url) {
    return "No active page";
  }

  try {
    const url = new URL(tabStatus.url);
    return `${url.hostname}${url.pathname === "/" ? "" : url.pathname}`;
  } catch (error) {
    return tabStatus.url;
  }
}

function formatPageSupport(tabStatus) {
  if (!tabStatus) {
    return "Checking...";
  }

  if (!tabStatus.supported) {
    return tabStatus.reason || "Unsupported page";
  }

  if (!tabStatus.contentReady) {
    return "Supported, reload needed";
  }

  return "Supported";
}

function formatRoomInfo(appState) {
  if (!appState || !appState.sessionId) {
    return "Not joined";
  }

  const peer = appState.peer || {};
  if (appState.role === "student" && peer.mismatch) {
    return `${appState.sessionId} - teacher on different page`;
  }

  if (appState.role === "instructor") {
    return `${appState.sessionId} - ${peer.studentCount || 0} student(s)`;
  }

  return `${appState.sessionId} - ${peer.instructorConnected ? "teacher connected" : "waiting for teacher"}`;
}

function getSelectedRole() {
  const selected = elements.roleInputs.find((input) => input.checked);
  return selected ? selected.value : "student";
}

function setSelectedRole(role) {
  elements.roleInputs.forEach((input) => {
    input.checked = input.value === role;
  });
}

function capitalize(value) {
  return String(value || "").replace(/^\w/, (letter) => letter.toUpperCase());
}

function sendToWorker(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        resolve({ ok: false, error: error.message });
        return;
      }

      resolve(response || { ok: true });
    });
  });
}

function storageGet(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, resolve);
  });
}
