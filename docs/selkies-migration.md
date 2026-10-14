# Migrating GameDock from Xpra to Selkies

This is a general GameDock runtime/viewer migration. No emulator, game server,
account provisioning bridge, host KSM configuration or particular game is needed.
The same image contract supports native Linux programs, OpenTTD, Java and Wine.

## Architecture

The portal keeps its authenticated `/play/ID`, `/desktop/ID/...`, API, SQLite,
account policies and persistent `/data` volume model. Session containers publish
no host ports. Per-session firewall namespaces and destination allowlists remain
in force. Selkies HTTP/WebSocket traffic passes through the same ownership and
Origin checks; its internal control/API paths are restricted by the gateway.

The runtime starts a pinned Selkies stack: DRI3-capable Xvfb, Openbox, PulseAudio
and pixelflux. This integration uses WebSockets, not WebRTC; it needs no UDP/TURN
services. H.264 decoding requires browser WebCodecs (HTTPS or localhost) and
codec support. JPEG provides a fallback; inspect the negotiated result.
Software rendering/encoding is supported. AMD/Intel can use GLAMOR/DRI3 and VAAPI;
NVIDIA rendering uses VirtualGL and encoding depends on available NVENC libraries.
Neither mapping a GPU nor requesting H.264 proves hardware acceleration.

The Selkies sidebar is hidden and technical mutations are blocked in the gateway.
GameDock's own settings affect local scaling/filtering, sound playback and input
preferences. Operators retain server FPS, bitrate, CRF/JPEG quality, codec and
audio settings. Those apply to newly launched sessions. Browser filters never
increase the transmitted resolution. FSR consumes client GPU work and cannot
recover missing text detail.

## Upgrade without discarding accounts or saves

1. Record the old portal/runtime/game image digests and current Compose/env files.
   Make a consistent SQLite backup (SQLite backup API or stop the portal during
   the copy) and back up named game volumes. Do not copy a live SQLite main file
   without its WAL. Keep secrets and backups outside Git.
2. Build the new runtime, then every game image derived from it. The base changes
   from Fedora to Debian: replace `dnf` packages with Debian equivalents. Keep
   UID/GID **1000:1000**, `/data`, the ordinary game CMD and persistent volume
   names. The base account name is not `player`: use numeric USER/COPY ownership.
3. Build/update the portal and preserve its database volume, namespace, game IDs,
   account IDs and network policy. Do not initialize a fresh SQLite database.
4. Stop and relaunch test game instances through GameDock. Existing Xpra runtime
   containers are not converted in place; do not mix them with the new viewer.
   Relaunch reuses the account/game volume and retains saved files.
5. Refresh browser pages so they receive the new coherent versioned asset bundle.
   Verify rendered video, mouse coordinates, keyboard, sound after a user gesture,
   fullscreen, reconnect, no-viewer cleanup and denied network destinations.
6. Test native GPU encoder selection and load on the intended host. Encoder target
   FPS and bitrate are configuration, not evidence of delivered FPS or capacity.

Legacy Xpra configuration keys remain accepted/readable for old database/profile
compatibility but are deprecated and ignored by Selkies. Migrate operator tuning
to the new streaming form rather than assuming old batching/codec values apply.
Accounts, password hashes, invitations and API authentication are unchanged.
This does not make application-specific game password schemes interchangeable.

## Rollback

Stop new runtime sessions, restore the pinned previous portal and game image
references and the corresponding Compose/env files. Reuse existing game volumes.
If database/profile changes cannot be read by the old version, restore the
consistent pre-upgrade SQLite backup; doing so loses subsequent account/catalog
changes, so retain the newer backup too. Browser pages must refresh to the old
asset version. Do not delete volumes as an upgrade or rollback step.

## Measurement and validation

Use `scripts/qa.sh` for current unit/adapter checks. Historical Xpra-specific
browser fixtures are not evidence for the replacement. For real acceptance,
compare the same game, scene, resolution and movement with separate client hosts.
Measure decoded/encoded FPS, RTT, encode/pipeline time, Mbps, errors, per-container
CPU and cgroup/PSS memory. Selkies host CPU/RAM counters are not game-container
usage. RSS may double-count shared pages; VRAM is separate from system RAM.
Exercise simultaneous joins as well as steady state, reconnection, mobile and
unsupported codec/WebGL fallback. See VALIDATION.md for observed results and gaps.
