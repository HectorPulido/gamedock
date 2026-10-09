"""Real OpenTTD session and administrator UI against disposable QA."""

import os
from pathlib import Path
import secrets
import time
from playwright.sync_api import sync_playwright

url = os.getenv("QA_URL", "http://localhost:18088")
password = next(
    line.split("=", 1)[1]
    for line in Path("/qa.env").read_text().splitlines()
    if line.startswith("ADMIN_PASSWORD=")
)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(url)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_text("Administration", exact=True).click()
    page.locator("#settings").get_by_label("Name", exact=True).fill("GameDock Playroom")
    page.locator("#settings").get_by_label("Banner / welcome message").fill(
        "Independent desktops for your community."
    )
    page.locator("#settings").get_by_label("Banner image (optional URL)").fill(
        url + "/assets/banner.svg"
    )
    page.get_by_role("button", name="Save settings").click()
    page.get_by_text("Settings saved.", exact=True).wait_for()
    page.get_by_role("heading", name="GameDock Playroom", exact=True).wait_for()
    page.locator("#intro-banner").wait_for(state="visible")
    page.wait_for_function("document.querySelector('#intro-banner').naturalWidth > 0")
    page.locator("#profile").get_by_label("JSON definition").fill(
        Path("examples/openttd/profile.json").read_text()
    )
    page.get_by_role("button", name="Save game", exact=True).click()
    page.get_by_text("Game saved.", exact=True).wait_for()
    page.get_by_role("heading", name="OpenTTD", exact=True).wait_for()
    page.screenshot(path="/artifacts/admin.png", full_page=True)
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.get_by_label("Username", exact=True).fill("game_" + secrets.token_hex(4))
    page.get_by_label("Password", exact=True).fill(secrets.token_urlsafe(20))
    page.get_by_role("button", name="Create account", exact=True).click()
    page.get_by_role("heading", name="OpenTTD", exact=True).wait_for()
    page.locator("article").filter(
        has=page.get_by_role("heading", name="OpenTTD", exact=True)
    ).get_by_role("button", name="Launch instance").click()
    page.get_by_role("link", name="Connect").wait_for(timeout=60000)
    with page.expect_popup() as popup:
        page.get_by_role("link", name="Connect").click()
    desktop = popup.value
    failures = []
    desktop.on("pageerror", lambda e: failures.append(str(e)))
    desktop.on("requestfailed", lambda r: failures.append(r.url + " " + str(r.failure)))
    desktop.on(
        "response",
        lambda r: failures.append(str(r.status) + " " + r.url)
        if r.status >= 400
        else None,
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = desktop.goto(desktop.url)
        if response.status == 200:
            break
        time.sleep(0.5)
    try:
        desktop.wait_for_function(
            """() => [...document.querySelectorAll('canvas')].some(c => {
          if(c.width < 640 || c.height < 480) return false;
          const ctx=c.getContext('2d'); if(!ctx) return false;
          const data=ctx.getImageData(0,0,c.width,c.height).data; const colors=new Set();
          for(let i=0;i<data.length;i+=160) if(data[i+3]) colors.add(data.slice(i,i+4).join(','));
          return colors.size>30;
        })""",
            timeout=45000,
        )
        desktop.screenshot(path="/artifacts/openttd.png", full_page=True)
    finally:
        desktop.screenshot(path="/artifacts/openttd-debug.png", full_page=True)
        print("Asset failures:", failures)
        print("Game viewer:", desktop.locator("body").inner_text()[:1000])
    page.on("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Stop", exact=True).click()
    page.get_by_text("Stopped", exact=False).wait_for()
    browser.close()
print(
    "PASS: admin name/banner/profile forms, OpenTTD launch, rendered game over WebSocket, termination"
)
