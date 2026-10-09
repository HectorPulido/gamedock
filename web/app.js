const $ = (s) => document.querySelector(s);
let state;
let profileEditing = false;
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
  $("#invite-field").hidden =
    !state.settings.registration || !state.settings.invite_required;
  $("#add-game").hidden = !state.user?.admin;
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
      "idle_minutes",
    ])
      $("#settings").elements[key].value = state.settings[key] ?? "";
    for (const key of ["registration", "desktop_toolbar", "invite_required"])
      $("#settings").elements[key].checked = state.settings[key];
    if (!profileEditing) editGame();
    await invitations();
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
    label.hidden = !state.user.admin;
    const launch = node("button", "Launch instance");
    launch.onclick = () =>
      action(async () => {
        const instance = await api("/instances", "POST", {
          game: game.id,
          ...(state.user.admin ? { resolution: select.value } : {}),
        });
        message(
          "Instance created. The desktop may take a few seconds to become ready.",
        );
        if (!state.user.admin) {
          location.assign(instance.url);
          return;
        }
        await refresh();
      }, launch);
    body.append(label, launch);
    if (state.user.admin) {
      const edit = node("button", "Edit", "secondary");
      edit.onclick = () => {
        $("#admin details").open = true;
        editGame(game);
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
  const list = (await api("/instances")).filter((i) =>
    ["running", "starting"].includes(i.status),
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
          }[i.status] || i.status) +
          (state.user.admin ? " · Account " + i.uid : ""),
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
      desktop_toolbar: f.elements.desktop_toolbar.checked,
      invite_required: f.elements.invite_required.checked,
      idle_minutes: Number(f.elements.idle_minutes.value),
      max_instances: Number(f.elements.max_instances.value),
      per_user: Number(f.elements.per_user.value),
    });
    await load();
    message("Settings saved.");
  }, e.submitter);
};
function editGame(game) {
  profileEditing = !!game;
  const f = $("#profile").elements;
  $("#profile-title").textContent = game ? "Edit game" : "Add game";
  $("#profile-mode-help").textContent = game
    ? "Editing an existing game. Save to update its definition. Use New game to start a separate profile."
    : "Create a game with a new ID. Saving an existing ID updates that game.";
  f.definition.value = JSON.stringify(
    game || {
      id: "my-game",
      name: "My game",
      description: "Describe the game",
      image: "my-game:local",
      command: ["/opt/game/start"],
      resolutions: ["1280x720", "1920x1080"],
      default_resolution: "1280x720",
      max_per_user: 1,
      enabled: true,
      internet_access: false,
      banner: "",
      env: {},
    },
    null,
    2,
  );
}
function newGame() {
  editGame();
  $("#admin details").open = true;
  $("#profile").scrollIntoView({ behavior: "smooth" });
  $("#profile").elements.definition.focus();
}
$("#add-game").onclick = newGame;
$("#new-game").onclick = newGame;
$("#profile").oninput = () => {
  profileEditing = true;
};
$("#profile").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    await api(
      "/admin/games",
      "PUT",
      JSON.parse(e.target.elements.definition.value),
    );
    profileEditing = false;
    await load();
    message("Game saved.");
  }, e.submitter);
};
async function invitations() {
  const list = await api("/admin/invitations");
  $("#invitations").replaceChildren();
  for (const invite of list) {
    const row = node("div", null, "user-row");
    row.append(
      node(
        "span",
        (invite.label || "Invitation") +
          " — " +
          invite.uses +
          "/" +
          invite.max_uses +
          " uses" +
          (invite.revoked
            ? " (revoked)"
            : invite.expires < Date.now() / 1000
              ? " (expired)"
              : " — expires " +
                new Date(invite.expires * 1000).toLocaleDateString()),
      ),
    );
    if (!invite.revoked) {
      const revoke = node("button", "Revoke", "secondary");
      revoke.onclick = () =>
        action(async () => {
          await api("/admin/invitations/" + invite.id, "DELETE", {});
          await invitations();
        }, revoke);
      row.append(revoke);
    }
    $("#invitations").append(row);
  }
}
$("#invitation-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const f = e.target.elements;
    const result = await api("/admin/invitations", "POST", {
      label: f.label.value,
      max_uses: Number(f.max_uses.value),
      expires_days: Number(f.expires_days.value),
    });
    $("#invitation-result").replaceChildren(
      node("span", "Copy this code now; it is shown only once: "),
      node("code", result.code),
    );
    await invitations();
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
    const container = node("div", null, "account");
    container.append(row);
    if (!u.admin) {
      const details = node("details", null, "advanced");
      details.append(node("summary", "Game access and instance limits"));
      const form = node("form", null, "account-policy");
      const maximum = node(
        "label",
        "Total instances (blank uses the platform limit)",
      );
      const maxInput = node("input");
      maxInput.type = "number";
      maxInput.min = 0;
      maxInput.max = 100;
      maxInput.value = u.policy.max_instances ?? "";
      maximum.append(maxInput);
      form.append(maximum);
      const inherit = node("label", null, "check"),
        inheritInput = node("input");
      inheritInput.type = "checkbox";
      inheritInput.checked = u.policy.games === null;
      inherit.append(
        inheritInput,
        document.createTextNode("Use the library's default game access"),
      );
      form.append(inherit);
      const fields = [];
      for (const game of state.games) {
        const label = node("label", game.name + " instances (0 blocks access)");
        const input = node("input");
        input.type = "number";
        input.min = 0;
        input.max = 100;
        input.value = u.policy.games?.[game.id] ?? game.max_per_user ?? 1;
        input.disabled = inheritInput.checked;
        label.append(input);
        form.append(label);
        fields.push([game.id, input]);
      }
      inheritInput.onchange = () =>
        fields.forEach(([, input]) => {
          input.disabled = inheritInput.checked;
        });
      const save = node("button", "Save account limits");
      form.append(save);
      form.onsubmit = (e) => {
        e.preventDefault();
        action(async () => {
          await api("/admin/users/" + u.id, "PATCH", {
            policy: {
              max_instances:
                maxInput.value === "" ? null : Number(maxInput.value),
              games: inheritInput.checked
                ? null
                : Object.fromEntries(
                    fields.map(([id, input]) => [id, Number(input.value)]),
                  ),
            },
          });
          message("Account limits saved.");
          await users();
        }, save);
      };
      details.append(form);
      container.append(details);
    }
    $("#users").append(container);
  }
}
action(load);
setInterval(() => {
  if (state?.user && !document.hidden) action(refresh);
}, 15000);
