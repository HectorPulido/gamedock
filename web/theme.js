/* Shared by the library, sign-in page and desktop viewer. */
window.GameDockTheme = (() => {
  const presets = {
    classic: {
      label: "Classic",
      colors: {
        background: "#eaf1fa",
        surface: "#ffffff",
        text: "#163354",
        muted: "#45648b",
        accent: "#235bc4",
        accent_text: "#ffffff",
        border: "#9eb4d3",
        art: "#d1dff5",
        danger: "#a03542",
        danger_background: "#ffe4e8",
        focus: "#b87400",
        player_background: "#101a29",
        player_header: "#163354",
        player_text: "#eaf1fa",
      },
    },
    midnight: {
      label: "Midnight",
      colors: {
        background: "#171b26",
        surface: "#222938",
        text: "#edf1f7",
        muted: "#b3bfd2",
        accent: "#91b9f3",
        accent_text: "#122039",
        border: "#53627c",
        art: "#2c3850",
        danger: "#ffb4bd",
        danger_background: "#542c38",
        focus: "#f2c76b",
        player_background: "#11151e",
        player_header: "#222938",
        player_text: "#edf1f7",
      },
    },
    forest: {
      label: "Forest",
      colors: {
        background: "#edf2ef",
        surface: "#ffffff",
        text: "#203c31",
        muted: "#4e6b5d",
        accent: "#28664b",
        accent_text: "#ffffff",
        border: "#9ab3a5",
        art: "#d2e2d9",
        danger: "#9f3243",
        danger_background: "#ffe5e9",
        focus: "#9c6500",
        player_background: "#14271f",
        player_header: "#203c31",
        player_text: "#edf2ef",
      },
    },
  };
  const fonts = {
    trebuchet: '"Trebuchet MS", Verdana, sans-serif',
    system: 'system-ui, -apple-system, "Segoe UI", sans-serif',
    verdana: "Verdana, Geneva, sans-serif",
    mono: 'ui-monospace, "Cascadia Code", monospace',
  };
  let custom;
  function apply(settings) {
    const a = settings.appearance || {};
    const theme = presets[a.theme] || presets.classic;
    const root = document.documentElement;
    root.dataset.theme = a.theme || "classic";
    root.style.colorScheme = a.theme === "midnight" ? "dark" : "light";
    for (const [key, color] of Object.entries({ ...theme.colors, ...a.colors }))
      root.style.setProperty("--" + key.replaceAll("_", "-"), color);
    root.style.setProperty("--font", fonts[a.font] || fonts.trebuchet);
    root.style.setProperty("--radius", (a.radius ?? 7) + "px");
    root.style.setProperty("--content-width", (a.content_width ?? 1180) + "px");
    // JSON quoting keeps the complete URL inside a single CSS string.
    root.style.setProperty(
      "--background-image",
      a.background_image
        ? `url(${JSON.stringify(a.background_image)})`
        : "none",
    );
    if (!custom) {
      custom = document.createElement("style");
      custom.id = "platform-custom-css";
      document.head.append(custom);
    }
    custom.textContent = a.custom_css || "";
    document
      .querySelectorAll("[data-platform-name]")
      .forEach((el) => (el.textContent = settings.name));
    const footer = document.querySelector("#footer-message");
    if (footer)
      footer.textContent = a.footer ?? "Game desktops under your control.";
    document.querySelectorAll(".brand-logo").forEach((img) => {
      img.hidden = !a.logo_url;
      if (a.logo_url) img.src = a.logo_url;
      else img.removeAttribute("src");
    });
    document
      .querySelectorAll(".mark")
      .forEach((el) => (el.hidden = !!a.logo_url));
  }
  return { presets, fonts, apply };
})();
