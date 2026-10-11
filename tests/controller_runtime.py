import ctypes
import json
import time
import urllib.request

x = ctypes.CDLL("libX11.so.6")
x.XOpenDisplay.restype = ctypes.c_void_p
x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
d = x.XOpenDisplay(None)


def held():
    a = ctypes.create_string_buffer(32)
    x.XQueryKeymap(d, a)
    code = x.XKeysymToKeycode(d, ord("a"))
    return bool(a.raw[code // 8] & (1 << (code % 8)))


body = json.dumps({"axes": [-1, 0, 0, 0], "buttons": [False] * 17}).encode()
for attempt in range(30):
    try:
        result = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    "http://localhost:6085/",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
            )
        )
        break
    except OSError:
        time.sleep(0.2)
assert result["mode"] == "keyboard"
time.sleep(0.1)
assert held(), "A key not pressed"
time.sleep(1)
assert not held(), "Watchdog did not release A"
print(
    "PASS: HTTP controller input produces real X11 key state and watchdog releases it"
)
