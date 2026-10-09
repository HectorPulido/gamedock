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
