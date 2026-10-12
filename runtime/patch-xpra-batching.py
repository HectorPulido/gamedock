"""Make refresh-derived batching optional without changing the capture target."""

import inspect
from pathlib import Path
from xpra.server.window import batch_config, video_compress


def replace_once(module, old, new):
    path = Path(inspect.getfile(module))
    source = path.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f"Unsupported Xpra batching target: {path}")
    path.write_text(source.replace(old, new))


replace_once(
    batch_config,
    "        if MIN_VREFRESH <= vrefresh <= MAX_VREFRESH:\n",
    '        if __import__("os").environ.get("GAMEDOCK_BATCH_MATCH_REFRESH", "1") != "1":\n'
    "            return\n"
    "        if MIN_VREFRESH <= vrefresh <= MAX_VREFRESH:\n",
)
replace_once(
    video_compress,
    "        if self.batch_config.min_delay > 20:\n",
    '        if __import__("os").environ.get("GAMEDOCK_BATCH_MATCH_REFRESH", "1") != "1":\n'
    '            framerate = max(MIN_VREFRESH, min(MAX_VREFRESH, int(__import__("os").environ.get("GAMEDOCK_CAPTURE_HZ", "30"))))\n'
    "        elif self.batch_config.min_delay > 20:\n",
)
