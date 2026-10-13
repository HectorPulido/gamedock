# Selkies migration validation (2026-10-13)

The entries below the historical section describe the previous Xpra implementation
and are retained as historical evidence only. They do not establish Selkies
compatibility, current browser FPS or ten-player capacity. Current checks target
Selkies gateway restrictions, fixed operator settings, session lifecycle, metrics
and the generic GameDock viewer adapter. Real browser, native GPU, audio/controller
hardware and simultaneous ten-player acceptance must be recorded separately.

Example images now use Debian apt and numeric UID/GID 1000:1000. OpenTTD can be
built against an isolated Selkies runtime tag without any commercial game files.
Wine and Minecraft recipes require user-supplied clients; a Dockerfile update is
not proof those games launch or their authentication/audio work.

Observed generic OpenTTD smoke test: Debian image built successfully against
`gamedock-runtime:selkies-test`; an isolated UID1000 container with all capabilities
dropped and no-new-privileges served Selkies HTTP200 and ran OpenTTD14.1 at
960×540. Logs showed Selkies2.0 with H.264 target30FPS. This proves startup, not
actual browser decoder/FPS/audio quality. The disposable container was removed.

## Historical Xpra validation

# GameDock validation

The complete suite ran on October 9, 2026, on `hector-server`, Linux x86_64,
Docker 29.8.2, using the independent `gamedock-qa` Compose project.

| Requirement                         | Executed evidence                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Registration, sign-in, and sign-out | Four API tests and Chromium: account creation, subsequent sign-in, token revocation, and WebSocket closure on sign-out                      |
| User ownership                      | API rejects access to or termination of other users' desktops; regular users list only their own instances                                  |
| Command-line launch                 | CLI registers an account and launches the native profile; the configured command creates a file inside the container                        |
| Independent desktops                | Two concurrent containers on separate networks; direct cross-network connections rejected; no session ports published                       |
| Resolution                          | `xdpyinfo` inside both instances confirms 1280×720 and 1920×1080                                                                            |
| Names and banners                   | Chromium saves the name, message, and image through Administration and verifies image loading                                               |
| Basic administration                | API checks permissions, closed registration, limits, account disabling, token revocation, and instance termination; Chromium edits profiles |
| Real connection                     | Chromium waits for rendered pixels, types a command through the keyboard, and verifies the resulting file through Docker                    |
| Games                               | OpenTTD and OpenGFX built from the repository; real menu rendered through Xpra/WebSocket and terminated through the portal                  |
| Persistence                         | Portal recreation preserves the token, account, and game PID; replacing an instance preserves a marker in its volume                        |
| Separate deployments                | Docker tests confirm volumes under the `gamedock-qa` namespace; an independent clean deployment uses `gamedock-cleancheck-user-2-desktop`   |
| Mobile interface                    | Screenshot at 390 px and a check for horizontal overflow                                                                                    |

Run `./scripts/qa.sh` to reproduce the suite and generate screenshots under
`/tmp/gamedock-artifacts`. The final result was `QA passed`.

After adding namespaces, the real Docker/CLI and persistence tests were repeated.
A clean Git clone of commit `f34ddc6` also built the runtime and portal, deployed
an independent Compose project with an empty database, created an administrator
and user, and served an authenticated Xpra desktop. The clone's Git working tree
remained clean. No databases, game clients, or `.runtime` files were copied.

The local demo was also built from repository sources on macOS ARM64 using
OrbStack. `./scripts/start-local.sh` completed successfully and was repeated
without replacing credentials or data. All five API tests passed, followed by
native Chromium tests covering registration, login, rendered desktop pixels,
actual keyboard input, logout revocation, instance termination, mobile layout,
administration forms, and a rendered OpenTTD session. Initial credentials remain
in the ignored local `.env`; no remote images or application data were copied.

Minecraft and Wine are provided as configurable adapters. Commercial clients are
not distributed, and no claim is made that those clients have been tested. The
base runtime uses software rendering without audio or GPU access. Each game's
specific requirements belong in its image and profile, as described in the README.

The extraction did not modify or restart Dofus. Its original code is retained as
non-executable reference material under `upstream/`, with the original revision
recorded. Reference messages and default language settings were later translated
to English; consult the recorded source revision for the unmodified originals.

## Player controls and access policies

The October 9, 2026 update was checked in the isolated `gamedock-features` Docker
project on macOS ARM64, separate from the user's local demonstration data:

- Twelve API tests cover invitation expiry, revocation, use limits and concurrent
  redemption; registration mode; role permissions; game quotas and player
  resolution enforcement; activity ownership; inactivity cleanup; toolbar
  settings; and migration of the previous database schema.
