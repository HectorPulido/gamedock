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
