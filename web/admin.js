const $ = (s) => document.querySelector(s);
let state;
let profileEditing = false;
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
// Sidebar links use normal URLs so sections can be bookmarked and browser Back works.
const sections = [
  "access",
  "games",
  "platform",
  "appearance",
  "streaming",
  "instances",
];
function showSection(focus = false) {
  const id = location.hash.slice(1);
  const selected = sections.includes(id) ? id : "access";
  for (const name of sections) {
    $("#section-" + name).hidden = name !== selected;
    const link = $("#admin-nav a[href='#" + name + "']");
    if (name === selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (focus) {
    $("#" + selected + "-title").focus({ preventScroll: true });
    $("#admin-main").scrollTop = 0;
  }
}
function goToSection(id) {
  if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
  showSection();
}
window.addEventListener("hashchange", () => showSection(true));
window.addEventListener("popstate", () => showSection(true));
async function load() {
  state = await api("/catalog");
  if (!state.user?.admin) {
    location.replace("/");
    return;
  }
  GameDockTheme.apply(state.settings);
  document.title = state.settings.name + " | Administration";
  message("");
  $("#admin-operator").textContent = "Signed in as " + state.user.username;
  for (const key of [
    "name",
    "banner",
    "banner_image",
    "max_instances",
    "per_user",
    "idle_minutes",
    "viewer_action",
    "viewer_disconnect_seconds",
    "viewer_first_connect_seconds",
    "memory_mb",
    "cpus",
  ])
    $("#settings").elements[key].value = state.settings[key] ?? "";
  for (const key of ["registration", "desktop_toolbar", "invite_required"])
    $("#settings").elements[key].checked = state.settings[key];
  fillAppearance(state.settings.appearance || {});
  fillStreaming(state.settings.streaming);
  if (!profileEditing) editGame();
  renderGames();
  await users();
  await invitations();
  await refresh();
  $("#admin-workspace").hidden = false;
  showSection();
}
function filterAccounts() {
  const query = $("#account-search").value.trim().toLowerCase();
  let found = 0;
  for (const account of document.querySelectorAll("#users .account")) {
    account.hidden = !account.dataset.search.includes(query);
    if (!account.hidden) found++;
  }
  $("#account-count").textContent = query
    ? found + " / " + state.users.length
    : state.users.length;
  $("#users-empty")?.remove();
  if (!found) {
    const empty = node(
      "p",
      query ? "No accounts match your search." : "No accounts yet.",
      "empty-state",
    );
    empty.id = "users-empty";
    $("#users").append(empty);
  }
}
$("#account-search").addEventListener("input", filterAccounts);
function renderGames() {
  const query = $("#game-search").value.trim().toLowerCase();
  $("#games").replaceChildren();
  for (const game of state.games.filter((g) =>
    (g.name + " " + g.id).toLowerCase().includes(query),
  )) {
    const card = node("article", null, "managed-game");
    const text = node("div", null, "managed-game-info");
    text.append(
      node("h3", game.name),
      node("p", game.description || game.id),
      node(
        "small",
        (game.enabled === false ? "Disabled" : "Enabled") +
          " · " +
          game.id +
          " · " +
          (game.memory_mb ?? state.settings.memory_mb) +
          " MiB / " +
          (game.cpus ?? state.settings.cpus) +
          " CPU",
      ),
    );
    const edit = node("button", "Edit", "secondary");
    edit.onclick = () => {
      editGame(game);
      $("#game-editor").scrollIntoView({ behavior: "smooth", block: "start" });
      $("#profile").elements.definition.focus({ preventScroll: true });
    };
    const remove = node("button", "Remove from catalog", "danger");
    remove.onclick = () => {
      if (confirm("Remove " + game.name + " from the catalog?"))
        action(async () => {
          await api("/admin/games/" + game.id, "DELETE", {});
          try {
            if (
              JSON.parse($("#profile").elements.definition.value).id === game.id
            )
              editGame();
          } catch {}
          await load();
          message("Game removed.");
        }, remove);
    };
    const controls = node("div", null, "managed-game-controls");
    const resolution = node("label", "Test resolution");
    const select = node("select");
    for (const size of game.resolutions) {
      const option = node("option", size);
      option.value = size;
      select.append(option);
    }
    select.value = game.default_resolution || game.resolutions[0];
    resolution.append(select);
    const launch = node("button", "Launch test", "secondary");
    launch.onclick = () =>
      action(async () => {
        const instance = await api("/instances", "POST", {
          game: game.id,
          resolution: select.value,
        });
        location.assign(instance.url);
      }, launch);
    const actions = node("div", null, "actions");
    actions.append(edit, launch, remove);
    const availability = node("label", null, "game-availability");
    const toggle = node("input");
    toggle.type = "checkbox";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-label", "Enable " + game.name);
    toggle.checked = game.enabled !== false;
    toggle.onchange = () =>
      action(async () => {
        try {
          const updated = await api("/admin/games/" + game.id, "PATCH", {
            enabled: toggle.checked,
          });
          game.enabled = updated.enabled;
          try {
            const f = $("#profile").elements;
            const draft = JSON.parse(f.definition.value);
            if (draft.id === game.id) {
              draft.enabled = updated.enabled;
              f.enabled.checked = updated.enabled;
              f.definition.value = JSON.stringify(draft, null, 2);
            }
          } catch {}
          renderGames();
          message(game.name + (game.enabled ? " enabled." : " disabled."));
        } catch (error) {
          toggle.checked = game.enabled !== false;
          throw error;
        }
      }, toggle);
    availability.append(toggle, node("span", "Enabled"));
    controls.append(availability, resolution, actions);
    card.append(text, controls);
    $("#games").append(card);
  }
  if (!$("#games").children.length)
    $("#games").append(
      node(
        "p",
        query
          ? "No games match your search."
          : "No games yet. Add a game to build your catalog.",
        "empty-state",
      ),
    );
}
$("#game-search").addEventListener("input", () => renderGames());
let running = [];
async function refresh() {
  running = (await api("/instances")).filter((i) =>
    ["running", "starting"].includes(i.status),
  );
  renderInstances();
}
function renderInstances() {
  const query = $("#instance-search").value.trim().toLowerCase();
  $("#instances").replaceChildren();
  for (const instance of running) {
    const game = state.games.find((g) => g.id === instance.game);
    const account = state.users?.find((u) => u.id === instance.uid);
    const search = [game?.name, instance.game, account?.username, instance.id]
      .join(" ")
      .toLowerCase();
    if (!search.includes(query)) continue;
    const row = node("div", null, "instance");
    const text = node("div");
    text.append(
      node("strong", game?.name || instance.game),
      node(
        "small",
        (account?.username || "Account " + instance.uid) +
          " · " +
          instance.resolution +
          " · " +
          instance.status,
      ),
      node("small", instance.id),
      node("small", (() => {
        const v = instance.viewers;
        if (!v || v.count === null) return "Viewers: unknown · awaiting verification";
        let text = "Viewers: " + v.count;
        if (v.without_viewer_seconds !== null) text += " · No viewer for " + v.without_viewer_seconds + "s";
        if (v.waiting_for_first_viewer) text += " · Waiting for first viewer";
        if (v.stop_pending) text += " · Stop in " + v.stop_in_seconds + "s";
        return text;
      })()),
    );
    const controls = node("div", null, "actions");
    const connect = node("a", "Connect", "button secondary");
    connect.href = "/play/" + instance.id;
    const stop = node("button", "Stop", "danger");
    stop.onclick = () => {
      if (confirm("Stop this instance? Unsaved progress may be lost."))
        action(async () => {
          await api("/instances/" + instance.id, "DELETE", {});
          await refresh();
          message("Instance stopped.");
        }, stop);
    };
    controls.append(connect, stop);
    row.append(text, controls);
    $("#instances").append(row);
  }
  if (!$("#instances").children.length)
    $("#instances").append(
      node(
        "p",
        query ? "No instances match your search." : "No running instances.",
        "empty-state",
      ),
    );
}
$("#instance-search").addEventListener("input", renderInstances);
$("#refresh").onclick = (e) => action(refresh, e.target);
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
      viewer_action: f.elements.viewer_action.value,
      viewer_disconnect_seconds: Number(f.elements.viewer_disconnect_seconds.value),
      viewer_first_connect_seconds: Number(f.elements.viewer_first_connect_seconds.value),
      max_instances: Number(f.elements.max_instances.value),
      per_user: Number(f.elements.per_user.value),
      memory_mb: Number(f.elements.memory_mb.value),
      cpus: Number(f.elements.cpus.value),
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
  f.enabled.checked = game?.enabled !== false;
  f.banner.value = game?.banner || "";
  previewBanner();
  f.memory_mb.value = game?.memory_mb ?? "";
  f.cpus.value = game?.cpus ?? "";
  fillGpu(game?.gpu || {});
  fillNetwork(game || {});
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
      memory_mb: null,
      cpus: null,
      banner: "",
      env: {},
      streaming: {},
      gpu: { vendor: "none" },
    },
    null,
    2,
  );
}
function newGame() {
  editGame();
  goToSection("games");
  $("#profile").scrollIntoView({ behavior: "smooth" });
  $("#profile").elements.definition.focus();
}
$("#add-game").onclick = newGame;
$("#new-game").onclick = newGame;
$("#profile").oninput = () => {
  profileEditing = true;
};
// Keep the convenient controls and JSON editor in sync. Invalid JSON stays
// untouched until the administrator fixes it and submits the form.
$("#profile").elements.definition.addEventListener("input", (e) => {
  try {
    const game = JSON.parse(e.target.value);
    $("#profile").elements.enabled.checked = game.enabled !== false;
    $("#profile").elements.banner.value = game.banner || "";
    previewBanner();
    $("#profile").elements.memory_mb.value = game.memory_mb ?? "";
    $("#profile").elements.cpus.value = game.cpus ?? "";
    fillGpu(game.gpu || {});
    fillNetwork(game);
  } catch {}
});
function previewBanner() {
  const preview = $("#banner-preview");
  const url = $("#profile").elements.banner.value.trim();
  preview.textContent = "▦";
  if (!/^https?:\/\//.test(url)) return;
  const image = node("img");
  image.alt = "";
  image.src = url;
  image.onload = () => {
    if ($("#profile").elements.banner.value.trim() === url)
      preview.replaceChildren(image);
  };
}
$("#profile").elements.banner.addEventListener("input", (event) => {
  previewBanner();
  try {
    const f = $("#profile").elements;
    const game = JSON.parse(f.definition.value);
    game.banner = event.target.value.trim();
    f.definition.value = JSON.stringify(game, null, 2);
  } catch {}
});
$("#profile").elements.enabled.addEventListener("change", (event) => {
  try {
    const f = $("#profile").elements;
    const game = JSON.parse(f.definition.value);
    game.enabled = event.target.checked;
    f.definition.value = JSON.stringify(game, null, 2);
  } catch {}
});
for (const key of ["memory_mb", "cpus"])
  $("#profile").elements[key].addEventListener("input", (e) => {
    try {
      const f = $("#profile").elements;
      const game = JSON.parse(f.definition.value);
      game[key] = e.target.value === "" ? null : Number(e.target.value);
      f.definition.value = JSON.stringify(game, null, 2);
    } catch {}
  });
function fillGpu(gpu) {
  const f = $("#profile").elements;
  f.gpu_vendor.value = gpu.vendor || "none";
  f.gpu_device.value =
    gpu.device ||
    (gpu.vendor === "nvidia"
      ? "0"
      : gpu.vendor && gpu.vendor !== "none"
        ? "/dev/dri/renderD128"
        : "");
  f.gpu_groups.value = (gpu.groups || []).join(", ");
  f.software_threads.value = gpu.software_threads ?? 0;
  f.software_threads.disabled = f.gpu_vendor.value !== "none";
  f.gpu_device.disabled = f.gpu_groups.disabled = f.gpu_vendor.value === "none";
}
function gpuFromForm(previous = {}) {
  const f = $("#profile").elements;
  if (f.gpu_vendor.value === "none")
    return {
      vendor: "none",
      software_threads: Number(f.software_threads.value),
    };
  const raw = f.gpu_groups.value.trim();
  if (raw && !/^\d+(?:\s*,\s*\d+)*$/.test(raw))
    throw Error("GPU host group IDs must be comma-separated numbers");
  const gpu = {
    ...previous,
    vendor: f.gpu_vendor.value,
    device: f.gpu_device.value.trim(),
    groups: raw ? raw.split(",").map(Number) : [],
  };
  if (gpu.vendor !== "nvidia" && gpu.vgl_display != null)
    gpu.vgl_display = gpu.device;
  return gpu;
}
for (const key of [
  "gpu_vendor",
  "gpu_device",
  "gpu_groups",
  "software_threads",
]) {
  $("#profile").elements[key].addEventListener("input", () => {
    try {
      const f = $("#profile").elements;
      const game = JSON.parse(f.definition.value);
      if (key === "gpu_vendor") {
        fillGpu({ vendor: f.gpu_vendor.value });
        delete game.gpu;
      }
      game.gpu = gpuFromForm(game.gpu);
      f.definition.value = JSON.stringify(game, null, 2);
    } catch {}
  });
}
$("#profile").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const game = JSON.parse(e.target.elements.definition.value);
    for (const key of ["memory_mb", "cpus"]) {
      const value = e.target.elements[key].value;
      game[key] = value === "" ? null : Number(value);
    }
    game.gpu = gpuFromForm(game.gpu);
    game.network_policy = networkFromForm();
    game.internet_access = game.network_policy.mode === "internet";
    game.enabled = e.target.elements.enabled.checked;
    game.banner = e.target.elements.banner.value.trim();
    await api("/admin/games", "PUT", game);
    profileEditing = false;
    await load();
    editGame(state.games.find((g) => g.id === game.id));
    message("Game saved.");
  }, e.submitter);
};
async function invitations() {
  const list = await api("/admin/invitations");
  $("#invitations").replaceChildren();
  if (!list.length)
    $("#invitations").append(
      node(
        "p",
        "No invitations yet. Create one to invite a player.",
        "empty-state",
      ),
    );
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
  state.users = list;
  $("#account-count").textContent = list.length;
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
    container.dataset.search = u.username.toLowerCase();
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
  filterAccounts();
}
// Appearance is saved separately so changing limits cannot overwrite a theme.
const appearanceForm = $("#appearance");
const colorLabels = {
  background: "Page background",
  surface: "Cards and inputs",
  text: "Text",
  muted: "Secondary text",
  accent: "Accent",
  accent_text: "Accent text",
  border: "Borders",
  art: "Covers and artwork",
  danger: "Danger text",
  danger_background: "Danger background",
  focus: "Keyboard focus",
  player_background: "Viewer background",
  player_header: "Viewer header",
  player_text: "Viewer text",
};
for (const [key, label] of Object.entries(colorLabels)) {
  const el = node("label", label);
  const input = node("input");
  input.type = "color";
  input.name = "color_" + key;
  el.append(input);
  $("#theme-colors").append(el);
}
function fillAppearance(a) {
  const f = appearanceForm.elements;
  f.theme.value = a.theme || "classic";
  f.font.value = a.font || "trebuchet";
  f.radius.value = a.radius ?? 7;
  f.content_width.value = a.content_width ?? 1180;
  f.logo_url.value = a.logo_url || "";
  f.background_image.value = a.background_image || "";
  f.footer.value = a.footer ?? "Game desktops under your control.";
  f.custom_css.value = a.custom_css || "";
  const colors = {
    ...GameDockTheme.presets[f.theme.value].colors,
    ...a.colors,
  };
  for (const key of Object.keys(colorLabels))
    f["color_" + key].value = colors[key];
}
function readAppearance() {
  const f = appearanceForm.elements;
  return {
    theme: f.theme.value,
    font: f.font.value,
    radius: Number(f.radius.value),
    content_width: Number(f.content_width.value),
    logo_url: f.logo_url.value,
    background_image: f.background_image.value,
    footer: f.footer.value,
    custom_css: f.custom_css.value,
    colors: Object.fromEntries(
      Object.keys(colorLabels).map((key) => [key, f["color_" + key].value]),
    ),
  };
}
appearanceForm.elements.theme.onchange = () => {
  const f = appearanceForm.elements;
  for (const [key, value] of Object.entries(
    GameDockTheme.presets[f.theme.value].colors,
  ))
    f["color_" + key].value = value;
  $("#appearance-status").textContent =
    "Preset colors loaded. Preview or save to apply.";
};
$("#preview-theme").onclick = () => {
  if (!appearanceForm.reportValidity()) return;
  GameDockTheme.apply({ ...state.settings, appearance: readAppearance() });
  $("#appearance-status").textContent =
    "Preview only. Save appearance to apply for everyone.";
};
$("#cancel-theme").onclick = () => {
  fillAppearance(state.settings.appearance || {});
  GameDockTheme.apply(state.settings);
  $("#appearance-status").textContent = "Preview discarded.";
};
$("#reset-theme").onclick = () => {
  fillAppearance({ theme: appearanceForm.elements.theme.value });
  // Drop custom CSS from the preview too, so this also recovers a broken layout.
  GameDockTheme.apply({ ...state.settings, appearance: readAppearance() });
  $("#appearance-status").textContent =
    "Preset restored in preview. Save to keep it.";
};
appearanceForm.onsubmit = (e) => {
  e.preventDefault();
  $("#appearance-status").textContent = "Saving appearance…";
  action(async () => {
    const appearance = readAppearance();
    const saved = await api("/admin/settings", "PUT", { appearance });
    state.settings = saved;
    GameDockTheme.apply(saved);
    $("#appearance-status").textContent = "Appearance saved.";
  }, e.submitter);
};
$("#export-theme").onclick = () => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(readAppearance(), null, 2)], {
      type: "application/json",
    }),
  );
  const link = node("a");
  link.href = url;
  link.download = "appearance.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("#import-theme").onchange = async (e) => {
  try {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 30000) throw Error("Appearance file is too large.");
    const a = JSON.parse(await file.text());
    if (
      !a ||
      Array.isArray(a) ||
      typeof a !== "object" ||
      (a.theme && !GameDockTheme.presets[a.theme])
    )
      throw Error("Invalid appearance file.");
    fillAppearance(a);
    $("#appearance-status").textContent =
      "Appearance imported. Preview or save to apply.";
  } catch (error) {
    $("#appearance-status").textContent = error.message;
  } finally {
    e.target.value = "";
  }
};

