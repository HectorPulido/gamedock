"""Reconcile HTML5 visibility, desktop iconic state and window batch locks.

A visible page must clear iconification before asking for a refresh. Keep the
normal iconic guard for genuinely hidden windows; do not merely remove it.
"""
import inspect
from pathlib import Path
from xpra.server.window import compress
from xpra.x11.desktop import base


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"Unsupported Xpra visibility patch target in {path}: {old!r}")
    path.write_text(text.replace(old, new))


replace_once(
    Path(inspect.getfile(base)),
    '        self._window_mapped_at(proto, wid, window, (x, y, w, h))\n',
    '        # A map is authoritative even when old clients omit window state.\n'
    '        if __import__("os").environ.get("GAMEDOCK_IDLE_FIX", "1") == "1":\n'
    '            self._set_window_state(proto, wid, window, {"iconified": False})\n'
    '        self._window_mapped_at(proto, wid, window, (x, y, w, h))\n',
)
replace_once(
    Path(inspect.getfile(compress)),
    '    def map(self, mapped_at: tuple[int, int]) -> None:\n        self.mapped_at = mapped_at\n        self.no_idle()\n',
    '    def map(self, mapped_at: tuple[int, int]) -> None:\n'
    '        self.mapped_at = mapped_at\n'
    '        if __import__("os").environ.get("GAMEDOCK_IDLE_FIX", "1") == "1":\n'
    '            self.iconic = False\n'
    '        self.no_idle()\n',
)
replace_once(
    Path(inspect.getfile(compress)),
    '        self.batch_config.delay = self.batch_config.saved\n',
    '        self.batch_config.delay = self.batch_config.saved\n'
    '        if __import__("os").environ.get("GAMEDOCK_IDLE_FIX", "1") == "1":\n'
    '            self.batch_config.delay = min(self.batch_config.max_delay, max(self.batch_config.min_delay, self.batch_config.delay))\n',
)
client = Path('/usr/share/xpra/www/js/Client.js')
replace_once(
    client,
    'resume(){for(var index in this.id_to_window)this.id_to_window[index].resume();',
    'resume(){for(var index in this.id_to_window){const win=this.id_to_window[index];'
    'if(!win.override_redirect&&!win.tray)this.send_configure_window(win,{iconified:false},true);'
    'win.resume();}',
)
# Never let HTTP content negotiation select a stale precompressed client.
for suffix in ('.gz', '.br'):
    client.with_name(client.name + suffix).unlink(missing_ok=True)
