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

HTTPS enables WebCodecs but does not guarantee browser H.264 support. Inspect the
actual codec and decoder in Diagnostics. JPEG remains the compatibility fallback.
The WebSocket transport does not require WebRTC or extra UDP ports.

## Bandwidth and process accounting

The Mbps value is an encoder target, not a strict traffic shaper. Complex frames,
audio and protocol overhead can produce bursts. Measure sustained traffic from
a real client; FPS alone does not establish bandwidth or latency. Xpra batching
and capability patches no longer apply. See [migration notes](../../docs/selkies-migration.md).

Game processes include Wine processes adopted by PID 1 in the dedicated game
container. Selkies and its children, Xvfb, PulseAudio and openbox are streaming overhead. Runtime,
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

Run `./scripts/qa-streaming.sh` for current Selkies contract checks. A real
HTTPS browser decoder test and external-network acceptance run remain necessary
on the deployment host; contract tests do not measure those paths.