action(load);
setInterval(() => {
  if (state?.user?.admin && !document.hidden && location.hash === "#instances")
    action(refresh);
}, 15000);

function fillStreaming(values) {
  const fields = $("#streaming-fields");
  if (!fields.children.length) {
    const groups = new Map();
    for (const [key, spec] of Object.entries(state.streaming_schema)) {
      if (spec.deprecated) continue;
      if (!groups.has(spec.group)) {
        const group = node("fieldset");
        group.className = "streaming-group";
        group.append(node("legend", spec.group));
        const grid = node("div", null, "streaming-grid");
        group.append(grid);
        groups.set(spec.group, grid);
        fields.append(group);
      }
      const label = node("label", spec.label);
      let input;
      if (spec.type === "select") {
        input = node("select");
        for (const value of spec.options) {
          const option = node(
            "option",
            value === "all" ? "Automatic / all available" : value,
          );
          option.value = value;
          input.append(option);
        }
      } else {
        input = node("input");
        input.type = spec.type === "boolean" ? "checkbox" : "number";
        if (spec.type === "boolean") label.className = "check";
        else {
          input.min = spec.min;
          input.max = spec.max;
          input.step = spec.step;
          input.required = true;
        }
      }
      input.name = key;
      if (spec.type === "boolean") label.prepend(input);
      else label.append(input);
      const wrapper = node("div");
      wrapper.append(label);
      if (spec.help) wrapper.append(node("p", spec.help, "help"));
      groups.get(spec.group).append(wrapper);
    }
  }
  for (const [key, spec] of Object.entries(state.streaming_schema)) {
      if (spec.deprecated) continue;
    const input = $("#streaming-settings").elements[key];
    if (spec.type === "boolean") input.checked = values[key] ?? spec.default;
    else input.value = values[key] ?? spec.default;
  }
}
for (const button of document.querySelectorAll("[data-streaming-preset]")) {
  button.onclick = () => {
    fillStreaming(state.streaming_presets[button.dataset.streamingPreset]);
    message(
      "Preset loaded. Save streaming settings to apply it to new instances.",
    );
  };
}
$("#streaming-settings").onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const streaming = {};
    for (const [key, spec] of Object.entries(state.streaming_schema)) {
      if (spec.deprecated) continue;
      const input = event.target.elements[key];
      streaming[key] =
        spec.type === "boolean"
          ? input.checked
          : spec.type === "number"
            ? Number(input.value)
            : input.value;
    }
    const result = await api("/admin/settings", "PUT", { streaming });
    state.settings.streaming = result.streaming;
    message("Streaming settings saved. They apply to new instances.");
  }, event.submitter);
};

