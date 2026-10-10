"""Streaming UI and real Xpra sessions in the disposable QA project."""

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


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Administration", exact=True).click()
    page.locator("#admin-nav").get_by_role("link", name="Streaming", exact=True).click()
    original = page.request.get(URL + "/api/catalog").json()["settings"]
    form = page.locator("#streaming-settings")
    sid = None
    profile_id = "qa-streaming-overrides"
    try:
        schema = page.request.get(URL + "/api/catalog").json()["streaming_schema"]
        expect(form.locator("input, select")).to_have_count(len(schema))
        page.get_by_role("button", name="Sharp picture", exact=True).click()
        expect(form.get_by_label("Fixed quality", exact=True)).to_have_value("95")
        # A preset is a draft until explicitly saved.
        assert (
            page.request.get(URL + "/api/catalog").json()["settings"]["streaming"]
            == original["streaming"]
        )
        form.get_by_role("button", name="Save streaming settings").click()
        expect(
            page.get_by_text(
                "Streaming settings saved. They apply to new instances.", exact=True
            )
        ).to_be_visible()
        page.reload()
        expect(form.get_by_label("Fixed quality", exact=True)).to_have_value("95")
        # Inconsistent queue values are rejected without changing saved settings.
        form.get_by_label("Minimum frame queue (ms)").fill("100")
        form.get_by_role("button", name="Save streaming settings").click()
        expect(page.locator("#notice")).to_contain_text("minimum <= initial <= maximum")
        assert (
            page.request.get(URL + "/api/catalog").json()["settings"]["streaming"][
                "batch_min_delay"
            ]
            == 5
        )
        for label, key in (
            ("Balanced", "balanced"),
            ("Sharp picture", "sharp"),
            ("Dofus low latency", "low_latency"),
            ("Lossless picture", "lossless"),
        ):
            page.get_by_role("button", name=label, exact=True).click()
            form.get_by_role("button", name="Save streaming settings").click()
            expect(page.locator("#notice")).to_contain_text("Streaming settings saved")
            expected = page.request.get(URL + "/api/catalog").json()["settings"][
                "streaming"
            ]
            response = page.request.post(
                URL + "/api/instances", data={"game": "desktop"}
            )
            assert response.status == 201, response.text()
            sid = response.json()["id"]
            definition = json.loads(
                docker("GET", "/containers/gamedock-" + sid + "/json")
            )
            env = dict(
                item.split("=", 1)
                for item in definition["Config"]["Env"]
                if "=" in item
            )
            assert json.loads(env["GAMEDOCK_STREAMING"]) == expected
            viewer = context.new_page()
            viewer.goto(URL + "/play/" + sid)
            remote = rendered(viewer)
            assert remote.evaluate("innerWidth") == 1280
            info = run(sid, ["xpra", "info", ":0"])
            (ARTIFACTS / ("streaming-" + key + "-info.txt")).write_text(info)
            assert "display.xshm=True" in info, "Shared-memory capture was not active"
            assert "display.xshm-attached.segments=1" in info
            process = json.loads(
                run(
                    sid,
                    [
                        "python3",
                        "-c",
                        "import json,pathlib; print(json.dumps([p.read_bytes().replace(b'\\x00',b' ').decode() for p in pathlib.Path('/proc').glob('[0-9]*/cmdline') if b'xpra\\x00shadow' in p.read_bytes()]))",
                    ],
                )
            )
            command = next(item for item in process if "--daemon=no" in item)
            assert "--quality=" + str(expected["quality"]) in command
            assert "--min-quality=" + str(expected["min_quality"]) in command
            assert "--resize-display=no" in command
            assert "1280x720 pixels" in run(sid, ["xdpyinfo"])
            defaults = viewer.request.get(
                URL + "/desktop/" + sid + "/default-settings.txt"
            ).text()
            assert "min-quality = " + str(expected["min_quality"]) in defaults
            viewer.screenshot(path=str(ARTIFACTS / ("streaming-" + key + ".png")))
            # Hidden browser tabs must not leave Xpra's per-window queue idle.
            remote.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            canvas = remote.locator("canvas").first.bounding_box()
            viewer.mouse.click(
                canvas["x"] + canvas["width"] / 2, canvas["y"] + canvas["height"] / 2
            )
            viewer.keyboard.type(
                "printf streaming-" + key + " > /data/streaming-input.txt", delay=15
            )
            viewer.keyboard.press("Enter")
            viewer.wait_for_timeout(750)
            assert run(sid, ["cat", "/data/streaming-input.txt"]) == "streaming-" + key
            viewer.close()
            assert page.request.delete(URL + "/api/instances/" + sid, data={}).ok
            sid = None
        # A game can override capture and latency without changing platform defaults.
        profile = {
            "id": profile_id,
            "name": "Streaming overrides",
            "image": "gamedock-runtime:local",
            "command": ["xterm"],
            "streaming": {
                "xshm": False,
                "idle_fix": False,
                "socket_nodelay": False,
                "socket_cork": True,
            },
        }
        assert page.request.put(URL + "/api/admin/games", data=profile).ok
        response = page.request.post(URL + "/api/instances", data={"game": profile_id})
        assert response.status == 201, response.text()
        sid = response.json()["id"]
        viewer = context.new_page()
        viewer.goto(URL + "/play/" + sid)
        rendered(viewer)
        info = run(sid, ["xpra", "info", ":0"])
        assert "env.GAMEDOCK_IDLE_FIX=0" in info
        assert "env.XPRA_SHADOW_XSHM=0" in info
        assert "env.XPRA_SOCKET_CORK=1" in info
        viewer.close()
        assert page.request.delete(URL + "/api/instances/" + sid, data={}).ok
        sid = None
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(ARTIFACTS / "streaming-mobile.png"))
        assert not errors, errors
        print(
            "PASS: streaming controls, presets, validation, persistence, actual Xpra flags and XSHM capture, client defaults, rendered desktops, keyboard, unchanged resolution and mobile"
        )
    finally:
        if sid:
            page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.delete(URL + "/api/admin/games/" + profile_id, data={})
        page.request.put(URL + "/api/admin/settings", data=original)
        browser.close()
