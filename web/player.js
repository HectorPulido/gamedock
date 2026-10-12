const sid = location.pathname.split("/")[2];
const frame = document.querySelector("#desktop-frame");
const stage = document.querySelector("#desktop-stage");
const notify = (text, options = {}) =>
  GameDockNotifications.show(text, options);
const viewer = GameDockViewer.create(frame);
const controller = GameDockController.create(frame, sid);
const scaleControl = document.querySelector("#viewer-scale");
const filterControl = document.querySelector("#canvas-filter");
const diagnostics = document.querySelector("#streaming-diagnostics");
frame.addEventListener("fsr-status", (event) => {
  document.querySelector("#scaler-status").textContent = event.detail.reason;
});
let diagnosticTimer;
let viewerSettings = {};
function preference(key) {
  try {
    return localStorage.getItem("gamedock-" + key);
  } catch {
    return null;
  }
}
function savePreference(key, value) {
  try {
    localStorage.setItem("gamedock-" + key, value);
  } catch {}
}
const settingsDialog = document.querySelector("#player-settings");
document.querySelector("#player-settings-toggle").onclick = () =>
  settingsDialog.showModal();
document.querySelector("#player-settings-close").onclick = () =>
  settingsDialog.close();
settingsDialog.addEventListener("click", (event) => {
  if (event.target !== settingsDialog) return;
  const rect = settingsDialog.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
    settingsDialog.close();
});
settingsDialog.addEventListener("close", returnFocus);
function returnFocus() {
  if (settingsDialog.open) return;
  if (viewerSettings.restore_focus !== false)
    requestAnimationFrame(() => viewer.focus());
}
function applyViewerSettings() {
  viewerSettings = settings.streaming || {};
  scaleControl.value =
    preference("viewer-scale") || viewerSettings.viewer_scale || "fit";
  filterControl.value =
    preference("canvas-filter") || viewerSettings.canvas_filter || "fsr";
  if (!["fit", "original", "integer"].includes(scaleControl.value))
    scaleControl.value = "fit";
  if (!["fsr", "smooth", "crisp"].includes(filterControl.value))
    filterControl.value = "fsr";
  viewer.filter(filterControl.value);
  document.querySelector("#diagnostics-toggle").hidden =
    viewerSettings.diagnostics_enabled === false;
  if (viewerSettings.diagnostics_enabled === false && !diagnostics.hidden)
    toggleDiagnostics(false);
}
let stopped = false;
function stoppedDesktop() {
  if (stopped) return;
  stopped = true;
  frame.hidden = true;
  frame.removeAttribute("src");
  clearInterval(diagnosticTimer);
  controller.dispose();
  viewer.dispose();
  const empty = document.createElement("section");
  empty.className = "desktop-stopped";
  const title = document.createElement("h1");
  title.textContent = "Instance stopped";
  const detail = document.createElement("p");
  detail.textContent = "Return to the library to launch a new instance.";
  const link = document.createElement("a");
  link.className = "button";
  link.href = "/";
  link.textContent = "Back to library";
  empty.append(title, detail, link);
  stage.append(empty);
  document.querySelector("#stop-instance").disabled = true;
  GameDockNotifications.show("");
  notify("This instance has stopped.", {
    key: "stopped",
    title: "Session ended",
  });
}
let current,
  settings,
  lastSent = 0,
  pending = false;