function fillNetwork(game) {
  const f = $("#profile").elements;
  const policy = game.network_policy || {mode: game.internet_access ? "internet" : "offline"};
  f.network_mode.value = policy.mode || "offline";
  f.network_allow.value = (policy.allow || []).map(r => `${r.cidr} ${r.port} ${r.protocol}`).join("\n");
  f.network_deny.value = (policy.deny || []).join("\n");
}
function networkFromForm() {
  const f = $("#profile").elements;
  const lines = value => value.split(/\n/).map(s => s.trim()).filter(Boolean);
  return {mode: f.network_mode.value, deny: lines(f.network_deny.value),
    allow: lines(f.network_allow.value).map(line => {
      const parts = line.split(/\s+/);
      if (parts.length !== 3) throw new Error("Allowed services: use IP/CIDR port tcp|udp on each line.");
      return {cidr: parts[0], port: Number(parts[1]), protocol: parts[2].toLowerCase()};
    })};
}
for (const key of ["network_mode", "network_allow", "network_deny"]) {
  $("#profile").elements[key].addEventListener("input", () => {
    try {
      const f = $("#profile").elements;
      const game = JSON.parse(f.definition.value);
      game.network_policy = networkFromForm();
      game.internet_access = game.network_policy.mode === "internet";
      f.definition.value = JSON.stringify(game, null, 2);
    } catch {}
  });
}
