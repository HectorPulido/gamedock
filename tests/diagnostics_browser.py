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
    context = browser.new_context(viewport={"width": 2000, "height": 1200})
    page = context.new_page()
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("link", name="Administration", exact=True)).to_be_visible()
    original = page.request.get(URL + "/api/catalog").json()["settings"]
    sid = None
    try:
        configured = dict(original)
        configured["streaming"] = dict(
            original["streaming"],
            metrics_interval=1,
            diagnostics_enabled=True,
            viewer_scale="integer",
            canvas_filter="crisp",
            restore_focus=True,
        )
        saved = page.request.put(
            URL + "/api/admin/settings", data={"streaming": configured["streaming"]}
        )
        assert saved.ok, saved.text()
        response = page.request.post(URL + "/api/instances", data={"game": "desktop"})
        assert response.status == 201, response.text()
        sid = response.json()["id"]
        page.goto(URL + "/play/" + sid)
        remote = rendered(page)
        box = remote.locator("canvas").first.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.keyboard.type(
            "timeout 10 sh -c 'i=0; while :; do i=$((i+1)); echo stream-frame-$i; sleep 0.03; done'",
            delay=5,
        )
        page.keyboard.press("Enter")
        page.locator("#diagnostics-toggle").click()
        for metric in ("capture_fps", "delivered_fps", "decoded_fps", "image_mbps"):
            page.wait_for_function(
                "key => parseFloat(document.querySelector('[data-metric=\"'+key+'\"]').textContent)>0",
                arg=metric,
                timeout=12000,
            )
        expect(page.locator("#diagnostics-status")).to_contain_text("Live sample")
        assert "1280x720 pixels" in run(sid, ["xdpyinfo"])
        assert abs(page.locator("#desktop-frame").bounding_box()["width"] - 1280) < 2
        assert (
            remote.locator("canvas").first.evaluate(
                "c => getComputedStyle(c).imageRendering"
            )
            == "pixelated"
        )
        (ARTIFACTS / "diagnostics-info.txt").write_text(
            run(sid, ["xpra", "info", ":0"])
        )
        page.screenshot(path=str(ARTIFACTS / "diagnostics-live.png"))
        page.locator("#diagnostics-close").click()
        page.wait_for_timeout(11000)
        page.locator("#viewer-scale").select_option("fit")
        page.wait_for_timeout(200)
        page.keyboard.type("printf header-focus-ok > /data/header-focus.txt", delay=15)
        page.keyboard.press("Enter")
        page.wait_for_timeout(750)
        page.screenshot(path=str(ARTIFACTS / "focus-debug.png"))
        assert run(sid, ["cat", "/data/header-focus.txt"]) == "header-focus-ok"
        page.locator("#canvas-filter").select_option("smooth")
        page.wait_for_timeout(200)
        page.keyboard.type("printf filter-focus-ok > /data/filter-focus.txt", delay=15)
        page.keyboard.press("Enter")
        page.wait_for_timeout(750)
        assert run(sid, ["cat", "/data/filter-focus.txt"]) == "filter-focus-ok"
        remote.evaluate(
            "() => {window.qaInfoRequests=0; const original=client.send_info_request; client.send_info_request=function(){window.qaInfoRequests++;return original.apply(this,arguments)}}"
        )
        page.wait_for_timeout(2300)
        assert remote.evaluate("qaInfoRequests") == 0
        print(
            "PASS: real animated capture, delivery, decode, payload, integer scaling, filter, header keyboard focus and no hidden-panel polling"
        )
    finally:
        if sid:
            page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.put(
            URL + "/api/admin/settings", data={"streaming": original["streaming"]}
        )
        browser.close()