- Chromium verifies automatic same-tab launch, centered and scaled game frames,
  actual keyboard input, previous-instance navigation, logout revocation, hidden
  stopped instances, and mobile layout.
- Chromium adds OpenTTD using the Add game editor, creates and redeems an
  invitation, changes the toolbar setting for a running viewer, edits account
  limits, and stops the rendered game.
- The real Docker/CLI suite checks administrator-selected player resolutions,
  persistent volumes, container isolation, cross-account denial, and portal
  recreation without restarting games.
- The real background worker stops an idle Docker instance after a configured
  one-minute timeout plus the next 15-second sweep.

The network probe found that OrbStack permits sibling traffic between ordinary
Docker bridges. Session networks are now internal by default; the repeat isolation
check passed. Internet access is an explicit game profile option and requires a
native Linux Docker host for sibling isolation, as documented in the README.

The JSON editor was restored with explicit Add game and Edit game modes.
Chromium verifies creation from a new template, loading an existing definition,
and resetting the editor with New game, alongside the OpenTTD player flow.

## Resource controls, platform appearance and fullscreen

The October 10, 2026 changes were checked in the independent
`gamedock-personalize` Docker project on macOS ARM64 with OrbStack:

- All 15 API tests pass in Docker, including resource inheritance and game
  overrides, administrator permissions, invalid resource and appearance values,
  Docker payload conversion, and escaped branding in initial HTML.
- The real Docker/CLI suite passes, including portal recreation without
  restarting the game process, persistence, resolutions and network isolation.
- Chromium verifies all three saved themes on the public sign-in page, the
  server name in titles and footer, preview isolation, logo loading, custom CSS,
  and appearance JSON import/export.
- Existing Chromium suites also pass registration, instance navigation, logout
  revocation, administration, invitations and a real OpenTTD session.
- Actual session inspection confirms inherited 1024 MiB / 0.5 CPU and per-game
  1536 MiB / 0.75 CPU limits.
- The viewer grows beyond its native 1280-pixel width while both the iframe
  viewport and `xdpyinfo` remain 1280×720. Real mouse/keyboard input reaches xterm
  through the enlarged viewer. Fullscreen entry/exit and mobile fitting pass.

Reproduce the feature checks with `tests/customization_browser.py`; the standard
`./scripts/qa.sh` now includes it. Screenshots from this run are under
`/tmp/gamedock-personalize-artifacts`. Credentials and application data remain
outside Git. Resource changes affect new sessions and do not restart games.

## Separate administrator workspace (2026-10-10)

- 16 API tests pass, including unauthenticated redirect and player denial for `/admin`.
- Chromium verifies identical player/admin game cards, a single administrator link, automatic launch, and own instances in the library.
- Workspace checks cover account/game/instance searches, preserved drafts, browser history, bookmarked sections, all three themes, and mobile layouts.
- Customization regression passes: branding, appearance preview/import/export, real Docker CPU/RAM limits, scaled input, unchanged desktop resolution, fullscreen, and mobile.

## Configurable streaming and floating notifications (2026-10-10)

- 19 host API/configuration tests pass; two Xpra-specific tests are skipped on the host and pass inside the rebuilt runtime image.
- The idle regression exercises both enabled and disabled recovery of an independently idle window while the connection remains active.
- Chromium verifies all 22 streaming controls, draft presets, saved/reloaded values, invalid combinations, four real rendered Xpra sessions, and per-game overrides.
- Actual runtime checks cover XSHM attachment, server arguments, negotiated browser quality, bandwidth settings, mouse/keyboard input, and unchanged 1280×720 display resolution.
- Browser regression suites pass for the separate administrator workspace, customization/scaling/fullscreen, and OpenTTD game creation, invitations and account limits.
- Both `gamedock-runtime:local` and the derived OpenTTD image were rebuilt; existing user game containers were preserved.
- Floating-notification browser checks pass for expiry, dismiss, errors, navigation persistence, polling deduplication, unchanged viewer layout/focus, fullscreen/mobile and the stopped-session state.

## Viewer quality diagnostics (2026-10-10)

- 24 host tests run: 22 pass and two Xpra-only checks skip on the host.
- Added API coverage for a coherent frozen HTML/CSS/JS bundle, immutable asset
  versions and rejection of unavailable versions instead of mixing files.
- Added capture counter coverage for successful reads, independent refresh-loop
  frequency, idle expiry and disabled instrumentation.
- A real animated xterm verifies positive capture, delivery, decode and image
  payload rates, source resolution unchanged, integer scaling, crisp filtering,
  keyboard input after header controls and no statistics polling after closing.
