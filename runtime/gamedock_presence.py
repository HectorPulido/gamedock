"""Publish cheap UI-client presence from Xpra's own event loop.

No subprocesses, process classification, capture metrics or xpra-info requests.
"""

import functools
import json
import os
from pathlib import Path
import time


def instrument(server_class):
    from gi.repository import GLib

    original = server_class.init

    @functools.wraps(original)
    def init(self, opts):
        result = original(self, opts)
        path = (
            Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/gamedock-runtime"))
            / "viewers.json"
        )
        ever_seen = False

        def publish():
            nonlocal ever_seen
            try:
                count = sum(
                    1
                    for source in tuple(self._server_sources.values())
                    if getattr(source, "window_enabled", False)
                    and not source.is_closed()
                )
                ever_seen |= count > 0
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(
                        {
                            "updated": time.time(),
                            "viewers": count,
                            "ever_seen": ever_seen,
                        }
                    )
                )
                temp.replace(path)
            except Exception:
                # A stale sample is rejected by the HTTP reader and portal.
                pass
            return True

        publish()
        GLib.timeout_add(1000, publish)
        return result

    server_class.init = init
