"""Exercise network settings against local portal, cleaning up the QA profile."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from browser_helpers import rendered

url = os.getenv("QA_URL", "http://localhost:8080")
values = dict(
    line.split("=", 1)
    for line in Path("/qa.env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
profile = {
    "id": "network-ui-qa",
    "name": "Network UI QA",
    "image": "gamedock-runtime:local",
    "command": ["xterm"],
}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    response = context.request.post(
        url + "/api/auth/login",
        data={
            "username": values.get("ADMIN_USER", "admin"),
            "password": values["ADMIN_PASSWORD"],
        },
    )
    assert response.ok, response.status
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sid = None
    try:
        page.goto(url + "/admin#games")
        expect(page.locator("#admin-workspace")).to_be_visible()
        page.get_by_role("button", name="New game", exact=True).click()
        page.locator("[name=definition]").fill(json.dumps(profile))
        page.locator("[name=network_mode]").select_option("allowlist")
        page.locator("[name=network_allow]").fill(
            "192.168.0.7/32 5555 tcp\n1.1.1.1/32 443 tcp"
        )
        page.locator("[name=network_deny]").fill("192.168.0.8/32")
        with page.expect_response(
            lambda r: r.url.endswith("/api/admin/games") and r.request.method == "PUT"
        ) as result:
            page.get_by_role("button", name="Save game", exact=True).click()
        assert result.value.ok, result.value.text()
        saved = result.value.json()["network_policy"]
        assert (
            saved["mode"] == "allowlist"
            and len(saved["allow"]) == 2
            and saved["deny"] == ["192.168.0.8/32"]
        ), saved
        expect(page.locator("[name=network_mode]")).to_have_value("allowlist")
        page.locator("[name=network_allow]").scroll_into_view_if_needed()
        page.screenshot(path="/artifacts/network-settings.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors, errors
        if os.getenv("NETWORK_LAUNCH_QA") == "1":
            started = context.request.post(
                url + "/api/instances", data={"game": profile["id"]}, timeout=60000
            )
            assert started.status == 201, started.text()
            sid = started.json()["id"]
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(url + "/play/" + sid)
            rendered(page, 2)
            controls = context.request.post(
                url + "/desktop/" + sid + "/gamedock-controller",
                data={"axes": [0, 0, 0, 0], "buttons": [False] * 17},
            )
            assert controls.ok, controls.text()
            print(
                "PASS: real Xpra desktop rendered through firewall; controller forwarding works"
            )
        print(
            "PASS: administrator network mode, exceptions, blocked destinations, persistence, mobile width, no JS errors"
        )
    finally:
        if sid:
            context.request.delete(url + "/api/instances/" + sid, data={})
        context.request.delete(url + "/api/admin/games/" + profile["id"], data={})
        browser.close()
