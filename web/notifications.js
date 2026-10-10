/* A small, non-blocking notification queue, shared by every GameDock page. */
window.GameDockNotifications = (() => {
  const host = document.querySelector("#player-notice, #notice");
  const seen = new Set();
  const queue = [];
  let active, timer;
  if (!host) return { show() {}, clear() {}, remember() {} };
  host.className = "toast-region";
  host.replaceChildren();
  host.removeAttribute("role");
  host.setAttribute("aria-live", "polite");
  host.setAttribute("aria-atomic", "true");
  document.body.append(host);
  function clear() {
    clearTimeout(timer);
    active = undefined;
    host.replaceChildren();
    if (queue.length) render(queue.shift());
  }
  function render(item) {
    active = item;
    const card = document.createElement("section");
    card.className = "toast " + item.kind;
    card.setAttribute("role", "status");
    const mark = document.createElement("span");
    mark.className = "toast-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent =
      item.kind === "error" ? "!" : item.kind === "success" ? "✓" : "i";
    const copy = document.createElement("div");
    copy.className = "toast-copy";
    const title = document.createElement("strong");
    title.textContent =
      item.title ||
      (item.kind === "error"
        ? "Something went wrong"
        : item.kind === "success"
          ? "Done"
          : document.querySelector("#brand")?.textContent || "GameDock");
    const body = document.createElement("p");
    body.textContent = item.text;
    copy.append(title, body);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.textContent = "×";
    close.onclick = () => {
      clear();
      const frame = document.querySelector("#desktop-frame");
      if (frame && !frame.hidden) {
        try {
          frame.contentWindow.focus();
        } catch {}
      }
    };
    const progress = document.createElement("i");
    progress.className = "toast-timer";
    progress.style.animationDuration = item.duration + "ms";
    card.append(mark, copy, close, progress);
    host.replaceChildren(card);
    let started = performance.now(),
      remaining = item.duration;
    const pauses = new Set();
    const pause = (reason) => {
      if (!pauses.size) {
        clearTimeout(timer);
        remaining -= performance.now() - started;
        card.classList.add("paused");
      }
      pauses.add(reason);
    };
    const resume = (reason) => {
      pauses.delete(reason);
      if (pauses.size || active !== item) return;
      started = performance.now();
      timer = setTimeout(clear, Math.max(0, remaining));
      card.classList.remove("paused");
    };
    card.addEventListener("mouseenter", () => pause("pointer"));
    card.addEventListener("mouseleave", () => resume("pointer"));
    card.addEventListener("focusin", () => pause("focus"));
    card.addEventListener("focusout", (event) => {
      if (!card.contains(event.relatedTarget)) resume("focus");
    });
    timer = setTimeout(clear, remaining);
  }
  function show(text, options = {}) {
    if (!text) {
      queue.length = 0;
      clear();
      return;
    }
    if (options.key && seen.has(options.key)) return;
    if (active?.text === text || queue.some((item) => item.text === text))
      return;
    if (options.key) seen.add(options.key);
    const item = {
      text,
      kind: "info",
      duration: options.kind === "error" ? 12000 : 9000,
      ...options,
    };
    if (!active) render(item);
    else {
      if (queue.length === 3) queue.shift();
      queue.push(item);
    }
  }
  function remember(text, options = {}) {
    try {
      sessionStorage.setItem(
        "gamedock-notification",
        JSON.stringify({ text, options }),
      );
    } catch {}
  }
  try {
    const pending = sessionStorage.getItem("gamedock-notification");
    sessionStorage.removeItem("gamedock-notification");
    if (pending) {
      const item = JSON.parse(pending);
      // Let page initialization clear old action feedback before showing this.
      document.addEventListener(
        "DOMContentLoaded",
        () => show(item.text, item.options),
        { once: true },
      );
    }
  } catch {}
  return { show, clear, remember };
})();
