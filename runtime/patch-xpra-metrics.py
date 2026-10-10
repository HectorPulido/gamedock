"""Attach optional telemetry without changing capture timing or encoded pixels."""

from pathlib import Path
import sysconfig
from xpra.x11.shadow import server
import inspect

source = Path(inspect.getfile(server))
text = source.read_text()
marker = "from gamedock_metrics import instrument as _gamedock_instrument"
if "class ShadowX11Server(" not in text or marker in text:
    raise RuntimeError("Unsupported or already patched Xpra shadow server")
source.write_text(text + "\n\n" + marker + "\n_gamedock_instrument(ShadowX11Server)\n")
target = Path(sysconfig.get_path("purelib"), "gamedock_metrics.py")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(Path("/tmp/gamedock_metrics.py").read_bytes())
