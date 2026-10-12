"""Real 540p Xpra decoding, client FSR, source input and fullscreen QA."""
import json
import os
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

URL = os.getenv("QA_URL", "http://localhost:18090")
PASSWORD = os.getenv("QA_PASSWORD", "fsr-qa-password")
origin = urlsplit(URL)
assert (
    origin.hostname in {"localhost", "127.0.0.1"} and origin.port == 18090
), "This destructive QA fixture only accepts the isolated local portal on port 18090."
assert origin.scheme in {"http", "https"} and origin.path in {"", "/"}
assert not origin.query and not origin.fragment and not origin.username
with sync_playwright() as p:
    browser = p.chromium.launch(
        args=[
            "--no-sandbox",
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
        ]
    )
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("console", lambda m: print("CONSOLE", m.text, flush=True))
    page.on("pageerror", lambda e: print("ERROR", e, flush=True))
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_selector('a[href="/admin"]')
    profile = {
        "id": "fsr-540-qa",
        "name": "FSR 540p QA",
        "image": "gamedock-runtime:local",
        "command": ["xterm"],
        "resolutions": ["960x540"],
        "default_resolution": "960x540",
        "streaming": {"canvas_filter": "fsr"},
    }
    sid = None
    try:
        response = page.request.put(URL + "/api/admin/games", data=profile)
        assert response.ok, response.text()
        response = page.request.post(
            URL + "/api/instances", data={"game": "fsr-540-qa"}
        )
        assert response.ok, response.text()
        sid = response.json()["id"]
        page.goto(URL + "/play/" + sid)
        try:
            page.wait_for_function(
                'document.querySelector("iframe").contentDocument.querySelector(".fsr-overlay")?.width > 960',
                timeout=60000,
            )
        except Exception:
            print(
                page.evaluate(
                    '({sample:viewer.sample(),filter:filterControl.value,src:frame.src,hidden:frame.contentDocument?.hidden,canvases:[...(frame.contentDocument?.querySelectorAll("canvas")||[])].map(c=>[c.width,c.height,c.getBoundingClientRect().width])})'
                ),
                flush=True,
            )
            page.screenshot(path="/artifacts/fsr-error.png")
            raise
        remote = page.locator("#desktop-frame").element_handle().content_frame()
        assert remote.evaluate("[innerWidth,innerHeight]") == [960, 540]
        remote.evaluate(
            """() => { window.qaPointers=[];const send=client.send;client.send=function(packet){if(['pointer-position','button-action'].includes(packet[0]))qaPointers.push(packet);return send.call(this,packet);}; }"""
        )
        results = []
        for mode in ["smooth", "crisp", "fsr"]:
            page.locator("#player-settings-toggle").click()
            page.locator("#canvas-filter").select_option(mode)
            page.locator("#player-settings-close").click()
            page.wait_for_timeout(1000)
            assert remote.locator("canvas").first.evaluate("c=>[c.width,c.height]") == [
                960,
                540,
            ]
            if mode == "fsr":
                page.wait_for_function('viewer.sample().scaler.mode === "fsr"')
                assert (
                    page.locator("iframe")
                    .content_frame.locator(".fsr-overlay")
                    .is_visible()
                )
            else:
                assert (
                    page.locator("iframe").content_frame.locator(".fsr-overlay").count()
                    == 0
                )
            page.screenshot(path="/artifacts/xpra-540-" + mode + ".png")
            results.append(page.evaluate("viewer.sample().scaler"))
        for fullscreen in [False, True, False]:
            if fullscreen != bool(page.evaluate("!!document.fullscreenElement")):
                page.locator("#fullscreen").click()
                page.wait_for_timeout(500)
            canvas = remote.locator("canvas").first
            box = canvas.bounding_box()
            for fx, fy in [(0.15, 0.2), (0.5, 0.5), (0.85, 0.8)]:
                remote.evaluate("qaPointers.length=0")
                page.mouse.click(
                    box["x"] + box["width"] * fx, box["y"] + box["height"] * fy
                )
                page.wait_for_timeout(150)
                points = remote.evaluate(
                    'qaPointers.filter(p=>p[0]==="button-action").map(p=>p[4].slice(0,2))'
                )
                assert len(points) == 2, points
                for point in points:
                    assert (
                        abs(point[0] - 960 * fx) <= 2 and abs(point[1] - 540 * fy) <= 2
                    ), (point, fx, fy)
            assert canvas.evaluate("c=>[c.width,c.height]") == [960, 540]
        remote.locator("#fullscreen_button").click()
        page.wait_for_function("document.fullscreenElement === document.body")
        page.locator("#fullscreen").click()
        page.wait_for_function("!document.fullscreenElement")
        assert remote.locator(".fsr-overlay").is_visible()
        print("PASS: Xpra toolbar remains reachable above FSR presentation", flush=True)
        print(json.dumps(results), flush=True)
        print(
            "PASS: real Xpra 960x540 stays 540p; FSR presentation, fallback filters, fit/fullscreen pointer packets",
            flush=True,
        )
    finally:
        if sid is not None:
            page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.delete(URL + "/api/admin/games/fsr-540-qa")
        browser.close()
