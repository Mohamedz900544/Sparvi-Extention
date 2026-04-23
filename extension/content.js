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
  const STAGE_STORAGE_KEY = "sparviInstructorStageLayout";
  const STAGE_MARGIN = 12;
  const STAGE_TOP_MARGIN = 64;
  const STAGE_TOOLBAR_GAP = 14;
  const STAGE_TOOLBAR_WIDTH = 72;
  const MIN_STAGE_WIDTH = 260;
  const MIN_STAGE_HEIGHT = 170;
  const DRAG_THRESHOLD_PX = 3;
  const TOOL_SEND_INTERVAL_MS = 45;
  const DRAW_TOOL_MODES = new Set(["arrow", "circle", "underline"]);

  const runtimeState = {
    clientId: null,
    role: "student",
    connected: false,
    pointerEnabled: false,
    pointerTargetClientId: "all",
    peer: {
      students: []
    }
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
  let stageListenersInstalled = false;
  let suppressNextStageClick = false;
  let suppressStageClickTimer = null;
  let currentToolMode = "pointer";
  let toolInteraction = null;
  let lastToolSentAt = 0;
  let hotspotStepNumber = 1;

  const stageState = {
    initialized: false,
    left: 0,
    top: 0,
    width: 0,
    height: 0
  };

  let stageInteraction = null;

  if (!isSupportedPage()) {
    console.info("[Sparvi] This page is unsupported. Live Pointer runs only on http and https pages.");
    return;
  }

  ensureOverlay();
  initializeStageLayout();
  installInputListeners();
  installStageInteractionListeners();
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

      case "REMOTE_TOOL_EVENT":
        renderRemoteToolEvent(message.payload || {});
        return false;

      case "REMOTE_POINTER_STATE":
        applyPointerTargetUpdate(message.payload || {});
        if (!message.payload || !message.payload.enabled) {
          hidePointer();
        }
        return false;

      case "POINTER_TARGET_UPDATE":
        applyPointerTargetUpdate(message.payload || {});
        return false;

      case "PAGE_MISMATCH":
        updateMismatchBadge(message.payload || {});
        return false;

      case "PEER_STATUS":
        runtimeState.peer = normalizePeer(message.peer);
        renderStudentTargets();
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

    if (root && !root.querySelector(".sparvi-tool-bar")) {
      root.remove();
      root = null;
    }

    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.setAttribute("aria-hidden", "true");
      root.innerHTML = [
        '<div class="sparvi-teaching-layer"></div>',
        '<div class="sparvi-instructor-stage" data-visible="false" data-active="false">',
        '  <div class="sparvi-target-bar" data-visible="false"></div>',
        '  <div class="sparvi-tool-bar" data-visible="false">',
        '    <button class="sparvi-tool-button" type="button" data-tool="pointer" title="Pointer">Ptr</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="laser" title="Laser pointer">Laser</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="arrow" title="Draw arrow">Arrow</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="circle" title="Draw circle">Circle</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="underline" title="Draw underline">Line</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="highlight" title="Highlight element">HL</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="freeze" title="Freeze marker">Pin</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool="hotspot" title="Guided hotspot">Step</button>',
        '    <button class="sparvi-tool-button" type="button" data-tool-action="clear" title="Clear teaching marks">Clear</button>',
        '  </div>',
        '  <div class="sparvi-stage-title">Live Pointer Area</div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-tl" data-resize="nw"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-tr" data-resize="ne"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-bl" data-resize="sw"></div>',
        '  <div class="sparvi-stage-corner sparvi-stage-corner-br" data-resize="se"></div>',
        '  <div class="sparvi-stage-edge sparvi-stage-edge-top" data-resize="n"></div>',
        '  <div class="sparvi-stage-edge sparvi-stage-edge-right" data-resize="e"></div>',
        '  <div class="sparvi-stage-edge sparvi-stage-edge-bottom" data-resize="s"></div>',
        '  <div class="sparvi-stage-edge sparvi-stage-edge-left" data-resize="w"></div>',
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
    elements.teachingLayer = root.querySelector(".sparvi-teaching-layer");
    elements.stage = root.querySelector(".sparvi-instructor-stage");
    elements.targetBar = root.querySelector(".sparvi-target-bar");
    elements.toolBar = root.querySelector(".sparvi-tool-bar");
    elements.pointer = root.querySelector(".sparvi-pointer");
    elements.badge = root.querySelector(".sparvi-page-badge");
  }

  function installInputListeners() {
    document.addEventListener("mousemove", handleMouseMove, { capture: true, passive: true });
    document.addEventListener("click", handleClick, { capture: true, passive: true });
  }

  function installStageInteractionListeners() {
    if (stageListenersInstalled) {
      return;
    }

    stageListenersInstalled = true;
    elements.stage.addEventListener("pointerdown", handleStagePointerDown, { capture: true });
    elements.targetBar.addEventListener("pointerdown", handleTargetSelectionPointerDown, { capture: true });
    elements.toolBar.addEventListener("pointerdown", handleToolBarPointerDown, { capture: true });
    document.addEventListener("pointermove", handleStagePointerMove, { capture: true });
    document.addEventListener("pointerup", handleStagePointerUp, { capture: true });
    document.addEventListener("pointercancel", handleStagePointerUp, { capture: true });
    window.addEventListener("resize", keepStageInsideViewport);
  }

  function handleMouseMove(event) {
    if (!canSendPointer() || stageInteraction) {
      return;
    }

    if (isOverlayControlTarget(event.target)) {
      return;
    }

    const stagePoint = getInstructorStagePoint(event);
    updateInstructorStageActive(Boolean(stagePoint));

    if (!stagePoint) {
      return;
    }

    if (currentToolMode === "laser") {
      sendLaserPoint(stagePoint);
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

    if (isOverlayControlTarget(event.target)) {
      return;
    }

    if (suppressNextStageClick) {
      clearStageClickSuppression();
      return;
    }

    const stagePoint = getInstructorStagePoint(event);
    updateInstructorStageActive(Boolean(stagePoint));

    if (!stagePoint) {
      return;
    }

    if (currentToolMode === "highlight") {
      sendTeachingToolEvent({
        kind: "highlight_element",
        xRatio: stagePoint.xRatio,
        yRatio: stagePoint.yRatio
      });
      return;
    }

    if (currentToolMode === "freeze") {
      sendTeachingToolEvent({
        kind: "freeze_marker",
        xRatio: stagePoint.xRatio,
        yRatio: stagePoint.yRatio
      });
      return;
    }

    if (currentToolMode === "hotspot") {
      sendTeachingToolEvent({
        kind: "guided_hotspot",
        xRatio: stagePoint.xRatio,
        yRatio: stagePoint.yRatio,
        stepNumber: hotspotStepNumber
      });
      hotspotStepNumber += 1;
      return;
    }

    if (currentToolMode === "pointer" || currentToolMode === "laser") {
      sendToWorker({
        type: "CLICK_PULSE",
        xRatio: stagePoint.xRatio,
        yRatio: stagePoint.yRatio,
        currentUrl: window.location.href
      });
    }
  }

  function renderRemoteCursor(payload) {
    if (runtimeState.role !== "student") {
      return;
    }

    if (!isThisStudentTargeted(payload.targetClientId)) {
      hidePointer();
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

  function handleStagePointerDown(event) {
    if (!canSendPointer() || event.button !== 0) {
      return;
    }

    if (isOverlayControlTarget(event.target)) {
      return;
    }

    ensureOverlay();
    const rect = elements.stage.getBoundingClientRect();
    const resizeMode = event.target && event.target.dataset ? event.target.dataset.resize || "" : "";
    const isTitleDrag = event.target && event.target.closest
      ? Boolean(event.target.closest(".sparvi-stage-title"))
      : false;

    if (!resizeMode && DRAW_TOOL_MODES.has(currentToolMode)) {
      const stagePoint = getInstructorStagePoint(event);
      if (stagePoint) {
        startDrawToolInteraction(event, stagePoint);
        event.preventDefault();
        event.stopPropagation();
      }
      return;
    }

    if (!resizeMode && currentToolMode !== "pointer" && !isTitleDrag) {
      return;
    }

    stageInteraction = {
      mode: resizeMode ? "resize" : "drag",
      resizeMode,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startLeft: rect.left,
      startTop: rect.top,
      startWidth: rect.width,
      startHeight: rect.height,
      moved: false
    };

    elements.stage.dataset.moving = "true";

    try {
      elements.stage.setPointerCapture(event.pointerId);
    } catch (error) {
      // Some pages or browsers may not allow capture here; document listeners still handle movement.
    }
  }

  function handleStagePointerMove(event) {
    if (toolInteraction && event.pointerId === toolInteraction.pointerId) {
      handleToolPointerMove(event);
      return;
    }

    if (!stageInteraction || event.pointerId !== stageInteraction.pointerId) {
      return;
    }

    const dx = event.clientX - stageInteraction.startX;
    const dy = event.clientY - stageInteraction.startY;
    const movedEnough = Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX;

    if (!stageInteraction.moved && !movedEnough) {
      return;
    }

    stageInteraction.moved = true;
    suppressStageClickBriefly();
    event.preventDefault();
    event.stopPropagation();

    const nextLayout = stageInteraction.mode === "resize"
      ? getResizedStageLayout(stageInteraction, dx, dy)
      : getDraggedStageLayout(stageInteraction, dx, dy);

    applyStageLayout(nextLayout);
  }

  function handleStagePointerUp(event) {
    if (toolInteraction && event.pointerId === toolInteraction.pointerId) {
      finishToolInteraction(event);
      return;
    }

    if (!stageInteraction || event.pointerId !== stageInteraction.pointerId) {
      return;
    }

    const moved = stageInteraction.moved;

    try {
      elements.stage.releasePointerCapture(stageInteraction.pointerId);
    } catch (error) {
      // Capture may already be released by the browser.
    }

    stageInteraction = null;
    elements.stage.dataset.moving = "false";

    if (moved) {
      suppressStageClickBriefly();
      saveStageLayout();
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function startDrawToolInteraction(event, stagePoint) {
    toolInteraction = {
      pointerId: event.pointerId,
      toolMode: currentToolMode,
      startX: event.clientX,
      startY: event.clientY,
      startPoint: stagePoint,
      endPoint: stagePoint,
      moved: false
    };

    try {
      elements.stage.setPointerCapture(event.pointerId);
    } catch (error) {
      // Document-level listeners still handle the drag if capture is unavailable.
    }
  }

  function handleToolPointerMove(event) {
    const stagePoint = getInstructorStagePoint(event);
    if (stagePoint) {
      toolInteraction.endPoint = stagePoint;
    }

    const dx = event.clientX - toolInteraction.startX;
    const dy = event.clientY - toolInteraction.startY;
    if (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX) {
      toolInteraction.moved = true;
      suppressStageClickBriefly();
    }

    event.preventDefault();
    event.stopPropagation();
  }

  function finishToolInteraction(event) {
    const interaction = toolInteraction;
    toolInteraction = null;

    try {
      elements.stage.releasePointerCapture(interaction.pointerId);
    } catch (error) {
      // Capture may already be released by the browser.
    }

    if (!interaction.moved) {
      return;
    }

    const kindByTool = {
      arrow: "draw_arrow",
      circle: "draw_circle",
      underline: "draw_underline"
    };

    sendTeachingToolEvent({
      kind: kindByTool[interaction.toolMode],
      x1Ratio: interaction.startPoint.xRatio,
      y1Ratio: interaction.startPoint.yRatio,
      x2Ratio: interaction.endPoint.xRatio,
      y2Ratio: interaction.endPoint.yRatio
    });

    suppressStageClickBriefly();
    event.preventDefault();
    event.stopPropagation();
  }

  function suppressStageClickBriefly() {
    suppressNextStageClick = true;

    if (suppressStageClickTimer) {
      clearTimeout(suppressStageClickTimer);
    }

    suppressStageClickTimer = setTimeout(() => {
      suppressNextStageClick = false;
      suppressStageClickTimer = null;
    }, 250);
  }

  function clearStageClickSuppression() {
    suppressNextStageClick = false;

    if (suppressStageClickTimer) {
      clearTimeout(suppressStageClickTimer);
      suppressStageClickTimer = null;
    }
  }

  function getDraggedStageLayout(interaction, dx, dy) {
    return constrainStageLayout({
      left: interaction.startLeft + dx,
      top: interaction.startTop + dy,
      width: interaction.startWidth,
      height: interaction.startHeight
    });
  }

  function getResizedStageLayout(interaction, dx, dy) {
    const limits = getStageLimits();
    const mode = interaction.resizeMode;
    const right = interaction.startLeft + interaction.startWidth;
    const bottom = interaction.startTop + interaction.startHeight;

    let left = interaction.startLeft;
    let top = interaction.startTop;
    let width = interaction.startWidth;
    let height = interaction.startHeight;

    if (mode.includes("e")) {
      width = clampRange(interaction.startWidth + dx, limits.minWidth, limits.maxWidth);
      width = Math.min(width, Math.max(limits.minWidth, getStageMaxRight() - left));
    }

    if (mode.includes("s")) {
      height = clampRange(interaction.startHeight + dy, limits.minHeight, limits.maxHeight);
      height = Math.min(height, Math.max(limits.minHeight, window.innerHeight - STAGE_MARGIN - top));
    }

    if (mode.includes("w")) {
      const maxLeft = right - limits.minWidth;
      left = clampRange(interaction.startLeft + dx, STAGE_MARGIN, maxLeft);
      width = right - left;

      if (width > limits.maxWidth) {
        width = limits.maxWidth;
        left = right - width;
      }
    }

    if (mode.includes("n")) {
      const maxTop = bottom - limits.minHeight;
      top = clampRange(interaction.startTop + dy, STAGE_MARGIN, maxTop);
      height = bottom - top;

      if (height > limits.maxHeight) {
        height = limits.maxHeight;
        top = bottom - height;
      }
    }

    return constrainStageLayout({ left, top, width, height });
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

  function handleTargetSelectionPointerDown(event) {
    const button = event.target && event.target.closest
      ? event.target.closest(".sparvi-target-button")
      : null;

    if (!button || !canSendPointer() || event.button !== 0) {
      return;
    }

    const targetClientId = normalizePointerTarget(button.dataset.targetClientId);
    runtimeState.pointerTargetClientId = targetClientId;
    renderStudentTargets();

    sendToWorker({
      type: "SET_POINTER_TARGET",
      targetClientId
    });

    event.preventDefault();
    event.stopPropagation();
  }

  function applyPointerTargetUpdate(payload) {
    runtimeState.pointerTargetClientId = normalizePointerTarget(payload.targetClientId);
    renderStudentTargets();

    if (runtimeState.role === "student" && !isThisStudentTargeted(runtimeState.pointerTargetClientId)) {
      hidePointer();
    }
  }

  function renderStudentTargets() {
    ensureOverlay();

    if (!elements.targetBar) {
      return;
    }

    const visible = canSendPointer();
    elements.targetBar.dataset.visible = visible ? "true" : "false";
    elements.targetBar.replaceChildren();

    if (!visible) {
      return;
    }

    elements.targetBar.appendChild(createTargetButton({
      clientId: "all",
      displayName: "All students",
      label: "All",
      avatarIndex: 8
    }));

    const students = runtimeState.peer.students || [];
    students.forEach((student, index) => {
      elements.targetBar.appendChild(createTargetButton({
        clientId: student.clientId,
        displayName: student.displayName || `Student ${index + 1}`,
        label: String(index + 1),
        avatarIndex: student.avatarIndex
      }));
    });
  }

  function createTargetButton(target) {
    const button = document.createElement("button");
    const selected = runtimeState.pointerTargetClientId === target.clientId;

    button.type = "button";
    button.className = "sparvi-target-button";
    button.dataset.targetClientId = target.clientId;
    button.dataset.avatar = String(Number(target.avatarIndex || 0) % 9);
    button.dataset.selected = selected ? "true" : "false";
    button.title = target.clientId === "all"
      ? "Show pointer to all students"
      : `Show pointer to ${target.displayName}`;

    const avatar = document.createElement("span");
    avatar.className = "sparvi-target-avatar";
    avatar.textContent = target.label;

    button.appendChild(avatar);
    return button;
  }

  function handleToolBarPointerDown(event) {
    const button = event.target && event.target.closest
      ? event.target.closest(".sparvi-tool-button")
      : null;

    if (!button || !canSendPointer() || event.button !== 0) {
      return;
    }

    const action = button.dataset.toolAction || "";
    if (action === "clear") {
      hotspotStepNumber = 1;
      sendTeachingToolEvent({ kind: "clear_tools" });
      clearTeachingArtifacts();
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    currentToolMode = button.dataset.tool || "pointer";
    renderToolBar();
    event.preventDefault();
    event.stopPropagation();
  }

  function renderToolBar() {
    ensureOverlay();

    if (!elements.toolBar) {
      return;
    }

    const visible = canSendPointer();
    elements.toolBar.dataset.visible = visible ? "true" : "false";

    for (const button of elements.toolBar.querySelectorAll(".sparvi-tool-button")) {
      const tool = button.dataset.tool || "";
      button.dataset.selected = tool && tool === currentToolMode ? "true" : "false";
    }
  }

  function sendLaserPoint(stagePoint) {
    const now = Date.now();
    if (now - lastToolSentAt < TOOL_SEND_INTERVAL_MS) {
      return;
    }

    lastToolSentAt = now;
    sendTeachingToolEvent({
      kind: "laser_point",
      xRatio: stagePoint.xRatio,
      yRatio: stagePoint.yRatio
    });
  }

  function sendTeachingToolEvent(event) {
    if (!event || !event.kind) {
      return;
    }

    const eventForSend = {
      id: createEventId(),
      ...event,
      currentUrl: window.location.href,
      targetClientId: runtimeState.pointerTargetClientId
    };

    sendToWorker({
      type: "TEACHING_TOOL_EVENT",
      event: eventForSend
    }, (response) => {
      if (!response || !response.ok) {
        console.warn("[Sparvi] Teaching tool event was not accepted:", response && response.error);
        return;
      }

      renderLocalTeachingToolPreview(eventForSend);
    });
  }

  function renderRemoteToolEvent(event) {
    if (runtimeState.role !== "student") {
      return;
    }

    if (!isThisStudentTargeted(event.targetClientId)) {
      return;
    }

    ensureOverlay();
    updateMismatchBadge({ instructorUrl: event.currentUrl });
    renderTeachingToolEvent(event);
  }

  function renderLocalTeachingToolPreview(event) {
    if (runtimeState.role !== "instructor") {
      return;
    }

    renderTeachingToolEvent(event);
  }

  function renderTeachingToolEvent(event) {
    switch (event.kind) {
      case "laser_point":
        renderLaserPoint(event);
        break;

      case "draw_arrow":
      case "draw_circle":
      case "draw_underline":
        renderDrawingArtifact(event);
        break;

      case "highlight_element":
        renderElementHighlight(event);
        break;

      case "freeze_marker":
        renderFreezeMarker(event);
        break;

      case "guided_hotspot":
        renderGuidedHotspot(event);
        break;

      case "clear_tools":
        clearTeachingArtifacts();
        break;

      default:
        break;
    }
  }

  function renderLaserPoint(event) {
    const point = ratiosToViewport(event.xRatio, event.yRatio);
    if (!point) {
      return;
    }

    const dot = document.createElement("div");
    dot.className = "sparvi-laser-dot";
    dot.style.left = `${point.x}px`;
    dot.style.top = `${point.y}px`;
    elements.teachingLayer.appendChild(dot);

    dot.addEventListener("animationend", () => dot.remove(), { once: true });
    setTimeout(() => dot.remove(), 1000);
  }

  function renderDrawingArtifact(event) {
    if (event.kind === "draw_circle") {
      renderCircleArtifact(event);
      return;
    }

    const svg = createDrawingSvg();
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    const y1 = event.kind === "draw_underline" ? event.y2Ratio : event.y1Ratio;
    const y2 = event.y2Ratio;
    line.setAttribute("x1", String(event.x1Ratio * 1000));
    line.setAttribute("y1", String(y1 * 1000));
    line.setAttribute("x2", String(event.x2Ratio * 1000));
    line.setAttribute("y2", String(y2 * 1000));
    line.setAttribute("class", event.kind === "draw_arrow" ? "sparvi-svg-arrow" : "sparvi-svg-underline");

    if (event.kind === "draw_arrow") {
      const markerId = `sparvi-arrowhead-${event.id || Date.now()}`;
      const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      const markerPath = document.createElementNS("http://www.w3.org/2000/svg", "path");

      marker.setAttribute("id", markerId);
      marker.setAttribute("markerWidth", "10");
      marker.setAttribute("markerHeight", "10");
      marker.setAttribute("refX", "8");
      marker.setAttribute("refY", "5");
      marker.setAttribute("orient", "auto");
      markerPath.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      markerPath.setAttribute("class", "sparvi-svg-arrow-head");
      marker.appendChild(markerPath);
      defs.appendChild(marker);
      svg.appendChild(defs);
      line.setAttribute("marker-end", `url(#${markerId})`);
    }

    svg.appendChild(line);
    elements.teachingLayer.appendChild(svg);
  }

  function renderCircleArtifact(event) {
    const left = Math.min(event.x1Ratio, event.x2Ratio);
    const top = Math.min(event.y1Ratio, event.y2Ratio);
    const width = Math.abs(event.x2Ratio - event.x1Ratio);
    const height = Math.abs(event.y2Ratio - event.y1Ratio);

    if (width < 0.01 || height < 0.01) {
      return;
    }

    const circle = document.createElement("div");
    circle.className = "sparvi-teaching-artifact sparvi-drawn-circle";
    circle.style.left = `${left * 100}%`;
    circle.style.top = `${top * 100}%`;
    circle.style.width = `${width * 100}%`;
    circle.style.height = `${height * 100}%`;
    elements.teachingLayer.appendChild(circle);
  }

  function createDrawingSvg() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "sparvi-teaching-artifact sparvi-drawing-svg");
    svg.setAttribute("viewBox", "0 0 1000 1000");
    svg.setAttribute("preserveAspectRatio", "none");
    return svg;
  }

  function renderElementHighlight(event) {
    const point = ratiosToViewport(event.xRatio, event.yRatio);
    if (!point) {
      return;
    }

    const target = document.elementFromPoint(point.x, point.y);
    if (!target || target === document.documentElement || target === document.body || elements.root.contains(target)) {
      return;
    }

    const rect = target.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }

    const highlight = document.createElement("div");
    highlight.className = "sparvi-teaching-artifact sparvi-element-highlight";
    highlight.style.left = `${rect.left}px`;
    highlight.style.top = `${rect.top}px`;
    highlight.style.width = `${rect.width}px`;
    highlight.style.height = `${rect.height}px`;
    elements.teachingLayer.appendChild(highlight);

    setTimeout(() => highlight.remove(), 3500);
  }

  function renderFreezeMarker(event) {
    const point = ratiosToViewport(event.xRatio, event.yRatio);
    if (!point) {
      return;
    }

    const marker = document.createElement("div");
    marker.className = "sparvi-teaching-artifact sparvi-freeze-marker";
    marker.style.left = `${point.x}px`;
    marker.style.top = `${point.y}px`;
    marker.textContent = "Look here";
    elements.teachingLayer.appendChild(marker);
  }

  function renderGuidedHotspot(event) {
    const point = ratiosToViewport(event.xRatio, event.yRatio);
    if (!point) {
      return;
    }

    const hotspot = document.createElement("div");
    hotspot.className = "sparvi-teaching-artifact sparvi-guided-hotspot";
    hotspot.style.left = `${point.x}px`;
    hotspot.style.top = `${point.y}px`;
    hotspot.textContent = String(event.stepNumber || 1);
    elements.teachingLayer.appendChild(hotspot);
  }

  function clearTeachingArtifacts() {
    ensureOverlay();
    elements.teachingLayer
      .querySelectorAll(".sparvi-teaching-artifact, .sparvi-laser-dot")
      .forEach((node) => node.remove());
  }

  function renderClickPulse(payload) {
    if (runtimeState.role !== "student") {
      return;
    }

    if (!isThisStudentTargeted(payload.targetClientId)) {
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
    runtimeState.clientId = nextState.clientId || runtimeState.clientId;
    runtimeState.role = nextState.role || runtimeState.role;
    runtimeState.connected = Boolean(nextState.connected);
    runtimeState.pointerEnabled = Boolean(nextState.pointerEnabled);
    runtimeState.pointerTargetClientId = normalizePointerTarget(nextState.pointerTargetClientId);
    runtimeState.peer = normalizePeer(nextState.peer || runtimeState.peer);
    updateInstructorStageVisibility();
    renderStudentTargets();
    renderToolBar();

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

  function isThisStudentTargeted(targetClientId) {
    const normalizedTarget = normalizePointerTarget(targetClientId);
    return normalizedTarget === "all" || normalizedTarget === runtimeState.clientId;
  }

  function normalizePointerTarget(value) {
    if (value === "all") {
      return "all";
    }

    if (typeof value !== "string") {
      return "all";
    }

    const trimmed = value.trim();
    return trimmed ? trimmed.slice(0, 128) : "all";
  }

  function normalizePeer(peer) {
    const students = Array.isArray(peer && peer.students)
      ? peer.students
      : [];

    return {
      ...(peer || {}),
      students: students
        .filter((student) => student && typeof student.clientId === "string")
        .map((student, index) => ({
          clientId: student.clientId,
          displayName: String(student.displayName || `Student ${index + 1}`).slice(0, 40),
          avatarIndex: Number.isFinite(Number(student.avatarIndex)) ? Number(student.avatarIndex) : index,
          currentUrl: typeof student.currentUrl === "string" ? student.currentUrl : ""
        }))
    };
  }

  function ratiosToViewport(xRatio, yRatio) {
    const x = clampRatio(xRatio);
    const y = clampRatio(yRatio);
    if (x === null || y === null) {
      return null;
    }

    return {
      x: x * window.innerWidth,
      y: y * window.innerHeight
    };
  }

  function createEventId() {
    if (globalThis.crypto && globalThis.crypto.randomUUID) {
      return globalThis.crypto.randomUUID();
    }

    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function isOverlayControlTarget(target) {
    if (!target || !target.closest) {
      return false;
    }

    return Boolean(target.closest(".sparvi-target-bar, .sparvi-tool-bar"));
  }

  function initializeStageLayout() {
    if (stageState.initialized) {
      return;
    }

    stageState.initialized = true;
    applyStageLayout(getDefaultStageLayout());

    chrome.storage.local.get(STAGE_STORAGE_KEY, (stored) => {
      void chrome.runtime.lastError;
      const savedLayout = stored && stored[STAGE_STORAGE_KEY];
      if (isValidStageLayout(savedLayout)) {
        applyStageLayout(savedLayout);
      }
    });
  }

  function getDefaultStageLayout() {
    const limits = getStageLimits();
    const width = clampRange(760, limits.minWidth, limits.maxWidth);
    const height = clampRange(460, limits.minHeight, limits.maxHeight);

    return {
      left: Math.round((window.innerWidth - width) / 2),
      top: Math.round((window.innerHeight - height) / 2),
      width,
      height
    };
  }

  function keepStageInsideViewport() {
    if (!stageState.initialized) {
      return;
    }

    applyStageLayout(stageState);
    saveStageLayout();
  }

  function applyStageLayout(layout) {
    ensureOverlay();

    const constrained = constrainStageLayout(layout);
    stageState.left = constrained.left;
    stageState.top = constrained.top;
    stageState.width = constrained.width;
    stageState.height = constrained.height;

    elements.stage.style.setProperty("left", `${Math.round(stageState.left)}px`, "important");
    elements.stage.style.setProperty("top", `${Math.round(stageState.top)}px`, "important");
    elements.stage.style.setProperty("width", `${Math.round(stageState.width)}px`, "important");
    elements.stage.style.setProperty("height", `${Math.round(stageState.height)}px`, "important");
    elements.stage.style.setProperty("right", "auto", "important");
    elements.stage.style.setProperty("bottom", "auto", "important");
    elements.stage.style.setProperty("transform", "none", "important");
  }

  function constrainStageLayout(layout) {
    const limits = getStageLimits();
    const width = clampRange(finiteOr(layout.width, limits.maxWidth), limits.minWidth, limits.maxWidth);
    const height = clampRange(finiteOr(layout.height, limits.maxHeight), limits.minHeight, limits.maxHeight);
    const maxLeft = Math.max(STAGE_MARGIN, getStageMaxRight() - width);
    const maxTop = Math.max(STAGE_TOP_MARGIN, window.innerHeight - height - STAGE_MARGIN);

    return {
      left: clampRange(finiteOr(layout.left, STAGE_MARGIN), STAGE_MARGIN, maxLeft),
      top: clampRange(finiteOr(layout.top, STAGE_TOP_MARGIN), STAGE_TOP_MARGIN, maxTop),
      width,
      height
    };
  }

  function getStageLimits() {
    const maxWidth = Math.max(160, window.innerWidth - STAGE_MARGIN - getStageRightReserve() - STAGE_MARGIN);
    const maxHeight = Math.max(120, window.innerHeight - STAGE_TOP_MARGIN - STAGE_MARGIN);

    return {
      minWidth: Math.min(MIN_STAGE_WIDTH, maxWidth),
      minHeight: Math.min(MIN_STAGE_HEIGHT, maxHeight),
      maxWidth,
      maxHeight
    };
  }

  function saveStageLayout() {
    const layout = {
      left: Math.round(stageState.left),
      top: Math.round(stageState.top),
      width: Math.round(stageState.width),
      height: Math.round(stageState.height)
    };

    chrome.storage.local.set({ [STAGE_STORAGE_KEY]: layout }, () => {
      void chrome.runtime.lastError;
    });
  }

  function isValidStageLayout(layout) {
    return Boolean(
      layout &&
      Number.isFinite(Number(layout.left)) &&
      Number.isFinite(Number(layout.top)) &&
      Number.isFinite(Number(layout.width)) &&
      Number.isFinite(Number(layout.height))
    );
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
    if (stageState.initialized) {
      applyStageLayout(stageState);
    }
    renderToolBar();
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

  function clampRange(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function finiteOr(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function getStageRightReserve() {
    return canSendPointer() ? STAGE_TOOLBAR_WIDTH + STAGE_TOOLBAR_GAP : 0;
  }

  function getStageMaxRight() {
    return window.innerWidth - STAGE_MARGIN - getStageRightReserve();
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
