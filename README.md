# GameDock

A framework for serving game desktops through a browser, with independent
accounts, configuration, and isolated game instances.

Includes registration, sign-in and sign-out, a bootstrap administrator, an editable
game catalog, platform name and banners, per-game resolutions, global and per-user
limits, account management, instance termination, and a CLI. Each instance runs a
command in its own container. The portal authenticates HTTP and WebSocket access
to Xpra; session containers do not publish ports to the host.

## Screenshots

OpenTTD running through the browser:

<img src="docs/screenshots/openttd.png" alt="OpenTTD running in a GameDock browser desktop" width="800" style="max-width: 100%; height: auto;" />

Game library:

<img src="docs/screenshots/library.png" alt="GameDock game library and running instance" width="800" style="max-width: 100%; height: auto;" />

## Getting started

For a local demo with OpenTTD included, run:

```sh
./scripts/start-local.sh
```

The script creates `.env` with a random administrator password if it does not
exist, builds the runtime and game images, starts the portal, waits for its health
check, and registers OpenTTD. Open `http://localhost:8080` and use the credentials
in `.env`. Create an invitation in Administration before registering a player
account. Repeating the command preserves existing credentials and data and updates the bundled OpenTTD profile. All application
dependencies run in Docker; the host needs Docker Engine, Docker Compose, and
Bash. On macOS, Docker Desktop or OrbStack provides the Linux environment.

### Initial administrator credentials

After running `./scripts/start-local.sh`, the initial username is `admin` and a
random password is saved as `ADMIN_PASSWORD` in `.env` at the repository root.
To display the credentials locally:

```sh
sed -n '/^ADMIN_USER=/p; /^ADMIN_PASSWORD=/p' .env
```

Use those values in the sign-in form at `http://localhost:8080`. Keep `.env`
private; it is excluded from Git. The administrator is created only when the
database is initialized. Editing `.env` later does not reset an existing
administrator's password. If `.env` already existed before running the script,
its credentials are preserved. You can also create a regular account through
the sign-in screen using an invitation code; only administrators can edit settings
and game profiles.

### Manual setup

Requirements: a Linux server with Docker Engine 26+ and Docker Compose. Tested on
x86_64. Serving the platform does not require Wine or Python on the host.

```sh
git clone git@github.com:HectorPulido/gamedock.git
cd gamedock
cp .env.example .env
# Edit .env: ADMIN_PASSWORD must contain at least 12 characters.
docker build -t gamedock-runtime:local runtime
docker compose up -d --build
```

Open `http://localhost:8080` and sign in with `ADMIN_USER` and `ADMIN_PASSWORD`.
The administrator is created on the first startup; changing `.env` does not change
existing passwords. The initial library includes an xterm desktop for testing
display, keyboard, and mouse input. Use Administration to change the name, welcome
message, banner image, registration policy, limits, game profiles, and account status.

For remote access, set `PUBLIC_URL` to the exact public HTTPS origin and place an
HTTPS proxy in front of the portal. Preserve paths and query strings and allow
WebSocket upgrades (Upgrade/Connection). Cookies use Secure when `PUBLIC_URL` uses
HTTPS. By default, the portal binds only to loopback. Do not expose session ports
or the Docker socket. Administrators are trusted operators: they select images
and commands, and the portal has access to the Docker daemon.

## Launch an instance from the command line

The CLI requires Python 3 and has no additional dependencies.

```sh
python3 cli/gamedock.py --url http://localhost:8080 register player --invite INVITATION_CODE
python3 cli/gamedock.py login player
python3 cli/gamedock.py launch desktop
python3 cli/gamedock.py list
python3 cli/gamedock.py stop INSTANCE_ID
python3 cli/gamedock.py logout
```

`launch` prints the instance ID and desktop URL. Sign in to the browser with the
same account to connect. Players use the administrator-configured resolution;
`--resolution` is available only to administrators. Passwords are prompted for rather than passed as command
arguments. CLI tokens expire after 24 hours and are stored with permissions 0600
in `~/.config/gamedock/session.json`. Use `GAMEDOCK_URL` or `--url` to select the
server and `--credentials` to maintain separate sessions.

## Add a game

Derive an image from `gamedock-runtime:local`, install the program, and keep the
`player` user (UID 1000). The working directory is `/data`, persisted per account
and game. As an administrator, click **Add game** above the library. Fill in the
name, unique ID, installed Docker image, launch command (one argument per line),
available resolutions, player resolution, and per-player instance limit. Click
**Save game** to publish it. Use **Edit** on a game card to update it. Environment
variables and Internet access are optional under Advanced settings. The image must already be built
or pulled on the server; adding a game does not download it.

Alternatively, create a profile through the CLI as an administrator:

```json
{
  "id": "my-game",
  "name": "My game",
  "description": "A game for your community",
  "banner": "https://example.com/banner.jpg",
  "image": "my-game:local",
  "command": ["/opt/game/start", "--server", "example.com"],
  "resolutions": ["1280x720", "1920x1080"],
  "default_resolution": "1280x720",
  "max_per_user": 1,
  "enabled": true,
  "env": { "LANG": "en_US.UTF-8" }
}
```

