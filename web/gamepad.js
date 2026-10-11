/* Browser controllers and multitouch feed the same bounded session state. */
window.GameDockController = (() => {
  function create(frame, sid) {
    const settings = document.querySelector('#controller-mode');
    const overlay = document.querySelector('#touch-controller');
    const physical = document.querySelector('#physical-controller');
    try { physical.checked = localStorage.getItem('gamedock-physical-controller') !== 'off'; } catch {}
    physical.onchange = () => {
      try { localStorage.setItem('gamedock-physical-controller', physical.checked ? 'on' : 'off'); } catch {}
      last = '';
    };
    const status = document.querySelector('#controller-status');
    const pointerResets = [];
    const touch = { axes: [0, 0, 0, 0], buttons: Array(17).fill(false) };
    let enabled = true, busy = false, last = '', sentAt = 0, nextAt = 0, backend = '', selected = null;
    let paused = false;
    try { settings.value = localStorage.getItem('gamedock-controller-mode') || 'auto'; } catch {}
    const mobile = matchMedia('(pointer: coarse)');
    function clear() {
      touch.axes.fill(0); touch.buttons.fill(false); last = '';
      for (const reset of pointerResets) reset();
      overlay.querySelectorAll('.pressed').forEach(el => el.classList.remove('pressed'));

    }
    function visibility() {
      overlay.hidden = !enabled || paused || settings.value === 'off' ||
        (settings.value === 'auto' && !mobile.matches);
      if (overlay.hidden) clear();
    }
    settings.onchange = () => {
      try { localStorage.setItem('gamedock-controller-mode', settings.value); } catch {}
      clear(); visibility();
    };
    mobile.addEventListener('change', visibility);
    visibility();
    const stick = overlay.querySelector('.touch-stick');
    const joystick = nipplejs.create({
      zone: stick, mode: 'static', position: {left: '50%', top: '50%'},
      color: 'white', size: 100, restOpacity: .35, dynamicPage: true,
    });
    joystick.on('move', (event) => {
      const data = event.data;
      touch.axes[0] = Math.abs(data.vector.x) < .12 ? 0 : Math.max(-1, Math.min(1, data.vector.x));
      touch.axes[1] = Math.abs(data.vector.y) < .12 ? 0 : Math.max(-1, Math.min(1, -data.vector.y));
    });
    joystick.on('end', () => { touch.axes[0] = touch.axes[1] = 0; });
    for (const button of overlay.querySelectorAll('[data-button]')) {
      const pointers = new Set();
      pointerResets.push(() => {
        for (const id of pointers) if (button.hasPointerCapture(id)) button.releasePointerCapture(id);
        pointers.clear();
      });
      button.onpointerdown = event => {
        event.preventDefault(); pointers.add(event.pointerId);
        button.setPointerCapture(event.pointerId);
        touch.buttons[+button.dataset.button] = true; button.classList.add('pressed');
      };
      button.onpointerup = button.onpointercancel = button.onlostpointercapture = event => {
        pointers.delete(event.pointerId);
        touch.buttons[+button.dataset.button] = pointers.size > 0;
        button.classList.toggle('pressed', pointers.size > 0);
      };
    }
    async function send(state, force = false) {
      const now = performance.now(), json = JSON.stringify(state);
      if (busy || (!force && now < nextAt) || (json === last && now - sentAt < 250)) return;
      busy = true;
      try {
        const response = await fetch(`/desktop/${sid}/gamedock-controller`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: json,
          signal: AbortSignal.timeout(2000),
        });
        if (!response.ok) throw Error('Controller unavailable; launch a new session after updating its image.');
        const result = await response.json(); backend = result.mode;
        last = json; sentAt = now; nextAt = 0;
      } catch (error) { backend = ''; status.textContent = error.message; nextAt = now + 3000; }
      finally { busy = false; }
    }
    function tick() {
      if (!enabled) return;
      const active = !paused && document.hasFocus() && !document.hidden;
      const state = { axes: [0, 0, 0, 0], buttons: Array(17).fill(false) };
      let pad;
      if (active) {
        try {
          const pads = physical.checked ? Array.from(navigator.getGamepads?.() || []) : [];
          pad = pads.find(p => p?.index === selected && p.mapping === 'standard') ||
            pads.find(p => p?.connected && p.mapping === 'standard');
        } catch {}
        if (pad) {
          selected = pad.index;
          state.axes = state.axes.map((_, i) => {
            const value = Math.max(-1, Math.min(1, pad.axes[i] || 0));
            return Math.abs(value) < .15 ? 0 : Math.round(value * 100) / 100;
          });
          state.buttons = state.buttons.map((_, i) => !!pad.buttons[i]?.pressed);
        }
        if (!overlay.hidden) {
          state.axes = state.axes.map((value, i) => Math.abs(touch.axes[i]) > Math.abs(value) ? touch.axes[i] : value);
          state.buttons = state.buttons.map((value, i) => value || touch.buttons[i]);
        }
      }
      // Poll even inside the same-origin Xpra iframe: parent blur alone must not disable physical input.
      if (frame.contentWindow?.client?.connected) {
        send(state);
        if (backend) status.textContent = `${pad ? pad.id : 'Touch controller'} · ${backend === 'gamepad' ? 'Virtual gamepad' : 'Keyboard mode (WASD / arrows)'}${!isSecureContext ? ' · HTTPS required for physical controllers' : ''}`;
      }
    }
    const timer = setInterval(tick, 50);
    document.addEventListener('visibilitychange', () => { clear(); tick(); });
    const dialogObserver = new MutationObserver(() => {
      paused = document.querySelector('#player-settings').open; clear(); visibility(); tick();
    });
    dialogObserver.observe(document.querySelector('#player-settings'), {attributes: true, attributeFilter: ['open']});
    window.addEventListener('pagehide', () => {
      clear();
      navigator.sendBeacon(`/desktop/${sid}/gamedock-controller`, new Blob([
        JSON.stringify({ axes: [0,0,0,0], buttons: Array(17).fill(false) })
      ], { type: 'application/json' }));
    });
    visibility();
    return { dispose() { enabled = false; clear(); overlay.hidden = true; clearInterval(timer); dialogObserver.disconnect(); joystick.destroy(); send(touch, true); } };
  }
  return { create };
})();
