"""Real HTTPS, H.264 decoding and effective Xpra bandwidth budget."""

import os
import http.client
import json
import socket
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD


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
    browser = p.chromium.launch(
        headless=True, executable_path=os.getenv("QA_BROWSER_EXECUTABLE") or None
    )
    context = browser.new_context(
        ignore_https_errors=True, viewport={"width": 1500, "height": 950}
    )
    page = context.new_page()
    page.goto(URL)
    assert page.evaluate("isSecureContext && typeof VideoDecoder !== 'undefined'")
    support = page.evaluate(
        "VideoDecoder.isConfigSupported({codec:'avc1.42C01E',codedWidth:1280,codedHeight:720})"
    )
    expect_h264 = os.getenv("QA_EXPECT_H264", "1") == "1"
    assert support["supported"] == expect_h264, support
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("link", name="Administration", exact=True)).to_be_visible()
    profile = {
        "id": "bandwidth-qa",
        "name": "Bandwidth QA",
        "image": "gamedock-runtime:bandwidth-qa",
        "command": ["glxgears", "-geometry", "1280x720+0+0"],
        "resolutions": ["1280x720"],
        "streaming": {
            "bandwidth_mbps": 6,
            "bandwidth_detection": True,
            "encoding": "h264",
            "encodings": "h264,webp,jpeg",
            "video_encoders": "openh264",
            "csc_modules": "libyuv",
            "quality": 0,
            "min_quality": 30,
            "min_speed": 80,
            "refresh_rate": 20,
            "metrics_interval": 1,
        },
    }
    saved = page.request.put(URL + "/api/admin/games", data=profile)
    assert saved.ok, saved.text()
    response = page.request.post(URL + "/api/instances", data={"game": profile["id"]})
    assert response.ok, response.text()
    sid = response.json()["id"]
    try:
        page.goto(URL + "/play/" + sid)
        page.wait_for_function(
            "document.querySelector('#desktop-frame').contentWindow?.client?.connected",
            timeout=60000,
        )
        remote = page.locator("#desktop-frame").element_handle().content_frame()
        remote.locator("canvas").first.wait_for()

        page.locator("#player-settings-toggle").click()
        page.locator("#diagnostics-toggle").click()
        expect(page.locator('[data-metric="h264_status"]')).to_have_text(
            "Receiving H.264"
            if expect_h264
            else "Unavailable: browser decoder not supported",
            timeout=45000,
        )
        expect(page.locator('[data-metric="decoded_fps"]')).not_to_have_text(
            "—", timeout=10000
        )
        page.wait_for_timeout(12000)
        info = run(sid, ["xpra", "info", ":0"])
        (ARTIFACTS / "bandwidth-info.txt").write_text(info)
        assert "client.0.bandwidth.limit=6000000" in info, info
        assert "client.0.window.1.bandwidth-limit=6000000" in info, info
        assert "video-max-size=(1280, 720)" in info, info
        expect(page.locator('[data-metric="decode_errors"]')).to_have_text("0")
        before = float(
            page.locator('[data-metric="game_rss_mb"]').inner_text().split()[0]
        )
        orphan = run(
            sid,
            [
                "python3",
                "-c",
                """
import os, ctypes, time
pid = os.fork()
if pid:
    print(pid, flush=True)
    os._exit(0)
for fd in (0,1,2): os.close(fd)
ctypes.CDLL(None).prctl(15, b'Dofus.exe', 0, 0, 0)
data = bytearray(160*1024**2)
for i in range(0, len(data), 4096): data[i] = 1
time.sleep(60)
""",
            ],
        ).strip()
        assert orphan.isdigit(), orphan
        parent = run(
            sid,
            [
                "python3",
                "-c",
                f"from pathlib import Path; s=Path('/proc/{orphan}/stat').read_text(); print(s[s.rindex(')')+2:].split()[1])",
            ],
        ).strip()
        assert parent == "1", parent
        page.wait_for_function(
            "before => parseFloat(document.querySelector('[data-metric=game_rss_mb]').textContent) > before + 120",
            arg=before,
            timeout=15000,
        )
        assert (
            float(page.locator('[data-metric="game_pss_mb"]').inner_text().split()[0])
            > 120
        )
        assert (
            float(
                page.locator('[data-metric="container_memory_mb"]')
                .inner_text()
                .split()[0]
            )
            > 160
        )
        print(
            "PASS: real orphan process adopted by PID 1 appears in game RSS/PSS and cgroup memory",
            flush=True,
        )
        page.screenshot(path=str(ARTIFACTS / "h264-https.png"))
        print(
            "METRICS",
            page.locator("[data-metric]").evaluate_all(
                "(els)=>Object.fromEntries(els.map(e=>[e.dataset.metric,e.textContent]))"
            ),
            flush=True,
        )
        print(
            "PASS: HTTPS codec capability/fallback, decoded frames, fixed client/window budgets and 720p negotiation",
            flush=True,
        )
    finally:
        page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.delete(URL + "/api/admin/games/" + profile["id"], data={})
        browser.close()