```sh
python3 cli/gamedock.py profile my-game.json
python3 cli/gamedock.py launch my-game --resolution 1280x720
```

`command` is an argument list with no implicit shell interpretation. If a shell
is needed, administrators can explicitly specify `["sh", "-c", "your command"]`.
Build or pull the image on the server before launching; GameDock does not pull
images automatically. Per-game banners are optional HTTP(S) image URLs. The
platform supports a welcome message and a banner image. Launch commands, images,
and environment variables are visible only to administrators. Do not use profile
environment variables to store individual users' secrets.

The runtime uses Xvfb, Openbox, and Xpra without audio. It supports X11 applications
and games compatible with software rendering. GPU access, controllers, audio,
anti-cheat, and 3D acceleration require adapting the image and device policy;
compatibility with every game is not guaranteed. Default per-session limits are
4 GiB of RAM, 2 CPUs, and 256 processes, configured in `server/app.py`.

### Ready-to-play example: OpenTTD

```sh
docker build -t gamedock-openttd:local examples/openttd
./bin/gamedock profile examples/openttd/profile.json
./bin/gamedock launch openttd --resolution 1280x720
```

Includes the free game and OpenGFX graphics from Fedora repositories, without
requiring commercial client files. Configuration and saved games are stored in
`/data`. `./bin/gamedock` accepts all CLI commands listed above.

### Minecraft and Windows

`examples/minecraft/` provides an image and profile for a Linux Java launcher.
Supply your client or launcher with its libraries and resources at
`examples/minecraft/client/launcher.jar`. It must open a graphical interface and
support Java 21; adapt the command if it uses a different format. No client is
included, and authentication and licensing are not bypassed. This is not a
universal official launcher configuration.

```sh
docker build -t gamedock-minecraft:local examples/minecraft
python3 cli/gamedock.py profile examples/minecraft/profile.json
python3 cli/gamedock.py launch minecraft --resolution 1280x720
```

`examples/wine/` provides a Windows adapter. Put the game files in
`examples/wine/client/`, adjust `Game.exe`, build `gamedock-wine:local`, and import
its `profile.json`. The Wine prefix is persisted at `/data/wine`.

## Persistence and operation

### Player desktops and toolbar

Launching a game as a player opens its desktop automatically in the same tab.
The game is centered in the available space and scaled down to fit smaller
windows without changing its configured resolution. The top bar shows running
instances, **Previous instance**, **Back to library**, and **Stop instance**.
Returning to the library or changing instances disconnects the viewer and keeps
the game running. Stopping an instance requires confirmation and preserves its
saved files. Stopped instances are hidden from the library; history remains in
the API and database.

Use **Administration → Your platform → Show desktop toolbar** to show or hide
Xpra's floating controls. Changes apply to open viewers within 15 seconds and do
not require rebuilding images or restarting games. `DESKTOP_TOOLBAR` in
`server/app.py` supplies the initial default when no administrator preference has
been saved. Hiding the toolbar changes the interface, not the underlying Xpra
features.

### Invitations and player limits

Registration requires an invitation by default. Under **Administration →
Invitations**, create a code with a label, usage limit, and expiration. Copy it
when it is shown: only its hash is stored, and it cannot be displayed again.
Share it with the player, who enters it in the registration form or uses the CLI
`register --invite CODE` option. Used-up, revoked, and expired codes are rejected.
Existing accounts can still sign in without a code. Disable **Require an
invitation code** for open registration, or disable **Allow account registration**
to close registration entirely.

The platform limits total concurrent instances and instances per account. Each
game also has an availability switch, a per-player instance cap (0 blocks access),
and a fixed player resolution. Under **Accounts → Game access and instance
limits**, override an account's total allowance and specify how many instances of
each game it may launch. With an explicit game list, games not on the list are
blocked. Inheriting library access applies the default limits to current and new
games. The most restrictive platform, account, and game limits apply; changes
restrict future launches without interrupting current games. Administrators may
choose from a game's configured resolutions and bypass game access restrictions,
but still obey the platform's global and per-account concurrent limits.

### Session networks

Game networks are internal by default: the portal can reach each desktop, but
games cannot reach the Internet or sibling game networks. This also preserves
isolation when using OrbStack for the local demo. For a game that needs downloads,
authentication, or online multiplayer, enable **Advanced settings → Allow internet
access** (`internet_access: true` in its profile). Use a native Linux Docker host
for Internet-enabled games: OrbStack permits traffic between ordinary bridges,
so separate non-internal networks alone do not provide sibling isolation there.
Network changes apply to newly launched instances.

### Inactivity cleanup

