"""Session-local controller input. Never exposes a host port."""

import ctypes
import json
import math
import os
from pathlib import Path
import stat
import uuid
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BUTTON_KEYS = [
    "space",
    "Escape",
    "e",
    "q",
    "Shift_L",
    "Control_L",
    "z",
    "c",
    "Tab",
    "Return",
    "r",
    "f",
    "Up",
    "Down",
    "Left",
    "Right",
    "Escape",
]


def validate_state(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid controller state")
    axes = data.get("axes", [0] * 4)
    buttons = data.get("buttons", [False] * 17)
    if (
        not isinstance(axes, list)
        or len(axes) != 4
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1
            for v in axes
        )
        or not isinstance(buttons, list)
        or len(buttons) != 17
        or any(type(v) is not bool for v in buttons)
    ):
        raise ValueError("Invalid controller state")
    return axes, buttons


class Output:
    def __init__(self):
        self.mode = "keyboard"
        self.held = set()
        self.device = None
        UInputError = OSError
        try:
            from evdev import UInput, AbsInfo, ecodes as e
            from evdev.uinput import UInputError

            self.e = e
            self.keys = [
                e.BTN_SOUTH,
                e.BTN_EAST,
                e.BTN_WEST,
                e.BTN_NORTH,
                e.BTN_TL,
                e.BTN_TR,
                e.BTN_TL2,
                e.BTN_TR2,
                e.BTN_SELECT,
                e.BTN_START,
                e.BTN_THUMBL,
                e.BTN_THUMBR,
                e.BTN_DPAD_UP,
                e.BTN_DPAD_DOWN,
                e.BTN_DPAD_LEFT,
                e.BTN_DPAD_RIGHT,
                e.BTN_MODE,
            ]
            self.abs = [e.ABS_X, e.ABS_Y, e.ABS_RX, e.ABS_RY]
            name = "GameDock-" + uuid.uuid4().hex
            self.device = UInput(
                {
                    e.EV_KEY: self.keys,
                    e.EV_ABS: [
                        (axis, AbsInfo(0, -32767, 32767, 0, 256, 0))
                        for axis in self.abs
                    ]
                    + [
                        (e.ABS_Z, AbsInfo(0, 0, 32767, 0, 0, 0)),
                        (e.ABS_RZ, AbsInfo(0, 0, 32767, 0, 0, 0)),
                        (e.ABS_HAT0X, AbsInfo(0, -1, 1, 0, 0, 0)),
                        (e.ABS_HAT0Y, AbsInfo(0, -1, 1, 0, 0, 0)),
                    ],
                },
                name=name,
                vendor=0x045E,
                product=0x028E,
            )
            # Expose only this session's event node, never the host input directory.
            for _ in range(20):
                nodes = list(Path("/sys/class/input").glob("event*"))
                match = next(
                    (
                        node
                        for node in nodes
                        if (node / "device/name").read_text().strip() == name
                    ),
                    None,
                )
                if match:
                    major, minor = map(int, (match / "dev").read_text().split(":"))
                    os.mknod(
                        "/dev/input/event0",
                        stat.S_IFCHR | 0o600,
                        os.makedev(major, minor),
                    )
                    break
                time.sleep(0.05)
            else:
                raise OSError("Virtual input node not found")
            os.chown("/dev/input/event0", 1000, 1000)
            self.mode = "gamepad"
        except (ImportError, OSError, PermissionError, UInputError):
            if self.device:
                self.device.close()
                self.device = None
            self.x = ctypes.CDLL("libX11.so.6")
            self.xt = ctypes.CDLL("libXtst.so.6")
            self.x.XOpenDisplay.restype = ctypes.c_void_p
            self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
            self.x.XStringToKeysym.restype = ctypes.c_ulong
            self.x.XFlush.argtypes = [ctypes.c_void_p]
            self.xt.XTestFakeKeyEvent.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_ulong,
            ]
            self.display = self.x.XOpenDisplay(None)
            deadline = time.monotonic() + 20
            while not self.display and time.monotonic() < deadline:
                time.sleep(0.1)
                self.display = self.x.XOpenDisplay(None)
            if not self.display:
                raise RuntimeError("Controller cannot open display")

    def apply(self, axes, buttons):
        if self.device:
            for axis, value in zip(self.abs, axes):
                self.device.write(self.e.EV_ABS, axis, round(value * 32767))
            for key, value in zip(self.keys, buttons):
                self.device.write(self.e.EV_KEY, key, int(value))
            for axis, value in (
                (self.e.ABS_Z, int(buttons[6]) * 32767),
                (self.e.ABS_RZ, int(buttons[7]) * 32767),
                (self.e.ABS_HAT0X, int(buttons[15]) - int(buttons[14])),
                (self.e.ABS_HAT0Y, int(buttons[13]) - int(buttons[12])),
            ):
                self.device.write(self.e.EV_ABS, axis, value)
            self.device.syn()
            return
        held = {key for key, down in zip(BUTTON_KEYS, buttons) if down}
        for value, negative, positive in [
            (axes[0], "a", "d"),
            (axes[1], "w", "s"),
            (axes[2], "Left", "Right"),
            (axes[3], "Up", "Down"),
        ]:
            if value < -0.3:
                held.add(negative)
            if value > 0.3:
                held.add(positive)
        for key in self.held ^ held:
            code = self.x.XKeysymToKeycode(
                self.display, self.x.XStringToKeysym(key.encode())
            )
            self.xt.XTestFakeKeyEvent(self.display, code, int(key in held), 0)
        self.x.XFlush(self.display)
        self.held = held


def serve():
    output = Output()
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    lock = threading.Lock()
    last = [0.0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != "/viewers":
                self.send_error(404)
                return
            try:
                path = (
                    Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/gamedock-runtime"))
                    / "viewers.json"
                )
                data = json.loads(path.read_text())
                if not 0 <= time.time() - data["updated"] <= 5:
                    raise ValueError("Stale presence")
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError, KeyError, TypeError):
                self.send_error(503, "Viewer presence unavailable")

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048:
                    raise ValueError("Invalid length")
                axes, buttons = validate_state(json.loads(self.rfile.read(length)))
                with lock:
                    output.apply(axes, buttons)
                    last[0] = time.monotonic()
                body = json.dumps({"mode": output.mode}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, TypeError, AttributeError):
                self.send_error(400)

    def watchdog():
        while True:
            time.sleep(0.1)
            with lock:
                if last[0] and time.monotonic() - last[0] > 0.75:
                    output.apply([0] * 4, [False] * 17)
                    last[0] = 0

    threading.Thread(target=watchdog, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 6085), Handler).serve_forever()


if __name__ == "__main__":
    serve()
