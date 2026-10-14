# Controllers

New sessions on the updated runtime accept touch and browser Gamepad inputs.
Settings → Touch controls selects Automatic on mobile, On, or Off.
A separate USB/Bluetooth switch controls physical input; both preferences persist locally.
Automatic shows the multitouch overlay on coarse-pointer devices. Dual sticks (vendored NippleJS 1.0.2, MIT),
D-pad, console face buttons, shoulder/trigger buttons, L3/R3 and Start/Select can be used simultaneously.
A standard USB/Bluetooth controller is polled while the session has focus. Pair
it with the **client device**, press a button, then focus the game. The browser
must support standard Gamepad mapping; use HTTPS (localhost also qualifies).
There is currently one logical controller per session; no rumble support.

Default output is keyboard emulation, including on Mac/OrbStack. Left stick:
WASD; right stick/D-pad: arrows; A Space, B Escape, X E, Y Q; L/R Shift/Ctrl;
triggers Z/C; Select Tab, Start Enter; stick clicks R/F, Guide Escape.
Set these bindings in your game. This mode does not make a controller-only game
compatible with keyboard input. Settings shows which output backend is active.
The input receiver releases controls after 750 ms without a heartbeat.

## Native virtual gamepad (Linux operator opt-in)

Linux uinput creates a kernel input device. On a dedicated Linux gaming server:

1. Load the `uinput` module and ensure `/dev/uinput` exists.
2. Build the optional Linux backend image:
   `docker build -t gamedock-runtime:gamepad -f examples/controllers/Dockerfile .`
   and select `gamedock-runtime:gamepad` as the game profile's image in administration.
   Set `--build-arg BASE_IMAGE=your-gpu-or-game-image` to extend an existing game image.
3. Set `GAMEDOCK_UINPUT=1` in the portal's `.env`, recreate the portal and launch
   a new session. Runtime images must be rebuilt first. A missing host `/dev/uinput` prevents
   Docker from launching an opted-in session; leave the option off on that host.

Sessions get `/dev/uinput`, a private tmpfs `/dev/input`, input-event read access
and MKNOD/SETUID/SETGID/CHOWN capabilities for startup. The input helper creates
only its own event node in that private directory and drops to UID 1000 before
accepting input; the runtime drops to UID 1000 before launching Selkies or the game.
The host input directory is never mounted. If setup fails, keyboard mode is used.
Kernel devices are host-global: this option belongs on a trusted dedicated host,
not an isolation boundary against hostile game code. Docker Desktop/OrbStack
may not provide uinput; keyboard mode is the supported fallback there.

Validated locally: state validation and key release, browser touch/physical API
simulation, and X11 key delivery. Native uinput and physical controller hardware
require a Linux/hardware test; Wine/controller-only games also need validation.

References: [Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API/Using_the_Gamepad_API),
[Linux uinput](https://docs.kernel.org/input/uinput.html).

Browser QA: `docker run --rm -v "$PWD:/repo:ro" -v /tmp/gamedock-streaming-artifacts:/tmp/artifacts --entrypoint python gamedock-browser-qa:h264 /repo/tests/controller_browser.py`.
Runtime QA: copy `tests/controller_runtime.py` into a running test session and run it with Python.
