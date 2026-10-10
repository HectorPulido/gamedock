const sid = location.pathname.split("/")[2];
const frame = document.querySelector("#desktop-frame");
const stage = document.querySelector("#desktop-stage");
const notify = (text, options = {}) =>
  GameDockNotifications.show(text, options);
let stopped = false;
function stoppedDesktop() {
  if (stopped) return;
  stopped = true;
  frame.hidden = true;
  frame.removeAttribute("src");
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
    document.querySelector("#viewer-scale").value === "original"
      ? Math.min(1, available)
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
  try {
    const doc = frame.contentDocument;
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
  if (!confirm("Stop this instance? Save your game before continuing.")) return;
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

const scaleControl = document.querySelector("#viewer-scale");
try {
  scaleControl.value = localStorage.getItem("gamedock-viewer-scale") || "fit";
} catch {}
if (!["fit", "original"].includes(scaleControl.value))
  scaleControl.value = "fit";
scaleControl.addEventListener("change", () => {
  try {
    localStorage.setItem("gamedock-viewer-scale", scaleControl.value);
  } catch {}
  fit();
});
const fullscreenButton = document.querySelector("#fullscreen");
fullscreenButton.hidden = !document.fullscreenEnabled;
fullscreenButton.onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.body.requestFullscreen();
  } catch {
    notify(
      "Fullscreen could not be opened. Try again or use your browser's fullscreen mode.",
      { kind: "error" },
    );
  }
};
document.addEventListener("fullscreenchange", () => {
  const active = !!document.fullscreenElement;
  fullscreenButton.textContent = active ? "Exit fullscreen" : "Fullscreen";
  fullscreenButton.setAttribute("aria-pressed", String(active));
  requestAnimationFrame(fit);
});
