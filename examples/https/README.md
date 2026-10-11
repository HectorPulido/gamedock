# HTTPS and browser video decoding

WebCodecs video decoding requires a secure browser context. `http://localhost`
works for local testing; `http://192.168.x.x` does not, even when the browser runs
on that server. A public/LAN client should use HTTPS with a trusted certificate
and WSS. A TLS reverse proxy can forward HTTP/WebSockets to the existing portal.

For standalone TLS, supply `fullchain.pem` and `privkey.pem` in a directory on the
Docker host, then set these values in your environment / `.env`:

```dotenv
TLS_DIRECTORY=/absolute/path/to/certificates
PUBLIC_URL=https://games.example.com:8443
PORT=8443
BIND_ADDRESS=0.0.0.0
```

```sh
docker compose -f compose.yaml -f examples/https/compose.yaml up -d --build
```

The directory mounts read-only. No keys are stored in Git. Restart the portal
after certificate renewal. The container health check skips certificate
verification **only for its loopback request**; browsers must trust the certificate.

HTTPS enables access to WebCodecs, but does not guarantee that a particular
browser supports H.264. Diagnostics show the browser codec list, actual received
codecs, decoding errors, and the reason H.264 is unavailable. JPEG/WebP remain
fallbacks. GameDock advertises the session's source dimensions as the maximum
video size, rather than Xpra HTML5's old 1024×768 default. Lossless PNG profiles
continue to exclude H.264.

## Bandwidth and process accounting

The fixed Mbps value is an Xpra encoding budget per viewer. The runtime patches
Xpra 6.5.4's HTML5 capability mismatch, zero/unlimited negotiation, and loss of a
fixed budget when no congestion is measured. Both the negotiated and per-window
budgets remain bounded when bandwidth detection is enabled or disabled.
This is adaptive quality/batching, **not a strict transport traffic shaper**.
Images, refresh frames and protocol overhead can cause bursts. Measure sustained
traffic from an external client; do not infer network throughput from FPS alone.

Game processes include Wine processes adopted by PID 1 in the dedicated game
container. Xpra and its children, Xvfb and openbox are streaming overhead. Runtime,
init and Docker exec process trees are excluded. The game group includes the
launcher and Wine services as well as the executable. RSS sums may count shared
pages more than once; PSS apportions shared pages. Container cgroup memory also
includes cache/kernel memory and is a separate value, not a sum of RSS or VRAM.
PSS/cgroup fields show unavailable if the kernel doesn't expose them. CPU uses
per-PID start times to avoid spikes when a PID is recycled, and cgroup CPU tracks
all container work, including exited processes.

Runtime changes apply to newly created game containers after rebuilding their
images. Refresh an open player page for frontend changes. Existing game containers
are never patched in place.

Run `./scripts/qa-streaming.sh` for the isolated HTTPS/H.264 check. It creates a
short-lived self-signed test certificate, which only the QA browser accepts.
The check uses a separate client container; it does not replace a real external
client/network test.