async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw Error(result.error || "The operation could not be completed");
  return result;
}
function fit() {
  if (!current) return;
  const [width, height] = current.resolution.split("x").map(Number);
  frame.style.width = width + "px";
  frame.style.height = height + "px";
  const available = Math.min(
    stage.clientWidth / width,
    stage.clientHeight / height,
  );
  const scale =
    scaleControl.value === "original"
      ? Math.min(1, available)
      : scaleControl.value === "integer" && available >= 1
        ? Math.max(1, Math.floor(available))
        : available;
  frame.style.transform = `translate(-50%, -50%) scale(${scale})`;
}
new ResizeObserver(fit).observe(stage);
function input(event) {
  if (!event.isTrusted || stopped) return;
  if (pending || Date.now() - lastSent < 5000) return;
  pending = true;
  api("/instances/" + sid + "/activity", "POST", {})
    .then(() => {
      lastSent = Date.now();
    })
    .catch((error) => {
      notify(error.message, {
        kind: "error",
        key: "activity-" + error.message,
      });
    })
    .finally(() => {
      pending = false;
    });
}
for (const type of [
  "pointerdown",
  "pointermove",
  "keydown",
  "wheel",
  "touchstart",
])
  document.addEventListener(type, input, { capture: true, passive: true });
frame.addEventListener("load", () => {
  if (stopped || !frame.getAttribute("src")) return;
  viewer.dispose();
  viewer.filter(filterControl.value);
  try {
    const doc = frame.contentDocument;
    // Xpra's own fullscreen resizes its viewport/canvas while the X display
    // stays fixed. Route its toolbar and global shortcut through the outer
    // player so the browser continues mapping input in source coordinates.
    frame.contentWindow.toggle_fullscreen = toggleFullscreen;
    doc.addEventListener(
      "click",
      (event) => {
        if (!event.target.closest?.("#fullscreen_button")) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        toggleFullscreen();
      },
      true,
    );
    for (const type of [
      "pointerdown",
      "pointermove",
      "keydown",
      "wheel",
      "touchstart",
    ])
      doc.addEventListener(type, input, { capture: true, passive: true });
    if (
      !doc.querySelector("canvas") &&
      doc.body?.textContent.includes("Starting your desktop")
    )
      notify("Starting your desktop…", {
        key: "starting",
        title: "Connecting",
      });
  } catch {
    notify(
      "The desktop connection could not be opened. Return to the library and try again.",
      { kind: "error", key: "connection" },
    );
  }
});
function historyKey(uid) {
  return "gamedock-recent-" + uid;
}
async function refresh() {
  if (stopped) return;
  const catalog = await api("/catalog");
  if (!catalog.user) {
    location.replace("/");
    return;
  }
  settings = catalog.settings;
  GameDockTheme.apply(settings);
  applyViewerSettings();
  document.querySelector("#brand").textContent = settings.name;
  const list = (await api("/instances")).filter(
    (i) => i.uid === catalog.user.id && i.status === "running",
  );
  current = await api("/instances/" + sid);
  if (current.status !== "running") {
    stoppedDesktop();
    return;
  }
  const tabs = document.querySelector("#session-tabs");
  tabs.replaceChildren();
  if (!list.some((i) => i.id === sid)) list.unshift(current);
  for (const i of list) {
    const a = document.createElement("a");
    a.className = "button secondary";
    a.href = "/play/" + i.id;
    const name = catalog.games.find((g) => g.id === i.game)?.name || i.game;
    a.textContent =
      name +
      (list.filter((item) => item.game === i.game).length > 1
        ? " #" + i.id.slice(0, 4)
        : "");
    if (i.id === sid) a.setAttribute("aria-current", "page");
    tabs.append(a);
  }
  const key = historyKey(catalog.user.id);
  let recent = [];
  try {
    recent = JSON.parse(sessionStorage.getItem(key) || "[]");
  } catch {}
  if (!Array.isArray(recent)) recent = [];
  const previous = recent.find(
    (id) => id !== sid && list.some((i) => i.id === id),
  );
  const button = document.querySelector("#previous");
  button.disabled = !previous;
  button.onclick = () => location.assign("/play/" + previous);
  sessionStorage.setItem(
    key,
    JSON.stringify([sid, ...recent.filter((id) => id !== sid)].slice(0, 100)),
  );
  const src = "/desktop/" + sid + "/?floating_menu=" + settings.desktop_toolbar;
  if (frame.getAttribute("src") !== src) frame.src = src;
  document.title =
    (catalog.games.find((g) => g.id === current.game)?.name || current.game) +
    " | " +
    settings.name;
  fit();
  if (settings.idle_minutes) {
    const seconds = Math.ceil(
      current.last_activity + settings.idle_minutes * 60 - Date.now() / 1000,
    );
    if (seconds <= 60)
      notify(
        "This instance will stop soon due to inactivity. Move the mouse or press a key to keep playing.",
        { key: "idle-" + current.last_activity, title: "Still playing?" },
      );
  }
}
document.querySelector("#stop-instance").onclick = async () => {
  if (!confirm("Stop this instance? Save your game before continuing.")) {
    returnFocus();
    return;
  }
  try {
    await api("/instances/" + sid, "DELETE", {});
    GameDockNotifications.remember("Instance stopped.", { kind: "success" });
    location.assign("/");
  } catch (error) {
    notify(error.message, { kind: "error" });
  }
};
refresh().catch((error) => {
  notify(error.message, { kind: "error", key: "refresh-" + error.message });
});
setInterval(
  () =>
    refresh().catch((error) => {
      notify(error.message, { kind: "error", key: "refresh-" + error.message });
    }),
  15000,
);

