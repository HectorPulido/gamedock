"""Preserve fixed budgets with HTML5 clients and without measured congestion."""

import inspect
from pathlib import Path
from xpra.server.source import bandwidth

path = Path(inspect.getfile(bandwidth))
text = path.read_text()
patches = [
    (
        '        return caps.boolget("bandwidth")',
        '        return caps.boolget("bandwidth") or "bandwidth-limit" in caps',
    ),
    (
        "            self.bandwidth_limit = min(limit, bandwidth_limit)",
        "            limits = [v for v in (limit, bandwidth_limit) if v > 0]\n"
        "            self.bandwidth_limit = min(limits) if limits else 0",
    ),
    ("        if not self.bandwidth_detection:\n            return\n", ""),
    (
        "        if BANDWIDTH_DETECTION:\n",
        "        if BANDWIDTH_DETECTION and self.bandwidth_detection:\n",
    ),
    (
        "            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)",
        "            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit) if bandwidth_limit > 0 else self.bandwidth_limit",
    ),
    (
        "            bandwidth_limit = max(MIN_BANDWIDTH, bandwidth_limit)",
        "            floor = min(MIN_BANDWIDTH, self.bandwidth_limit) if self.bandwidth_limit > 0 else MIN_BANDWIDTH\n"
        "            bandwidth_limit = max(floor, bandwidth_limit)",
    ),
    (
        "                ws.bandwidth_limit = max(MIN_BANDWIDTH // 10, bandwidth_limit * weight // total_weight)",
        "                ws.bandwidth_limit = max(1, bandwidth_limit * weight // total_weight)",
    ),
]
for old, new in patches:
    if text.count(old) != 1:
        raise RuntimeError(f"Unsupported Xpra bandwidth patch: {old!r}")
    text = text.replace(old, new)
path.write_text(text)

# Patch the actual packaged HTML client before its handshake. Remove precompressed
# variants so Xpra cannot serve an older copy of these files.
www = Path("/usr/share/xpra/www")
client = www / "js/Client.js"
text = client.read_text()
old = '"bandwidth-limit":this.bandwidth_limit'
if text.count(old) != 1:
    raise RuntimeError("Unsupported Xpra HTML5 network capabilities")
client.write_text(
    text.replace(
        old, 'bandwidth:!0,"bandwidth-detection":this.bandwidth_detection!==!1,' + old
    )
)
# The offscreen worker must not overwrite the session's negotiated video size.
text = client.read_text()
old = 'this.set_encoding_option("video_max_size",[4096,4096])'
if text.count(old) != 1:
    raise RuntimeError("Unsupported Xpra offscreen video dimensions")
client.write_text(
    text.replace(
        old,
        'this.set_encoding_option("video_max_size",this.encoding_options.video_max_size)',
    )
)
index = www / "index.html"
text = index.read_text()
old = "        client.scale = scale;"
if text.count(old) != 1:
    raise RuntimeError("Unsupported Xpra HTML5 initialization")
index.write_text(
    text.replace(
        old,
        old
        + """
        client.bandwidth_detection = getboolparam("bandwidth_detection", true);
        client.encoding_options.video_max_size = [
          getintparam("video_max_width", 3840), getintparam("video_max_height", 2160)
        ];
""",
    )
)
# WebCodecs can exist in Chromium builds without proprietary H.264 codecs.
# Probe before starting the worker/hello, retaining image fallbacks on failure.
text = index.read_text()
old = "          client.set_encoding(encoding);"
if text.count(old) != 1:
    raise RuntimeError("Unsupported Xpra encoding preference")
text = text.replace(old, old + '\n          client.set_encoding_option("", encoding);')
old = "          client.connect();"
if text.count(old) != 1:
    raise RuntimeError("Unsupported Xpra HTML5 connection startup")
index.write_text(
    text.replace(
        old,
        """
          (async () => {
            let supported = false;
            try {
              if (typeof VideoDecoder !== 'undefined') {
                const probe = await Promise.race([
                  VideoDecoder.isConfigSupported({codec: 'avc1.42C01E'}),
                  new Promise(resolve => setTimeout(() => resolve({supported:false}), 2000))
                ]);
                supported = probe.supported;
              }
            } catch (_) {}
            client.gamedock_h264_supported = supported;
            if (!supported) {
              client.check_encodings = client.check_encodings.filter(c => c !== 'h264');
              client.supported_encodings = client.supported_encodings.filter(c => c !== 'h264');
              if (client.encoding === 'h264') { client.set_encoding('auto'); client.set_encoding_option('', 'auto'); }
            }
            client.connect();
          })();
""",
    )
)
for file in (client, index):
    for suffix in (".gz", ".br"):
        Path(str(file) + suffix).unlink(missing_ok=True)