**Stop inactive instances after (minutes)** defaults to 30; 0 disables cleanup.
Mouse, touch, wheel, and keyboard input in the player page update the instance's
activity timestamp. An idle tab, a connected WebSocket, and game animation do not
keep it alive. Each instance has its own timer, including background instances.
The player warns during the final minute; the server checks every 15 seconds and
stops expired instances while retaining their saved files. Timestamps and settings
persist across portal restarts. Unsubmitted progress inside the game can be lost
when an inactive instance stops; choose a timeout appropriate for the game.

- The `gamedock_gamedock-data` volume stores SQLite data: accounts, scrypt password
  hashes, revocable tokens, profiles, configuration, and instance history.
- `NAMESPACE-user-UID-GAME` persists `/data`. The namespace defaults to the Compose
  project name (`gamedock`). Set `GAMEDOCK_NAMESPACE` explicitly using 1–40 lowercase
  letters, digits, underscores, or hyphens. Keep it stable and use distinct names
  for deployments that must not share files. Multiple sessions for the same
  account and game share files. For games that lock their profiles, set the
  per-user limit to 1 or use separate profiles. Save before stopping an instance:
  stopping removes the container but preserves its volume.
- State is reconciled with Docker when listing or creating instances. Recreating
  the portal preserves desktops and accounts. Signing out revokes desktop access
  without terminating the game. Disabling an account revokes its tokens and
  terminates its instances.
- `docker compose logs -f portal` shows operational errors without printing tokens
  or passwords. Stop instances through Administration before removing the
  platform: `docker compose down` stops the portal, not its session containers.
- Back up SQLite consistently along with game volumes. Do not commit `.env`,
  databases, tokens, or game clients. Source files and build instructions are
  fully defined by the repository.

## API

Mutations require `Content-Type: application/json`; send `{}` for requests with no
fields. Authenticate with an HttpOnly cookie or `Authorization: Bearer TOKEN`.
Do not put tokens in URLs. Other users' instances return 404; administrators can
manage all instances.

| Method     | Route                                   | Purpose                                                       |
| ---------- | --------------------------------------- | ------------------------------------------------------------- |
| GET        | `/api/catalog`                          | Public settings, account, and games                           |
| POST       | `/api/auth/register`, `/api/auth/login` | `{username, password}`                                        |
| POST       | `/api/logout`                           | Revoke the current session                                    |
| GET / POST | `/api/instances`                        | List / create with `{game, resolution}`                       |
| DELETE     | `/api/instances/ID`                     | Stop an instance                                              |
| GET        | `/play/ID`                              | Centered player and instance navigation                       |
| POST       | `/api/instances/ID/activity`            | Record user input for inactivity cleanup                      |
| GET        | `/api/instances/ID`                     | Owned instance status and dimensions                          |
| GET / WS   | `/desktop/ID/…`                         | Authenticated desktop access                                  |
| PUT        | `/api/admin/settings`                   | Name, banners, registration, limits                           |
| PUT        | `/api/admin/games`                      | Create or replace a profile                                   |
| DELETE     | `/api/admin/games/ID`                   | Remove a profile                                              |
| GET        | `/api/admin/users`                      | List accounts                                                 |
| PATCH      | `/api/admin/users/ID`                   | `{enabled: true/false}` or `{policy: {max_instances, games}}` |
| GET / POST | `/api/admin/invitations`                | List metadata / create an invitation                          |
| DELETE     | `/api/admin/invitations/ID`             | Revoke an invitation                                          |

## Validation

Run the complete suite on Linux using only the dedicated Docker QA project:

```sh
./scripts/qa.sh
```

Requires Python 3 and Docker Compose with `--wait`. QA credentials remain outside
the repository, and screenshots are written to `/tmp/gamedock-artifacts`. The
suite verifies that recreating the portal does not restart games and that volumes
survive instance replacement. Run browser tests sequentially on a stable Docker
network; do not use host networking while creating session networks.

```sh
docker build -t gamedock-portal:local .
docker run --rm -v "$PWD:/app:ro" gamedock-portal:local python -m unittest discover -s tests -v
```

`tests/live.py` checks the API and CLI, native commands, two real desktops, Xvfb
resolutions, persistence, proxying, isolation, and port exposure. Run it on the
host with Python 3 and the Docker CLI against a disposable QA deployment at
localhost:18088. It reads bootstrap credentials from `/tmp/gamedock-qa.env`.
Do not run it against real accounts. `tests/browser.py` checks registration,
launching, rendered desktop pixels, real keyboard input, WebSocket revocation,
termination, and mobile layout. `tests/game_browser.py` checks administration
forms, game creation, invitations, player access, live toolbar settings, and a
real OpenTTD session. `tests/idle_live.py` verifies the actual inactivity worker
against a Docker instance with a one-minute timeout. Build the browser environment
with `tests/Dockerfile.browser`; screenshots are written to `/artifacts`. The QA
portal uses `PUBLIC_URL=http://gamedock-qa-portal-1:8080`, passed to the browser as
`QA_URL`; the QA CLI connects through loopback:18088.