scaleControl.addEventListener("change", () => {
  savePreference("viewer-scale", scaleControl.value);
  fit();
  returnFocus();
});
filterControl.addEventListener("change", () => {
  savePreference("canvas-filter", filterControl.value);
  viewer.filter(filterControl.value);
  returnFocus();
});
document.querySelector("#viewer-defaults").onclick = () => {
  try {
    localStorage.removeItem("gamedock-viewer-scale");
    localStorage.removeItem("gamedock-canvas-filter");
  } catch {}
  applyViewerSettings();
  fit();
  returnFocus();
};
const metrics = [
  ["capture_fps", "Capture FPS", "fps"],
  ["capture_cycles_fps", "Capture loop", "Hz"],
  ["delivered_fps", "Delivered FPS", "fps"],
  ["decoded_fps", "Decoded FPS", "fps"],
  ["delivered_updates", "Delivered updates", "/s"],
  ["decoded_updates", "Decoded updates", "/s"],
  ["capture_ms", "Capture time", "ms"],
  ["decode_ms", "Client decode / paint time", "ms"],
  ["roundtrip_ms", "Client latency", "ms"],
  ["image_mbps", "Image payload", "Mbps"],
  ["hourly_gb", "Estimated image data", "GB/hour"],
  ["game_cpu_percent", "Game CPU", "%"],
  ["stream_cpu_percent", "Xpra / display CPU", "%"],
  ["game_rss_mb", "Game RSS (sum)", "MiB"],
  ["game_pss_mb", "Game PSS (shared pages apportioned)", "MiB"],
  ["game_processes", "Game processes", ""],
  ["container_memory_mb", "Container memory (cgroup)", "MiB"],
  ["container_cpu_percent", "Container CPU (cgroup)", "%"],
  ["stream_rss_mb", "Streaming process memory", "MiB"],
  ["codecs", "Observed codecs", ""],
  ["client_codecs", "Browser codecs", ""],
  ["h264_status", "H.264 negotiation", ""],
  ["bandwidth_budget_mbps", "Effective client bandwidth budget", "Mbps"],
  ["bandwidth_window_mbps", "Window bandwidth budget", "Mbps"],
  ["gpu_vendor", "Graphics profile", ""],
  ["gpu_renderer", "OpenGL renderer", ""],
  ["software_threads", "CPU render workers (configured)", ""],
  ["decode_errors", "Decode errors", ""],
  ["geometry", "Source → displayed", ""],
  ["canvas", "Canvas backing size", ""],
  ["scaler_mode", "Browser scaler", ""],
  ["scaler_submit", "Scaler CPU submission (not GPU time)", "ms"],
  ["scaler_output", "Client-only scaler output", ""],
];
const values = document.querySelector("#diagnostics-values");
for (const [key, label] of metrics) {
  const title = document.createElement("dt");
  title.textContent = label;
  const value = document.createElement("dd");
  value.dataset.metric = key;
  value.textContent = "—";
  values.append(title, value);
}
function sampleDiagnostics() {
  if (diagnostics.hidden || stopped || document.hidden) return;
  const sample = viewer.sample();
  sample.scaler_mode = sample.scaler?.reason || sample.scaler?.mode;
  sample.scaler_submit = sample.scaler?.submit_ms;
  sample.scaler_output = sample.scaler?.output;
  if (sample.gpu_vendor === "none") sample.gpu_vendor = "CPU / software";
  sample.hourly_gb =
    sample.image_mbps == null ? null : (sample.image_mbps * 3600) / 8 / 1000;
  const box = frame.getBoundingClientRect();
  sample.geometry = current
    ? current.resolution +
      " → " +
      Math.round(box.width) +
      "×" +
      Math.round(box.height)
    : "—";
  try {
    const canvas = frame.contentDocument.querySelector("canvas");
    sample.canvas = canvas ? canvas.width + "×" + canvas.height : "—";
  } catch {}
  const fresh =
    sample.server_age != null &&
    sample.server_age < (viewerSettings.metrics_interval || 2) * 3;
  const status = document.querySelector("#diagnostics-status");
  status.textContent = !sample.connected
    ? "Connecting to Xpra…"
    : sample.server_age == null
      ? "Waiting for server capture metrics…"
      : !fresh
        ? "Server sample is stale; waiting for a fresh response."
        : sample.enabled == null
          ? "Capture metrics unavailable in this runtime. Launch a new instance after updating its image."
          : sample.enabled === false
            ? "Capture diagnostics were disabled when this instance started."
            : "Live sample · capture target " + sample.target_hz + " Hz";
  for (const [key, , unit] of metrics) {
    const value = sample[key];
    const serverMetric =
      /^(capture|game_|stream_|gpu_|container_|bandwidth_|software_threads)/.test(
        key,
      );
    values.querySelector('[data-metric="' + key + '"]').textContent =
      value == null || (serverMetric && !fresh)
        ? "—"
        : (typeof value === "number"
            ? value.toFixed(key === "decode_errors" ? 0 : 1)
            : value) + (unit ? " " + unit : "");
  }
}
function toggleDiagnostics(open) {
  diagnostics.hidden = !open;
  document
    .querySelector("#diagnostics-toggle")
    .setAttribute("aria-expanded", String(open));
  clearInterval(diagnosticTimer);
  if (open) {
    sampleDiagnostics();
    diagnosticTimer = setInterval(
      sampleDiagnostics,
      (viewerSettings.metrics_interval || 2) * 1000,
    );
  }
}
document.querySelector("#diagnostics-toggle").onclick = () => {
  settingsDialog.close();
  toggleDiagnostics(diagnostics.hidden);
  returnFocus();
};
document.querySelector("#diagnostics-close").onclick = () => {
  toggleDiagnostics(false);
  returnFocus();
};
window.addEventListener("pagehide", () => {
  clearInterval(diagnosticTimer);
  controller.dispose();
  viewer.dispose();
});
const fullscreenButton = document.querySelector("#fullscreen");
fullscreenButton.hidden = !document.fullscreenEnabled;
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.body.requestFullscreen();
  } catch {
    notify(
      "Fullscreen could not be opened. Try again or use your browser's fullscreen mode.",
      { kind: "error" },
    );
  }
}
fullscreenButton.onclick = toggleFullscreen;
document.addEventListener("fullscreenchange", () => {
  const active = !!document.fullscreenElement;
  const label = active ? "Exit fullscreen" : "Fullscreen";
  fullscreenButton.setAttribute("aria-label", label);
  fullscreenButton.title = label;
  fullscreenButton.setAttribute("aria-pressed", String(active));
  requestAnimationFrame(fit);
  returnFocus();
});
