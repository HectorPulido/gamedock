"""Attach the lightweight presence publisher to the supported Xpra runtime."""

import inspect
from pathlib import Path
import sysconfig
from xpra.x11.shadow import server

path = Path(inspect.getfile(server))
source = path.read_text()
marker = "from gamedock_presence import instrument as _gamedock_presence"
if "class ShadowX11Server(" not in source or marker in source:
    raise RuntimeError("Unsupported or already patched Xpra presence target")
path.write_text(source + "\n\n" + marker + "\n_gamedock_presence(ShadowX11Server)\n")
Path(sysconfig.get_path("purelib"), "gamedock_presence.py").write_bytes(
    Path("/tmp/gamedock_presence.py").read_bytes()
)
