"""Real OpenTTD, game creation, invitation, and account settings in disposable QA."""

import json
from pathlib import Path
import secrets
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD, rendered, centered

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_text("Administration", exact=True).click()
    settings = page.locator("#settings")
    settings.get_by_label("Name", exact=True).fill("GameDock Playroom")
    settings.get_by_label("Banner / welcome message").fill(
        "Independent desktops for your community."
    )
    settings.get_by_label("Banner image (optional URL)").fill(
        URL + "/assets/banner.svg"
    )
    settings.get_by_label("Show desktop toolbar").uncheck()
    settings.get_by_label("Require an invitation code").check()
    page.get_by_role("button", name="Save settings", exact=True).click()
    expect(page.get_by_text("Settings saved.", exact=True)).to_be_visible()
    expect(
        page.get_by_role("heading", name="GameDock Playroom", exact=True)
    ).to_be_visible()
    page.wait_for_function("document.querySelector('#intro-banner').naturalWidth>0")
    # Add game starts a new JSON template; Edit loads the existing definition.
    page.get_by_role("button", name="Add game", exact=True).click()
    profile = json.loads(Path("examples/openttd/profile.json").read_text())
    form = page.locator("#profile")
    expect(form.get_by_role("heading", name="Add game", exact=True)).to_be_visible()
    assert (
        json.loads(form.get_by_label("JSON definition").input_value())["id"]
        == "my-game"
    )
    form.get_by_label("JSON definition").fill(json.dumps(profile, indent=2))
    page.get_by_role("button", name="Save game", exact=True).click()
    expect(page.get_by_text("Game saved.", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="OpenTTD", exact=True)).to_be_visible()
    card = page.locator("article").filter(
        has=page.get_by_role("heading", name="OpenTTD", exact=True)
    )
    card.get_by_role("button", name="Edit", exact=True).click()
    expect(form.get_by_role("heading", name="Edit game", exact=True)).to_be_visible()
    assert (
        json.loads(form.get_by_label("JSON definition").input_value())["id"]
        == "openttd"
    )
    form.get_by_role("button", name="New game", exact=True).click()
    expect(form.get_by_role("heading", name="Add game", exact=True)).to_be_visible()
    assert (
        json.loads(form.get_by_label("JSON definition").input_value())["id"]
        == "my-game"
    )
    invitation = page.locator("#invitation-form")
    invitation.get_by_label("Label", exact=True).fill("Browser QA")
    invitation.get_by_role("button", name="Create invitation").click()
    expect(page.locator("#invitation-result code")).to_be_visible()
    code = page.locator("#invitation-result code").inner_text()
    page.screenshot(path=str(ARTIFACTS / "admin.png"), full_page=True)
    # Use a separate player context so administrator settings can be changed live.
    player = browser.new_page(viewport={"width": 1440, "height": 1000})
    player.goto(URL)
    username = "game_" + secrets.token_hex(4)
    player.get_by_label("Username", exact=True).fill(username)
    player.get_by_label("Password", exact=True).fill(secrets.token_urlsafe(20))
    player.get_by_label("Invitation code (for new accounts)").fill(code)
    player.get_by_role("button", name="Create account", exact=True).click()
    expect(player.get_by_role("heading", name="OpenTTD", exact=True)).to_be_visible()
    expect(player.locator("#games select:visible")).to_have_count(0)
    player.locator("article").filter(
        has=player.get_by_role("heading", name="OpenTTD", exact=True)
    ).get_by_role("button", name="Launch instance").click()
    player.wait_for_url("**/play/*", timeout=60000)
    remote = rendered(player, 30)
    centered(player)
    assert remote.locator("#float_menu").is_hidden()
    player.screenshot(path=str(ARTIFACTS / "openttd.png"), full_page=True)
    # Changing the admin toolbar checkbox affects existing viewers without rebuilding.
    settings.get_by_label("Show desktop toolbar").check()
    page.get_by_role("button", name="Save settings", exact=True).click()
    expect(page.get_by_text("Settings saved.", exact=True)).to_be_visible()
    expect(player.frame_locator("#desktop-frame").locator("#float_menu")).to_be_visible(
        timeout=30000
    )
    # Account-level game type and total instance controls are editable in the UI.
    page.reload()
    page.get_by_text("Administration", exact=True).click()
    account = page.locator(".account").filter(
        has=page.get_by_text(username, exact=True)
    )
    account.get_by_text("Game access and instance limits", exact=True).click()
    account.get_by_label("Total instances (blank uses the platform limit)").fill("1")
    account.get_by_label("Use the library's default game access").uncheck()
    account.get_by_label("Test desktop instances (0 blocks access)", exact=True).fill(
        "0"
    )
    account.get_by_label("OpenTTD instances (0 blocks access)", exact=True).fill("1")
    account.get_by_role("button", name="Save account limits").click()
    expect(page.get_by_text("Account limits saved.", exact=True)).to_be_visible()
    player.on("dialog", lambda dialog: dialog.accept())
    player.get_by_role("button", name="Stop instance", exact=True).click()
    player.wait_for_url(URL + "/", timeout=60000)
    expect(
        player.get_by_role("heading", name="Test desktop", exact=True)
    ).to_have_count(0)
    expect(player.locator("#instances .instance")).to_have_count(0)
    browser.close()
print(
    "PASS: JSON game creation and edit modes, invitation creation/redemption, rendered OpenTTD, live toolbar setting, account limits, stop and hidden history"
)