- Runtime telemetry uses decimal strings on the wire because Xpra HTML5's
  rencodeplus decoder does not support float64. The viewer converts numeric
  telemetry back to numbers without losing decimal precision.
- Transmission FPS are measured from Xpra frame boundaries; they do not measure
  the game engine. Image throughput excludes audio and transport overhead.

## Optional NVIDIA / AMD / Intel runtimes (2026-10-10)

- All three vendor targets build on the local Linux ARM64 Docker daemon, including
  VirtualGL 3.1.3, GLVND, Mesa and diagnostic utilities. No physical GPU is exposed
  by this Mac/OrbStack environment; hardware acceleration is not claimed tested.
- 29 host tests run: 27 pass and two runtime-only Xpra tests skip on the host.
  GPU tests cover device selection, restricted Docker device mappings, group IDs,
  legacy CPU profiles, vendor validation and software-renderer rejection.
- Actual container probes reject NVIDIA's available llvmpipe renderer and report
  missing AMD/Intel render nodes, with nonzero exit status and explicit errors.
- A Fedora EGL loading issue was resolved with `VGL_EGLLIB=libEGL.so.1`, so the
  NVIDIA probe reaches renderer detection instead of failing to resolve EGL.
- Browser coverage verifies all three GPU form options, JSON synchronization,
  groups/devices, persistence, disabling GPU and a rendered CPU-only session from
  a GPU image. Existing diagnostics and customization suites pass.
- GPU usage must still be verified on the intended Linux hardware. Prepared
  Compose demos and per-game profiles are in `examples/gpu`; no privileged mode,
  host display socket or GPU access for the portal is needed.

## Default software OpenGL (2026-10-10)

- The standard runtime explicitly selects Mesa llvmpipe before Xvfb and the game
  start. The game's command is unchanged and no GPU device is requested. Mesa was
  already installed transitively; the change makes selection, worker budgeting
  and inspection explicit rather than claiming new physical graphics resources.
- Real container probes confirm two software workers with a 2-CPU quota and one
  with a 0.5-CPU quota. Unit checks cover affinity/quota and manual override.
- The GPU form also saves a configurable software worker count; 0 is automatic.
  Diagnostics reports the renderer and configured workers. Software rendering
  is distinguished from hardware acceleration and is not advertised as a speedup
  for all games.
- Chromium renders a real `glxgears` scene from a GPU image with hardware disabled,
  and confirms llvmpipe plus an explicit three-worker setting in Diagnostics.

## Bandwidth, H.264 and Wine metrics (2026-10-10)

- Changes and tests are local to GameDock. No remote Dofus container was changed.
- 34 host tests: 29 pass, five Xpra-only tests skip; all five pass in the
  patched runtime. Lint and JavaScript syntax checks pass.
- Isolated HTTPS Chromium sessions verify actual H.264 decoding at 1280×720
  with zero decoder errors, and JPEG/WebP fallback in a browser without H.264.
  Both sessions report 6 Mbps client and window budgets. This is Xpra's adaptive
  encoding budget, not a strict network traffic shaper.
- A real orphan process named Dofus.exe, adopted by PID 1, allocates 160 MiB;
  game RSS/PSS and cgroup memory reflect it. Fixtures also cover CPU deltas,
  PID reuse and Docker exec exclusion. Actual Wine/Dofus and an external client
  remain to be verified on the destination server.
- Reproduce with `scripts/qa-streaming.sh`: its dedicated QA project/volume is
  recreated and removed; user GameDock data is untouched. HTTPS deployment and
  trusted certificates are described in `examples/https/README.md`.

Controller update: 37 Python tests ran (32 passed, 5 runtime-only skips), browser QA
passed mobile auto-detection, simultaneous NippleJS movement/face buttons,
cancellation, standard Gamepad polling, disconnect and disabling. A local
Xvfb runtime test verified actual X11 key state and watchdog release after
750 ms without updates. Authorization/origin/payload checks passed. Native
Linux uinput and real USB/Bluetooth hardware are prepared but unverified on
this Mac. Remote Dofus containers were not changed.

A real authenticated portal forwarded input into a newly launched runtime.
The actual Xpra viewer kept controller polling active after iframe load, and
Settings hid/restored the touch overlay. Local portal/runtime/OpenTTD/GPU images
were updated; the optional Linux evdev image was not built or hardware-tested.

Touch layout revision: dual NippleJS sticks delivered axes 0–3 simultaneously
with face buttons; release/cancellation passed. Captures reviewed at 844×390,
667×375, 568×320, 390×844 and 320×568. All touch targets remained on-screen
and at least 44×44 CSS pixels. Controller UI and documentation use English.

