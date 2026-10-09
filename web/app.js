const $ = (s) => document.querySelector(s);
let state;
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function message(text) {
  $("#notice").textContent = text;
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
    message(e.message);
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
$("#refresh").onclick = (e) => action(refresh, e.target);
async function load() {
  state = await api("/catalog");
  document.title = state.settings.name;
  $("#brand").textContent = state.settings.name;
  $("#headline").textContent = state.settings.name;
  $("#banner").textContent = state.settings.banner;
  $("#intro-banner").hidden = !state.settings.banner_image;
  $(".desktop-art").hidden = !!state.settings.banner_image;
  if (state.settings.banner_image)
    $("#intro-banner").src = state.settings.banner_image;
  $("#auth").hidden = !!state.user;
  $("#library").hidden = !state.user;
  $("#admin").hidden = !state.user?.admin;
  $("#register").hidden = !state.settings.registration;
  $("#identity").replaceChildren();
  if (!state.user) return;
  $("#identity").append(node("span", state.user.username + " "));
  const out = node("button", "Sign out", "secondary");
  out.onclick = () =>
    action(async () => {
      await api("/logout", "POST", {});
      await load();
    }, out);
  $("#identity").append(out);
  renderGames();
  await refresh();
  if (state.user.admin) {
    for (const key of [
      "name",
      "banner",
      "banner_image",
      "max_instances",
      "per_user",
    ])
      $("#settings").elements[key].value = state.settings[key] ?? "";
    $("#settings").elements.registration.checked = state.settings.registration;
    $("#profile").elements.definition.value = JSON.stringify(
      {
        id: "my-game",
        name: "My game",
        image: "my-game:local",
        command: ["/opt/game/start"],
        resolutions: ["1280x720", "1920x1080"],
        env: {},
        description: "Describe the game",
      },
      null,
      2,
    );
    await users();
  }
}
function renderGames() {
  $("#games").replaceChildren();
  for (const game of state.games) {
    const card = node("article", null, "game");
    const cover = node("div", null, "game-cover");
    if (game.banner && /^https?:\/\//.test(game.banner)) {
      const img = node("img");
      img.src = game.banner;
      img.alt = "";
      cover.append(img);
    } else cover.textContent = "▦";
    const body = node("div", null, "game-body");
    body.append(node("h3", game.name), node("p", game.description));
    const label = node("label", "Resolution");
    const select = node("select");
    for (const size of game.resolutions) {
      const o = node("option", size);
      o.value = size;
      select.append(o);
    }
    label.append(select);
    const launch = node("button", "Launch instance");
    launch.onclick = () =>
      action(async () => {
        const instance = await api("/instances", "POST", {
          game: game.id,
          resolution: select.value,
        });
        message(
          "Instance created. The desktop may take a few seconds to become ready.",
        );
        await refresh();
      }, launch);
    body.append(label, launch);
    if (state.user.admin) {
      const edit = node("button", "Edit", "secondary");
      edit.onclick = () => {
        $("#admin details").open = true;
        $("#profile").elements.definition.value = JSON.stringify(game, null, 2);
        $("#profile").scrollIntoView({ behavior: "smooth" });
      };
      const remove = node("button", "Remove from catalog", "danger");
      remove.onclick = () => {
        if (confirm("Remove " + game.name + " from the catalog?"))
          action(async () => {
            await api("/admin/games/" + game.id, "DELETE", {});
            await load();
          }, remove);
      };
      const controls = node("div", null, "actions");
      controls.style.marginTop = "12px";
      controls.append(edit, remove);
      body.append(controls);
    }
    card.append(cover, body);
    $("#games").append(card);
  }
  if (!state.games.length)
    $("#games").append(
      node(
        "p",
        "No games are available. An administrator can add them to the catalog.",
      ),
    );
}
async function refresh() {
  const list = await api("/instances");
  $("#instances").replaceChildren();
  if (!list.length)
    $("#instances").append(
      node(
        "p",
        "You have no instances yet. Choose a game to launch your first one.",
      ),
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
          }[i.status] || i.status) +
          (state.user.admin ? " · Account " + i.uid : ""),
      ),
    );
    const controls = node("div", null, "actions");
    if (i.status === "running") {
      const open = node("a", "Connect", "button");
      open.href = "/desktop/" + i.id + "/";
      open.target = "_blank";
      open.rel = "noopener";
      const stop = node("button", "Stop", "danger");
      stop.onclick = () => {
        if (confirm("Stop this instance? Save your game before continuing."))
          action(async () => {
            await api("/instances/" + i.id, "DELETE", {});
            await refresh();
          }, stop);
      };
      controls.append(open, stop);
    }
    row.append(text, controls);
    $("#instances").append(row);
  }
}
$("#settings").onsubmit = (e) => {
  e.preventDefault();
  const f = e.target;
  action(async () => {
    await api("/admin/settings", "PUT", {
      name: f.elements.name.value,
      banner: f.elements.banner.value,
      banner_image: f.elements.banner_image.value,
      registration: f.elements.registration.checked,
      max_instances: Number(f.elements.max_instances.value),
      per_user: Number(f.elements.per_user.value),
    });
    await load();
    message("Settings saved.");
  }, e.submitter);
};
$("#profile").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    await api(
      "/admin/games",
      "PUT",
      JSON.parse(e.target.elements.definition.value),
    );
    await load();
    message("Game saved.");
  }, e.submitter);
};
async function users() {
  const list = await api("/admin/users");
  $("#users").replaceChildren();
  for (const u of list) {
    const row = node("div", null, "user-row");
    row.append(
      node(
        "span",
        u.username +
          (u.admin ? " · Administrator" : "") +
          (u.enabled ? "" : " · Disabled"),
      ),
    );
    if (u.id !== state.user.id) {
      const toggle = node(
        "button",
        u.enabled ? "Disable account" : "Enable account",
        "secondary",
      );
      toggle.onclick = () => {
        if (
          !u.enabled ||
          confirm("Disable this account and stop its instances?")
        )
          action(async () => {
            await api("/admin/users/" + u.id, "PATCH", { enabled: !u.enabled });
            await users();
            await refresh();
          }, toggle);
      };
      row.append(toggle);
    }
    $("#users").append(row);
  }
}
action(load);
