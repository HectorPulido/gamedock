"""Floating notifications never resize or refocus the streamed desktop."""

import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("link", name="Administration", exact=True)).to_be_visible()
    catalog = page.request.get(URL + "/api/catalog").json()
    catalog["settings"]["idle_minutes"] = 0
    before = page.locator("main").bounding_box()
    page.evaluate("GameDockNotifications.show('Saved correctly.', {kind:'success'})")
    expect(page.locator("#notice")).to_contain_text("Saved correctly.")
    assert before == page.locator("main").bounding_box()
    page.get_by_role("button", name="Dismiss notification").click()
    expect(page.locator(".toast")).to_have_count(0)
    page.evaluate(
        "GameDockNotifications.show('Invalid configuration.', {kind:'error'})"
    )
    expect(page.locator(".toast.error")).to_contain_text("Invalid configuration.")
    page.get_by_role("button", name="Dismiss notification").click()
    page.mouse.move(0, 0)
    page.evaluate("GameDockNotifications.show('Short lived.', {duration:120})")
    expect(page.locator(".toast")).to_have_count(0)
    page.evaluate(
        "GameDockNotifications.remember('Instance stopped.', {kind:'success'})"
    )
    page.reload()
    expect(page.locator("#notice")).to_contain_text("Instance stopped.")
    page.get_by_role("button", name="Dismiss notification").click()
    page.reload()
    expect(page.locator(".toast")).to_have_count(0)

    # A deterministic mocked stream checks layout/focus and stopped polling without
    # launching/stopping any real user's Docker game or changing platform settings.
    instance = {
        "id": "qa-notification",
        "uid": catalog["user"]["id"],
        "game": catalog["games"][0]["id"],
        "status": "running",
        "resolution": "1280x720",
        "last_activity": 0,
    }
    page.route(
        "**/play/qa-notification",
        lambda route: route.fulfill(
            body=Path("web/player.html").read_text(), content_type="text/html"
        ),
    )
    page.route("**/api/catalog", lambda route: route.fulfill(json=catalog))
    page.route("**/api/instances", lambda route: route.fulfill(json=[instance]))
    page.route(
        "**/api/instances/qa-notification", lambda route: route.fulfill(json=instance)
    )
    page.route(
        "**/api/instances/qa-notification/activity",
        lambda route: route.fulfill(json={"ok": True}),
    )
    page.route(
        "**/desktop/qa-notification/**",
        lambda route: route.fulfill(
            body='<canvas width="1280" height="720" tabindex="0"></canvas>',
            content_type="text/html",
        ),
    )
    # Route local assets too: Chromium classifies a fulfilled navigation as public
    # and otherwise blocks Docker-LAN subresources under its local-network policy.
    page.route(
        "**/assets/*",
        lambda route: route.fulfill(
            body=Path("web", route.request.url.rsplit("/", 1)[-1]).read_text(),
            content_type="text/css"
            if route.request.url.endswith(".css")
            else "text/javascript",
        ),
    )
    page.goto(URL + "/play/qa-notification")
    expect(page.locator("#desktop-frame")).to_have_attribute(
        "src", re.compile(r"/desktop/qa-notification/")
    )
    page.frame_locator("#desktop-frame").locator("canvas").focus()
    before = page.locator("#desktop-stage").bounding_box()
    page.evaluate(
        "GameDockNotifications.show('Connection recovered.', {key:'recovered'})"
    )
    assert page.evaluate("document.activeElement.id") == "desktop-frame"
    assert before == page.locator("#desktop-stage").bounding_box()
    page.screenshot(path=str(ARTIFACTS / "notifications-player.png"))
    page.get_by_role("button", name="Dismiss notification").click()
    page.evaluate(
        "GameDockNotifications.show('Connection recovered.', {key:'recovered'})"
    )
    expect(page.locator(".toast")).to_have_count(0)
    page.locator("#fullscreen").click()
    page.wait_for_function("!!document.fullscreenElement")
    page.evaluate("GameDockNotifications.show('Fullscreen notification.')")
    expect(page.locator(".toast")).to_be_visible()
    assert page.evaluate(
        "document.fullscreenElement.contains(document.querySelector('.toast'))"
    )
    page.evaluate("document.exitFullscreen()")
    page.get_by_role("button", name="Dismiss notification").click()
    instance["status"] = "stopped"
    page.evaluate("refresh()")
    expect(page.locator(".desktop-stopped")).to_be_visible()
    expect(page.locator("#desktop-frame")).to_be_hidden()
    assert page.locator("#desktop-frame").get_attribute("src") is None
    expect(page.locator(".toast")).to_contain_text("This instance has stopped.")
    page.get_by_role("button", name="Dismiss notification").click()
    page.evaluate("refresh()")
    expect(page.locator(".toast")).to_have_count(0)
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("GameDockNotifications.show('Mobile notification.')")
    page.locator(".toast").evaluate(
        "async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)); }"
    )
    bounds = page.locator(".toast").bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
    page.screenshot(path=str(ARTIFACTS / "notifications-mobile.png"))
    assert not errors, errors
    browser.close()
print(
    "Floating notifications: expiry, dismiss, dedup, navigation, layout, focus, mobile/fullscreen passed"
)
