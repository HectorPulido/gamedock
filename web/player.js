const sid = location.pathname.split("/")[2];
const frame = document.querySelector("#desktop-frame");
const stage = document.querySelector("#desktop-stage");
const notice = document.querySelector("#player-notice");
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
  const scale = Math.min(
    1,
    stage.clientWidth / width,
    stage.clientHeight / height,
  );
  frame.style.transform = `translate(-50%, -50%) scale(${scale})`;
}
new ResizeObserver(fit).observe(stage);
function input(event) {
  if (!event.isTrusted) return;
  if (pending || Date.now() - lastSent < 5000) return;
  pending = true;
  api("/instances/" + sid + "/activity", "POST", {})
    .then(() => {
      lastSent = Date.now();
      notice.textContent = "";
    })
    .catch((error) => {
      notice.textContent = error.message;
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
      notice.textContent = "Starting your desktop…";
    else notice.textContent = "";
  } catch {
    notice.textContent =
      "The desktop connection could not be opened. Return to the library and try again.";
  }
});
function historyKey(uid) {
  return "gamedock-recent-" + uid;
}
async function refresh() {
  const catalog = await api("/catalog");
  if (!catalog.user) {
    location.replace("/");
    return;
  }
  settings = catalog.settings;
  document.querySelector("#brand").textContent = settings.name;
  const list = (await api("/instances")).filter(
    (i) => i.uid === catalog.user.id && i.status === "running",
  );
  current = await api("/instances/" + sid);
  if (current.status !== "running") {
    notice.textContent =
      "This instance has stopped. Return to the library to launch it again.";
    frame.removeAttribute("src");
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
      notice.textContent =
        "This instance will stop soon due to inactivity. Move the mouse or press a key to keep playing.";
  }
}
document.querySelector("#stop-instance").onclick = async () => {
  if (!confirm("Stop this instance? Save your game before continuing.")) return;
  try {
    await api("/instances/" + sid, "DELETE", {});
    location.assign("/");
  } catch (error) {
    notice.textContent = error.message;
  }
};
refresh().catch((error) => {
  notice.textContent = error.message;
});
setInterval(
  () =>
    refresh().catch((error) => {
      notice.textContent = error.message;
    }),
  15000,
);
