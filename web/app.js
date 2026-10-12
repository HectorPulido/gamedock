const $ = (s) => document.querySelector(s);
let state;
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function message(text, error = false) {
  GameDockNotifications.show(text, { kind: error ? "error" : "success" });
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw Error(data.error || "The operation could not be completed");
  return data;
}
async function action(fn, button) {
  if (button) button.disabled = true;
  message("");
  try {
    await fn();
  } catch (e) {
    message(e.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
async function authenticate(mode) {
  const form = $("#auth-form");
  if (!form.reportValidity()) return;
  const body = Object.fromEntries(new FormData(form));
  await api("/auth/" + mode, "POST", body);
  form.reset();
  await load();
}
$("#auth-form").onsubmit = (e) => {
  e.preventDefault();
  action(() => authenticate("login"), e.submitter);
};
$("#register").onclick = (e) =>
  action(() => authenticate("register"), e.target);
const refreshButton = $("#refresh");
refreshButton.onclick = (e) => action(refresh, e.currentTarget);
async function load() {
  state = await api("/catalog");
  document.title = state.settings.name;
  GameDockTheme.apply(state.settings);
  $("#brand").textContent = state.settings.name;
  $("#headline").textContent = state.settings.name;
  $("#banner").textContent = state.settings.banner;
  $("#intro-banner").hidden = !state.settings.banner_image;
  $(".desktop-art").hidden = !!state.settings.banner_image;
  if (state.settings.banner_image)
    $("#intro-banner").src = state.settings.banner_image;
  $(".intro").hidden = !!state.user;
  $("#auth").hidden = !!state.user;
  $("#library").hidden = !state.user;
  $("#register").hidden = !state.settings.registration;
  $("#invite-field").hidden =
    !state.settings.registration || !state.settings.invite_required;
  $("#identity").replaceChildren();
  if (!state.user) return;
  $("#identity").append(node("span", state.user.username + " "));
  const out = node("button", "Sign out", "secondary");
  out.onclick = () =>
    action(async () => {
      await api("/logout", "POST", {});
      await load();
    }, out);
  if (state.user.admin) {
    const admin = node("a", "Administration", "button secondary");
    admin.href = "/admin";
    $("#identity").append(admin);
  }
  refreshButton.hidden = false;
  $("#identity").append(refreshButton, out);
  renderGames();
  await refresh();
}

function renderGames() {
  $("#games").replaceChildren();
  const games = state.games.filter(
    (g) => g.enabled !== false && g.max_per_user !== 0,
  );
  for (const game of games) {
    const card = node("article", null, "game");
    const cover = node("div", null, "game-cover");
    if (game.banner && /^https?:\/\//.test(game.banner)) {
      const img = node("img");
      img.src = game.banner;
      img.alt = "";
      img.loading = "lazy";
      img.onerror = () => { cover.textContent = "▦"; };
      cover.append(img);
    } else cover.textContent = "▦";
    const body = node("div", null, "game-body");
    body.append(node("h3", game.name), node("p", game.description));
    const launch = node("button", "Launch instance");
    launch.onclick = () =>
      action(async () => {
        const instance = await api("/instances", "POST", { game: game.id });
        location.assign(instance.url);
      }, launch);
    body.append(launch);
    card.append(cover, body);
    $("#games").append(card);
  }
  if (!games.length)
    $("#games").append(
      node(
        "p",
        "No games are available. An administrator can add them to the catalog.",
      ),
    );
}
async function refresh() {
  const list = (await api("/instances")).filter(
    (i) =>
      ["running", "starting"].includes(i.status) && i.uid === state.user.id,
  );
  $("#instances").replaceChildren();
  if (!list.length)
    $("#instances").append(
      node("p", "No running instances. Choose a game to start playing."),
    );
  for (const i of list) {
    const row = node("div", null, "instance " + i.status);
    const text = node("div");
    const game = state.games.find((g) => g.id === i.game);
    text.append(
      node("strong", game?.name || i.game),
      node(
        "small",
        i.resolution +
          " · " +
          ({
            running: "Running",
            starting: "Starting",
            stopped: "Stopped",
            failed: "Startup failed",
          }[i.status] || i.status),
      ),
    );
    const controls = node("div", null, "actions");
    if (i.status === "running") {
      const open = node("a", "Connect", "button");
      open.href = "/play/" + i.id;
      const stop = node("button", "Stop", "danger");
      stop.onclick = () => {
        if (confirm("Stop this instance? Save your game before continuing."))
          action(async () => {
            await api("/instances/" + i.id, "DELETE", {});
            await refresh();
            message("Instance stopped.");
          }, stop);
      };
      controls.append(open, stop);
    }
    row.append(text, controls);
    $("#instances").append(row);
  }
}
action(load);
setInterval(() => {
  if (state?.user && !document.hidden)
    refresh().catch((error) =>
      GameDockNotifications.show(error.message, {
        kind: "error",
        key: "refresh-" + error.message,
      }),
    );
}, 15000);
