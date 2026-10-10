"""Game availability switches persist and govern player access."""

import secrets

from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, PASSWORD, ARTIFACTS

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Administration", exact=True).click()
    page.locator("#admin-nav a[href='#games']").click()
    # The admin catalog includes full definitions.
    catalog = page.request.get(URL + "/api/catalog").json()
    game = next(g for g in catalog["games"] if g["id"] == "desktop")
    card = page.locator(".managed-game").filter(
        has=page.get_by_role("heading", name=game["name"], exact=True)
    )
    switch = card.get_by_role("switch", name="Enable " + game["name"], exact=True)
    try:
        switch.uncheck()
        expect(switch).not_to_be_checked()
        expect(card.locator("small")).to_contain_text("Disabled")
        card.get_by_role("button", name="Edit", exact=True).click()
        expect(page.locator('#profile [name="enabled"]')).not_to_be_checked()
        page.reload()
        expect(switch).not_to_be_checked()
        page.screenshot(path=str(ARTIFACTS / "game-availability.png"))
        guest = browser.new_context()
        forbidden = guest.request.patch(
            URL + "/api/admin/games/desktop", data={"enabled": True}
        )
        assert forbidden.status in (401, 403)
        invite = page.request.post(URL + "/api/admin/invitations", data={}).json()[
            "code"
        ]
        registered = guest.request.post(
            URL + "/api/auth/register",
            data={
                "username": "toggle_" + secrets.token_hex(4),
                "password": secrets.token_urlsafe(20),
                "invite": invite,
            },
        )
        assert registered.ok, registered.text()
        public = guest.request.get(URL + "/api/catalog").json()
        assert not any(g["id"] == "desktop" for g in public["games"])
        invalid = page.request.patch(
            URL + "/api/admin/games/desktop", data={"enabled": "yes"}
        )
        assert invalid.status == 400
        forbidden = guest.request.patch(
            URL + "/api/admin/games/desktop", data={"enabled": True}
        )
        assert forbidden.status in (401, 403)
        switch.check()
        expect(card.locator("small")).to_contain_text("Enabled")
        public = guest.request.get(URL + "/api/catalog").json()
        assert any(g["id"] == "desktop" for g in public["games"])
        guest.close()
        print(
            "PASS: availability toggle, editor sync, persistence, catalog filtering and authorization"
        )
    finally:
        page.request.patch(
            URL + "/api/admin/games/desktop",
            data={"enabled": game.get("enabled", True)},
        )
        browser.close()