Visibility recovery and 20 Hz comparison (2026-10-12):

- The runtime now clears stale `iconic` state on an explicit map, and the HTML5
  client announces `iconified=false` before its resume refresh. The actual
  `unlock_batch_delay()` retains its guard for hidden windows and bounds a
  restored saved delay to the configured maximum. The existing `idle_fix`
  setting still controls the server-side recovery patches.
- Five tests executed against installed Xpra 6.5 cover active-client input,
  stale iconic state, saved delays beyond the configured maximum, repeated
  unmap/map cycles, and preservation of the hidden-window batch lock.
- Headed distribution Chromium, Xvfb and Openbox alternated real tabs four times
  per profile. `document.hidden` changed naturally; no visibility events or
  DOM properties were synthesized. While hidden, the window batch was locked;
  after returning and pressing ArrowRight/moving the pointer it was unlocked,
  with reported last delay 0 ms <= configured maximum 40 ms, on every cycle.
- This measures the local Mac/OrbStack software-rendered **glxgears** workload at
  1280x720, OpenH264/libyuv, fixed quality 50, minimum quality 30, adaptive
  bandwidth detection enabled. Each final foreground sample lasted about
  16 seconds. Values are run-to-run observations, not a Dofus benchmark:

  | Budget | Capture FPS | Delivered FPS | Decoded FPS | Image Mbps | Decode errors |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | 4 Mbps | 19.00 | 19.45 | 19.45 | 2.198 | 0 |
  | 6 Mbps | 19.50 | 19.84 | 19.84 | 2.233 | 0 |

- A useful starting profile is 20 Hz, quality 50 and 4–6 Mbps, retaining H.264
  with WebP/JPEG fallbacks. This fixture fit within 4 Mbps; 6 Mbps gives more
  headroom for complex scenes. The small FPS difference does not establish
  that the higher budget caused an improvement. No defaults were changed.
  External clients, actual character movement/textures in Wine/Dofus, GPU
  encoding and hostile-network latency remain to be validated on the target
  host; no remote Dofus container was changed.
- `tests/visibility_browser.py` reproduces real-tab recovery and captures draw
  payload bytes plus successful decoder acknowledgements. Use a disposable
  animated runtime exposed through HTTPS as `QA_XPRA_URL`, with matching
  `QA_BANDWIDTH_MBPS`. Build `tests/Dockerfile.visibility-browser` on the QA
  browser image and run headed under Xvfb/Openbox. The fixture disables
  Playwright's internal focus emulation, which otherwise falsely keeps all
  tabs visible. It does not alter the application or Chromium's visibility API.
  Raw local observations: `/tmp/gamedock-streaming-artifacts/visibility-4mbps.json`
  and `visibility-6mbps.json`; the recovered canvas screenshot is in that folder.
- Local runtime, OpenTTD and NVIDIA/AMD/Intel images include the patch for new
  sessions. Existing user sessions were not restarted.

### Viewer disconnection lifecycle (2026-10-12)

- Generic viewer leases are tracked by the authorized desktop WebSocket proxy;
  HTTP, input activity and controller requests do not acquire leases. Cleanup
  and incoming reservations share the launch lock. Runtime snapshots are fetched
  outside the lock, with a generation check and an atomic final expiry/stop check.
- Python suite: 65 tests, 56 passed and 9 runtime-only skips. The six Xpra
  idle/visibility/batching tests also passed in the updated runtime. New tests
  exercise connected spectators, two viewers, reconnect cancellation, separate
  first-viewer grace, disabled migration defaults, query errors/invalid presence,
  restart reconciliation, idempotent concurrent stops, a handshake pending at
  expiry, reconnection during an in-flight snapshot, Origin/ownership and session
  revocation. A socket that ignores WebSocket PING is reclaimed without browser
  unload events.
- `tests/test_presence.py` checks that the lightweight runtime publisher counts
  only open window sources, excludes non-UI metric clients, remembers prior
  viewers, and replaces stale bootstrap counts when a new portal proxy connects.
- `tests/viewers_browser.py` exercised actual Chromium, Xpra, GLX rendering and
  Docker against the disposable portal `gamedock-viewers-portal-qa` at
  `http://localhost:18089`, with its own database and volume namespace. Tests use
  12 seconds of disconnect grace and 45 seconds for the first viewer to shorten
  the run. The restart phase uses the actual 60-second default, then restores
  12 seconds for stop timing; production defaults remain 60 and 180 seconds,
  with action disabled.
