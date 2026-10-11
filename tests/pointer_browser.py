"""Validate remote pointer coordinates through scaling and both fullscreen controls."""

import http.client
import json
import socket
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD, rendered


def docker(method, path, body=None):
    connection = http.client.HTTPConnection("localhost")
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.connect("/var/run/docker.sock")
    connection.request(
        method,
        "/v1.45" + path,
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    result = response.read()
    connection.close()
    assert response.status < 400, result
    return result


def run(sid, command):
    item = json.loads(
        docker(
            "POST",
            "/containers/gamedock-" + sid + "/exec",
            {"Cmd": command, "AttachStdout": True, "AttachStderr": True},
        )
    )
    data = docker(
        "POST", "/exec/" + item["Id"] + "/start", {"Detach": False, "Tty": False}
    )
    # Docker frames stdout/stderr using an eight-byte header.
    result = b""
    while len(data) >= 8:
        length = int.from_bytes(data[4:8], "big")
        result += data[8 : 8 + length]
        data = data[8 + length :]
    code = json.loads(docker("GET", "/exec/" + item["Id"] + "/json"))["ExitCode"]
    assert code == 0, result.decode(errors="replace")
    return result.decode()


POINTER_QUERY = """
import ctypes as c, json
x = c.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [c.c_char_p]
x.XOpenDisplay.restype = c.c_void_p
d = x.XOpenDisplay(b':0')
assert d
x.XDefaultRootWindow.argtypes = [c.c_void_p]
x.XDefaultRootWindow.restype = c.c_ulong
root = x.XDefaultRootWindow(d)
a, b = c.c_ulong(), c.c_ulong()
rx, ry, wx, wy, mask = c.c_int(), c.c_int(), c.c_int(), c.c_int(), c.c_uint()
x.XQueryPointer.argtypes = [c.c_void_p, c.c_ulong] + [c.c_void_p] * 7
assert x.XQueryPointer(d, root, c.byref(a), c.byref(b), c.byref(rx), c.byref(ry), c.byref(wx), c.byref(wy), c.byref(mask))
print(json.dumps([rx.value, ry.value]))
x.XCloseDisplay.argtypes = [c.c_void_p]
x.XCloseDisplay(d)
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1800, "height": 1000})
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("link", name="Administration", exact=True)).to_be_visible()
    response = page.request.post(URL + "/api/instances", data={"game": "desktop"})
    assert response.ok, response.text()
    sid = response.json()["id"]
    try:
        page.goto(URL + "/play/" + sid)
        remote = rendered(page)
        remote.evaluate("""() => {
            window.qaPointers = [];
            const send = client.send;
            client.send = function(packet) {
                if (['pointer-position', 'button-action'].includes(packet[0])) qaPointers.push(packet);
                return send.call(this, packet);
            };
        }""")

        def check(label):
            page.wait_for_timeout(350)
            assert remote.evaluate("[innerWidth, innerHeight]") == [1280, 720], label
            canvas = remote.locator("canvas").first
            assert canvas.evaluate("c => [c.width, c.height]") == [1280, 720], label
            box = canvas.bounding_box()
            for fx, fy in [(0.15, 0.2), (0.5, 0.5), (0.85, 0.8)]:
                expected = [round(1280 * fx), round(720 * fy)]
                remote.evaluate("qaPointers.length = 0")
                page.mouse.click(
                    box["x"] + box["width"] * fx, box["y"] + box["height"] * fy
                )
                page.wait_for_timeout(150)
                packets = remote.evaluate("qaPointers")
                moves = [
                    packet[2][:2]
                    for packet in packets
                    if packet[0] == "pointer-position"
                ]
                clicks = [
                    packet[4][:2] for packet in packets if packet[0] == "button-action"
                ]
                assert moves and len(clicks) == 2, (label, packets)
                actual = json.loads(run(sid, ["python3", "-c", POINTER_QUERY]))
                for point in [*moves, *clicks, actual]:
                    assert all(abs(a - b) <= 2 for a, b in zip(point, expected)), (
                        label,
                        expected,
                        point,
                    )
            print("PASS:", label, flush=True)

        for mode in ["fit", "original", "integer"]:
            page.locator("#player-settings-toggle").click()
            page.locator("#viewer-scale").select_option(mode)
            page.locator("#player-settings-close").click()
            check(mode)
            # Enter through Xpra; exit using the outer header.
            remote.locator("#fullscreen_button").click()
            page.wait_for_function("document.fullscreenElement === document.body")
            check(mode + " Xpra fullscreen")
            page.locator("#fullscreen").click()
            page.wait_for_function("!document.fullscreenElement")
            check(mode + " exit")
        page.locator("#fullscreen").click()
        page.wait_for_function("document.fullscreenElement === document.body")
        check("header fullscreen")
        remote.locator("#fullscreen_button").click()
        page.wait_for_function("!document.fullscreenElement")
        page.set_viewport_size({"width": 900, "height": 650})
        check("smaller viewport")
        page.screenshot(path=str(ARTIFACTS / "pointer-alignment.png"))
    finally:
        page.request.delete(URL + "/api/instances/" + sid, data={})
        browser.close()
print(
    "PASS: source resolution, motion/click packets and actual X11 pointer stay aligned"
)
