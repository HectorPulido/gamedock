"""Branding, themes, real resource limits and fullscreen in disposable QA only."""

import http.client
import json
import socket
import time
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD, rendered, centered


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
    data = response.read()
    connection.close()
    assert response.status < 400, data
    return data


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1200})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Administration", exact=True).click()
    page.locator("#admin-nav").get_by_role("link", name="Platform", exact=True).click()
    original = page.request.get(URL + "/api/catalog").json()["settings"]
    sid = None
    profile_id = "qa-customization"
    try:
        settings = page.locator("#settings")
        settings.get_by_label("Name", exact=True).fill("miservidor")
        settings.get_by_label("Default RAM per instance (MiB)").fill("1024")
        settings.get_by_label("Default CPU per instance", exact=True).fill("0.5")
        settings.get_by_role("button", name="Save settings", exact=True).click()
        expect(page.get_by_text("Settings saved.", exact=True)).to_be_visible()
        expect(page.locator("footer [data-platform-name]")).to_have_text("miservidor")
        expect(page).to_have_title("miservidor | Administration")
        page.locator("#admin-nav").get_by_role(
            "link", name="Appearance", exact=True
        ).click()
        # All presets persist and appear on the public sign-in page too.
        appearance = page.locator("#appearance")
        public = browser.new_page()
        for theme in ("classic", "midnight", "forest"):
            appearance.get_by_label("Theme", exact=True).select_option(theme)
            appearance.get_by_role("button", name="Save appearance", exact=True).click()
            expect(page.locator("#appearance-status")).to_have_text("Appearance saved.")
            public.goto(URL)
            expect(public.locator("#brand")).to_have_text("miservidor")
            public.wait_for_function(
                "t => document.documentElement.dataset.theme === t", arg=theme
            )
            public.screenshot(
                path=str(ARTIFACTS / ("theme-" + theme + ".png")), full_page=True
            )
        appearance.get_by_label("Accent", exact=True).fill("#315b9b")
        appearance.get_by_label("Logo image URL", exact=True).fill(
            URL + "/assets/banner.svg"
        )
        appearance.get_by_label("Footer message").fill("Welcome to miservidor")
        appearance.get_by_label("Corner radius (px)").fill("12")
        appearance.get_by_role("button", name="Preview", exact=True).click()
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
            )
            == "#315b9b"
        )
        # A preview must not affect other visitors.
        public.reload()
        public.wait_for_function("document.documentElement.dataset.theme === 'forest'")
        assert (
            public.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
            )
            == "#28664b"
        )
        appearance.get_by_role("button", name="Discard preview", exact=True).click()
        expect(appearance.get_by_label("Accent", exact=True)).to_have_value("#28664b")
        appearance.get_by_label("Accent", exact=True).fill("#315b9b")
        appearance.get_by_label("Logo image URL", exact=True).fill(
            URL + "/assets/banner.svg"
        )
        appearance.get_by_label("Footer message").fill("Welcome to miservidor")
        appearance.get_by_label("Corner radius (px)").fill("12")
        appearance.get_by_text("Advanced customization", exact=True).click()
        appearance.get_by_label("Custom CSS", exact=True).fill(
            "footer { letter-spacing: 1px; }"
        )
        with page.expect_download() as download:
            appearance.get_by_role("button", name="Export appearance").click()
        exported = ARTIFACTS / "appearance.json"
        download.value.save_as(exported)
        appearance.get_by_role("button", name="Reset to preset").click()
        page.locator("#import-theme").set_input_files(exported)
        expect(page.locator("#appearance-status")).to_have_text(
            "Appearance imported. Preview or save to apply."
        )
        appearance.get_by_role("button", name="Save appearance", exact=True).click()
        expect(page.locator("#appearance-status")).to_have_text("Appearance saved.")
        public.reload()
        expect(public.locator("#footer-message")).to_have_text("Welcome to miservidor")
        public.wait_for_function(
            "getComputedStyle(document.querySelector('footer')).letterSpacing === '1px'"
        )
        public.wait_for_function(
            "document.querySelector('.brand-logo').naturalWidth > 0"
        )
        # Create a real desktop via the editor; blank resource fields inherit.
        page.locator("#admin-nav").get_by_role("link", name="Games", exact=True).click()
        page.get_by_role("button", name="Add game", exact=True).click()
        form = page.locator("#profile")
        profile = {
            "id": profile_id,
            "name": "Customization desktop",
            "image": "gamedock-runtime:local",
            "command": ["xterm"],
            "resolutions": ["1280x720"],
        }
        form.get_by_label("JSON definition").fill(json.dumps(profile))
        form.get_by_role("button", name="Save game", exact=True).click()
        expect(page.get_by_text("Game saved.", exact=True)).to_be_visible()
        launched = page.request.post(URL + "/api/instances", data={"game": profile_id})
        assert launched.status == 201, launched.text()
        sid = launched.json()["id"]
        definition = json.loads(docker("GET", "/containers/gamedock-" + sid + "/json"))
        assert definition["HostConfig"]["Memory"] == 1024 * 1024**2
        assert definition["HostConfig"]["NanoCpus"] == 500000000
        assert page.request.delete(URL + "/api/instances/" + sid, data={}).ok
        sid = None
        # Per-game controls override both defaults in actual Docker configuration.
        card = page.locator("article").filter(
            has=page.get_by_role("heading", name=profile["name"], exact=True)
        )
        card.get_by_role("button", name="Edit", exact=True).click()
        form.get_by_label("Game RAM (MiB)").fill("1536")
        form.get_by_label("Game CPU", exact=True).fill("0.75")
        form.get_by_role("button", name="Save game", exact=True).click()
        expect(page.get_by_text("Game saved.", exact=True)).to_be_visible()
        launched = page.request.post(URL + "/api/instances", data={"game": profile_id})
        assert launched.status == 201, launched.text()
        sid = launched.json()["id"]
        definition = json.loads(docker("GET", "/containers/gamedock-" + sid + "/json"))
        assert definition["HostConfig"]["Memory"] == 1536 * 1024**2
        assert definition["HostConfig"]["NanoCpus"] == 750000000
        page.goto(URL + "/play/" + sid)
        remote = rendered(page)
        centered(page)
        expect(page.locator("#brand")).to_have_text("miservidor")
        page.locator("#viewer-scale").select_option("fit")
        assert page.locator("#desktop-frame").bounding_box()["width"] > 1280
        # The iframe's layout viewport and X display resolution remain fixed.
        assert remote.evaluate("innerWidth") == 1280

        def resolution():
            result = json.loads(
                docker(
                    "POST",
                    "/containers/gamedock-" + sid + "/exec",
                    {"Cmd": ["xdpyinfo"], "AttachStdout": True},
                )
            )
            return docker(
                "POST",
                "/exec/" + result["Id"] + "/start",
                {"Detach": False, "Tty": False},
            )

        assert b"1280x720 pixels" in resolution()
        page.locator("#viewer-scale").select_option("original")
        assert page.locator("#desktop-frame").bounding_box()["width"] == 1280
        page.locator("#viewer-scale").select_option("fit")
        canvas = remote.locator("canvas").first.bounding_box()
        page.mouse.click(
            canvas["x"] + canvas["width"] / 2, canvas["y"] + canvas["height"] / 2
        )
        page.keyboard.type(
            "printf scaled-input-ok > /data/customization-input.txt", delay=20
        )
        page.keyboard.press("Enter")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = json.loads(
                docker(
                    "POST",
                    "/containers/gamedock-" + sid + "/exec",
                    {
                        "Cmd": ["cat", "/data/customization-input.txt"],
                        "AttachStdout": True,
                    },
                )
            )
            if b"scaled-input-ok" in docker(
                "POST",
                "/exec/" + result["Id"] + "/start",
                {"Detach": False, "Tty": False},
            ):
                break
            page.wait_for_timeout(250)
        else:
            raise AssertionError("Scaled keyboard/mouse input did not reach xterm")
        page.get_by_role("button", name="Fullscreen", exact=True).click()
        page.wait_for_function("!!document.fullscreenElement")
        expect(page.locator("#fullscreen")).to_have_attribute("aria-pressed", "true")
        centered(page)
        assert b"1280x720 pixels" in resolution()
        page.screenshot(path=str(ARTIFACTS / "viewer-fullscreen.png"))
        page.get_by_role("button", name="Exit fullscreen", exact=True).click()
        page.wait_for_function("!document.fullscreenElement")
        page.reload()
        rendered(page)
        expect(page.locator("#viewer-scale")).to_have_value("fit")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        centered(page)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(ARTIFACTS / "viewer-mobile.png"))
        public.set_viewport_size({"width": 390, "height": 844})
        assert public.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        print(
            "PASS: branding, three themes, preview, CSS, logo, import/export, actual Docker limits, scaled input, unchanged resolution, fullscreen and mobile"
        )
    finally:
        if errors:
            print("Browser errors:", errors)
        page.screenshot(
            path=str(ARTIFACTS / "customization-last-page.png"), full_page=True
        )
        if sid:
            page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.delete(URL + "/api/admin/games/" + profile_id, data={})
        page.request.put(URL + "/api/admin/settings", data=original)
        browser.close()
