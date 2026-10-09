"""Repair Xpra's stale per-window idle batch state.

The HTML client can unmap the shadow window while the page is hidden without
marking the whole client source idle.  In that state Xpra locks the window's
batch delay at one second, but the next user event does not call ``no_idle``
because the client source itself already says it is active.  Make every real
user event reconcile the window sources as well.
"""

from pathlib import Path
import inspect

from xpra.server.source import idle_mixin, window


def replace_once(module, old: str, new: str) -> None:
    source = Path(inspect.getfile(module))
    contents = source.read_text()
    count = contents.count(old)
    if count != 1:
        raise RuntimeError(f"expected one Xpra patch target in {source}, found {count}")
    source.write_text(contents.replace(old, new))


replace_once(
    idle_mixin,
    """        if self.idle:\n            self.no_idle()\n""",
    """        # Reconcile per-window idle state even when the client source\n        # already considers itself active. A hidden HTML page can otherwise\n        # leave its window batch delay locked at one second.\n        self.no_idle()\n""",
)

replace_once(
    window,
    """    def no_idle(self) -> None:\n        # on user event, we stop being idle\n        if not self.idle:\n            return\n        self.idle = False\n        for window_source in self.all_window_sources():\n            window_source.no_idle()\n""",
    """    def no_idle(self) -> None:\n        # Window sources may have gone idle independently after an HTML\n        # unmap, so always reconcile them on the next user event.\n        self.idle = False\n        for window_source in self.all_window_sources():\n            window_source.no_idle()\n""",
)
