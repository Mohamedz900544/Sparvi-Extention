"use strict";

(() => {
  if (window.__sparviLivePointerLoaded) {
    return;
  }
  window.__sparviLivePointerLoaded = true;

  const ROOT_ID = "sparvi-live-pointer-root";
  const SEND_INTERVAL_MS = 40;
  const REMOTE_HIDE_MS = 1500;
  const URL_POLL_INTERVAL_MS = 1000;

  const runtimeState = {
    role: "student",
    connected: false,
    pointerEnabled: false
  };

  const remotePointer = {
    visible: false,
    x: 0,
    y: 0,
    targetX: 0,
    targetY: 0,
    rafId: null,
    hideTimer: null
  };

  let elements = {};
  let lastSentAt = 0;
  let pendingMove = null;
  let pendingMoveTimer = null;
  let lastKnownUrl = window.location.href;

  if (!isSupportedPage()) {
    console.info("[Sparvi] This page is unsupported. Live Pointer runs only on http and https pages.");
    return;
  }

  ensureOverlay();
  installInputListeners();
  installUrlChangeDetection();
  announcePage();
  requestInitialState();

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {
      case "CONTENT_STATUS_REQUEST":
        sendResponse({
          supported: true,
          currentUrl: window.location.href,
          title: document.title
        });
        return true;

      case "STATE_UPDATE":
        applyRuntimeState(message.state || {});
        return false;

      case "REMOTE_CURSOR_MOVE":
        renderRemoteCursor(message.payload || {});
        return false;

      case "REMOTE_CLICK_PULSE":
        renderClickPulse(message.payload || {});
        return false;

      case "REMOTE_POINTER_STATE":
        if (!message.payload || !message.payload.enabled) {
          hidePointer();
        }
        return false;

      case "PAGE_MISMATCH":
        updateMismatchBadge(message.payload || {});
        return false;

      case "PEER_STATUS":
        updateMismatchBadge({
          instructorUrl: message.peer && message.peer.instructorUrl
        });
        return false;

      default:
        return false;
    }
  });

  function ensureOverlay() {
    let root = document.getElementById(ROOT_ID);

    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.setAttribute("aria-hidden", "true");
      root.innerHTML = [
        '<div class="sparvi-instructor-stage" data-visible="false" data-active="false">',
        '  <div class="sparvi-stage-title">Live Pointer Area</div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-tl"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-tr"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-bl"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-br"></div>',
        '</div>',
        '<div class="sparvi-pointer" data-visible="false">',
        '  <div class="sparvi-cursor-shape"></div>',
        '  <div class="sparvi-label">Teacher</div>',
        '</div>',
        '<div class="sparvi-page-badge" data-visible="false">Teacher is on a different page</div>'
      ].join("");

      const target = document.body || document.documentElement;
      target.appendChild(root);
    }

    elements.root = root;
    elements.stage = root.querySelector(".sparvi-instructor-stage");
    elements.pointer = root.querySelector(".sparvi-pointer");
    elements.badge = root.querySelector(".sparvi-page-badge");
  }

  function installInputListeners() {
    document.addEventListener("mousemove", handleMouseMove, { capture: true, passive: true });
    document.addEventListener("click", handleClick, { capture: true, passive: true });
  }

  function handleMouseMove(event) {
    if (!canSendPointer()) {
      return;
    }

    const stagePoint = getInstructorStagePoint(event);
    updateInstructorStageActive(Boolean(stagePoint));

    if (!stagePoint) {
      return;
    }

    pendingMove = {
      type: "CURSOR_MOVE",
      xRatio: stagePoint.xRatio,
      yRatio: stagePoint.yRatio,
      currentUrl: window.location.href,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        source: "instructor-stage"
      }
    };

    const elapsed = Date.now() - lastSentAt;
    if (elapsed >= SEND_INTERVAL_MS) {
      flushPendingMove();
      return;
    }

    if (!pendingMoveTimer) {
      pendingMoveTimer = setTimeout(flushPendingMove, SEND_INTERVAL_MS - elapsed);
    }
  }

  function flushPendingMove() {
    if (pendingMoveTimer) {
      clearTimeout(pendingMoveTimer);
      pendingMoveTimer = null;
    }

    if (!pendingMove || !canSendPointer()) {
      pendingMove = null;
      return;
    }

    sendToWorker(pendingMove);
    pendingMove = null;
    lastSentAt = Date.now();
  }

  function handleClick(event) {
    if (!canSendPointer()) {
      return;
    }

    const stagePoint = getInstructorStagePoint(event);
    updateInstructorStageActive(Boolean(stagePoint));

    if (!stagePoint) {
      return;
    }

    sendToWorker({
      type: "CLICK_PULSE",
      xRatio: stagePoint.xRatio,
      yRatio: stagePoint.yRatio,
      currentUrl: window.location.href
    });
  }

  function renderRemoteCursor(payload) {
    if (runtimeState.role !== "student") {
      return;
    }

    const xRatio = clampRatio(payload.xRatio);
    const yRatio = clampRatio(payload.yRatio);
    if (xRatio === null || yRatio === null) {
      return;
    }

    ensureOverlay();
    updateMismatchBadge({ instructorUrl: payload.currentUrl });

    remotePointer.targetX = xRatio * window.innerWidth;
    remotePointer.targetY = yRatio * window.innerHeight;

    if (!remotePointer.visible) {
      remotePointer.x = remotePointer.targetX;
      remotePointer.y = remotePointer.targetY;
      remotePointer.visible = true;
      elements.pointer.dataset.visible = "true";
    }

    if (!remotePointer.rafId) {
      remotePointer.rafId = requestAnimationFrame(animatePointer);
    }

    if (remotePointer.hideTimer) {
      clearTimeout(remotePointer.hideTimer);
    }
    remotePointer.hideTimer = setTimeout(hidePointer, REMOTE_HIDE_MS);
  }

  function animatePointer() {
    remotePointer.x += (remotePointer.targetX - remotePointer.x) * 0.35;
    remotePointer.y += (remotePointer.targetY - remotePointer.y) * 0.35;

    setPointerPosition(remotePointer.x, remotePointer.y);

    const dx = Math.abs(remotePointer.targetX - remotePointer.x);
    const dy = Math.abs(remotePointer.targetY - remotePointer.y);

    if (remotePointer.visible && (dx > 0.5 || dy > 0.5)) {
      remotePointer.rafId = requestAnimationFrame(animatePointer);
    } else {
      remotePointer.x = remotePointer.targetX;
      remotePointer.y = remotePointer.targetY;
      setPointerPosition(remotePointer.x, remotePointer.y);
      remotePointer.rafId = null;
    }
  }

  function setPointerPosition(x, y) {
    elements.pointer.style.setProperty(
      "transform",
      `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`,
      "important"
    );
  }

  function hidePointer() {
    remotePointer.visible = false;
    if (elements.pointer) {
      elements.pointer.dataset.visible = "false";
    }
    if (remotePointer.rafId) {
      cancelAnimationFrame(remotePointer.rafId);
      remotePointer.rafId = null;
    }
  }

  function renderClickPulse(payload) {
    if (runtimeState.role !== "student") {
      return;
    }

    const xRatio = clampRatio(payload.xRatio);
    const yRatio = clampRatio(payload.yRatio);
    if (xRatio === null || yRatio === null) {
      return;
    }

    ensureOverlay();
    updateMismatchBadge({ instructorUrl: payload.currentUrl });

    const pulse = document.createElement("div");
    pulse.className = "sparvi-click-pulse";
    pulse.style.left = `${xRatio * window.innerWidth}px`;
    pulse.style.top = `${yRatio * window.innerHeight}px`;
    elements.root.appendChild(pulse);

    pulse.addEventListener("animationend", () => pulse.remove(), { once: true });
    setTimeout(() => pulse.remove(), 1000);
  }

  function updateMismatchBadge(payload) {
    ensureOverlay();

    const instructorUrl = payload.instructorUrl || payload.currentUrl || "";
    const mismatch = Boolean(instructorUrl && instructorUrl !== window.location.href);
    elements.badge.dataset.visible = mismatch ? "true" : "false";
  }

  function applyRuntimeState(nextState) {
    runtimeState.role = nextState.role || runtimeState.role;
    runtimeState.connected = Boolean(nextState.connected);
    runtimeState.pointerEnabled = Boolean(nextState.pointerEnabled);
    updateInstructorStageVisibility();

    if (!canSendPointer()) {
      pendingMove = null;
      if (pendingMoveTimer) {
        clearTimeout(pendingMoveTimer);
        pendingMoveTimer = null;
      }
      updateInstructorStageActive(false);
    }

    if (runtimeState.role === "student") {
      ensureOverlay();
    }
  }

  function installUrlChangeDetection() {
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function pushStateWrapper() {
      const result = originalPushState.apply(this, arguments);
      setTimeout(checkForUrlChange, 0);
      return result;
    };

    history.replaceState = function replaceStateWrapper() {
      const result = originalReplaceState.apply(this, arguments);
      setTimeout(checkForUrlChange, 0);
      return result;
    };

    window.addEventListener("popstate", checkForUrlChange);
    window.addEventListener("hashchange", checkForUrlChange);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        checkForUrlChange();
        announcePage();
      }
    });

    setInterval(checkForUrlChange, URL_POLL_INTERVAL_MS);
  }

  function checkForUrlChange() {
    if (window.location.href === lastKnownUrl) {
      return;
    }

    lastKnownUrl = window.location.href;
    hidePointer();
    updateMismatchBadge({ instructorUrl: "" });
    announcePage();
  }

  function requestInitialState() {
    sendToWorker({ type: "GET_STATE" }, (response) => {
      if (response && response.ok && response.state) {
        applyRuntimeState(response.state);
      }
    });
  }

  function announcePage() {
    sendToWorker({
      type: "PAGE_UPDATE",
      currentUrl: window.location.href,
      supported: true
    });
  }

  function canSendPointer() {
    return runtimeState.role === "instructor" && runtimeState.connected && runtimeState.pointerEnabled;
  }

  function getInstructorStagePoint(event) {
    ensureOverlay();

    if (!elements.stage) {
      return null;
    }

    const rect = elements.stage.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return null;
    }

    const inside = event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;

    if (!inside) {
      return null;
    }

    return {
      xRatio: clampRatio((event.clientX - rect.left) / rect.width),
      yRatio: clampRatio((event.clientY - rect.top) / rect.height)
    };
  }

  function updateInstructorStageVisibility() {
    ensureOverlay();

    const visible = canSendPointer();
    elements.stage.dataset.visible = visible ? "true" : "false";
  }

  function updateInstructorStageActive(active) {
    if (!elements.stage) {
      return;
    }

    elements.stage.dataset.active = active ? "true" : "false";
  }

  function isSupportedPage() {
    return window.location.protocol === "http:" || window.location.protocol === "https:";
  }

  function clampRatio(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return null;
    }

    return Math.max(0, Math.min(1, number));
  }

  function sendToWorker(message, callback) {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        void chrome.runtime.lastError;
        if (callback) {
          callback(response);
        }
      });
    } catch (error) {
      console.debug("[Sparvi] Could not send message to service worker:", error);
    }
  }
})();