- A new instance remained running without a viewer for 15 seconds. One connected
  viewer without input remained running beyond disconnect grace. Two tabs
  reported two viewers; closing one retained the instance. Reconnection reused
  the same instance and cancelled the stop. A real portal restart initially
  reported presence unknown, without scheduling a stop, and reconnection worked.
  Five successive rapid restart/reconnect cycles also passed. An earlier run
  with only 12 seconds for restart/loading expired before the new WebSocket
  arrived; HTTP loading deliberately does not count as a viewer. The restart
  acceptance fixture now uses the proposed production grace of 60 seconds.
- Closing the last viewer automatically removed both the game and namespace
  guard containers about 14.5 seconds after confirmed disconnect (12-second
  grace plus the five-second worker cadence). Docker returned 404 for both;
  no game processes or cgroup CPU/memory allocation remained. Before stopping,
  the container used approximately 174% CPU, 410 MB and 32 processes/threads.
  These measurements include Xpra and the GLX workload, not only the game.
- The next launch acquired the freed slot and read the persistent marker from
  the same named volume. Settings were also saved and reloaded through the
  browser; the English form and a 390 px mobile viewport passed.
- This Mac/OrbStack test used software Mesa rendering. Native NVIDIA/AMD/Intel
  GPU resource accounting was not measured; container removal uses the same
  generic cleanup path. All five local runtime/game/GPU image variants were
  checked for the presence and batching patches. No remote game deployment was
  changed.
- Artifacts: `/tmp/gamedock-viewer-artifacts/viewers-browser.json`,
  `viewer-presence-admin.png`, and `viewer-settings.png`.

Reproduce using a disposable portal (the browser fixture intentionally restarts
only the named QA portal):

```sh
docker run -d --name gamedock-viewers-portal-qa \
  -p 127.0.0.1:18089:8080 \
  -e PUBLIC_URL=http://localhost:18089 \
  -e ADMIN_PASSWORD=gamedock-viewers-test-password \
  -e GAMEDOCK_NAMESPACE=gamedock-viewers-qa \
  -e PORTAL_CONTAINER=gamedock-viewers-portal-qa \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v gamedock-viewers-portal-qa:/data gamedock-portal:local
mkdir -p /tmp/gamedock-viewer-artifacts
printf 'ADMIN_PASSWORD=gamedock-viewers-test-password\n' > /tmp/gamedock-viewers-qa.env
docker run --rm --network host \
  -v "$PWD:/app:ro" \
  -v /tmp/gamedock-viewers-qa.env:/qa.env:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/gamedock-viewer-artifacts:/artifacts \
  -e QA_URL=http://localhost:18089 \
  --entrypoint python gamedock-browser-qa:h264 /app/tests/viewers_browser.py
```

Remove only the QA portal and its two QA volumes after testing. The fixture stops
its game instances and deletes its temporary catalog entry, while deliberately
retaining the game volume to verify persistence.


## Browser FSR 1

- Uses AMD's upstream MIT-licensed FSR 1 EASU + RCAS shaders through WebGL 2,
  applied to the decoded Xpra canvas. Source/game/video dimensions do not change.
- Standalone Chromium tests cover shader orientation and colors, pointer
  passthrough, disposal/recreation at identical dimensions, filter switching and
  unavailable-WebGL fallback. Run `tests/fsr_browser.py` using the browser QA image.
- Real Xpra tests use a 960×540 desktop enlarged to 1600×900 and compare Smooth,
  Sharp and FSR; mouse coordinates are checked through fit and fullscreen changes.
  The presentation layer lives inside the iframe so Xpra toolbar/cursor DOM can
  remain above it. `tests/fsr_xpra_browser.py` runs against a disposable QA portal.
- Software Chromium measured approximately 100 ms shader initialization and
  0.4–8.7 ms CPU submission time in the standalone fixture. Real 540p samples
  varied from 2.7 to 84.9 ms across concurrent-build reruns. These figures
  are not GPU execution time, game FPS, end-to-end latency or mobile performance.
  Physical phones and native GPUs still need performance and battery testing.
- FSR cannot recover detail absent from a 540p source. The comparison establishes
  functionality, not a universal visual-quality advantage over the existing modes.
- Viewer-only streaming settings are omitted from the game container environment;
  existing runtime images need no schema update to use the browser's FSR filter.
- Real Xpra fullscreen toolbar entry and exit also passed, keeping FSR visible.
  Explicit WebGL context loss triggers the tested Smooth fallback.
- Comparison artifacts: `/tmp/gamedock-streaming-artifacts/xpra-540-smooth.png`,
  `xpra-540-crisp.png`, `xpra-540-fsr.png` and `fsr-colors.png`.
