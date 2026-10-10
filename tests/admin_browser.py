"""Separate administrator workspace and identical player library in disposable QA."""

import secrets
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD, admin_token, invitation, rendered


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    setup = p.request.new_context()
    token = admin_token(setup)
    headers = {"Authorization": "Bearer " + token}
    hidden_id = "qa-admin-disabled"
    username = "workspace_" + secrets.token_hex(4)
    password = secrets.token_urlsafe(20)
    assert setup.put(
        URL + "/api/admin/games",
        headers=headers,
        data={
            "id": hidden_id,
            "name": "Disabled QA game",
            "image": "gamedock-runtime:local",
            "command": ["xterm"],
            "enabled": False,
        },
    ).ok
    player = browser.new_page(viewport={"width": 1440, "height": 1000})
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    own = other = None
    original = None
    try:
        code = invitation(setup, token)
        player.goto(URL)
        player.get_by_label("Username", exact=True).fill(username)
        player.get_by_label("Password", exact=True).fill(password)
        player.get_by_label("Invitation code (for new accounts)").fill(code)
        player.get_by_role("button", name="Create account", exact=True).click()
        expect(
            player.get_by_role("heading", name="Choose where to play")
        ).to_be_visible()
        page.goto(URL)
        page.get_by_label("Username", exact=True).fill("admin")
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(
            page.get_by_role("link", name="Administration", exact=True)
        ).to_be_visible()
        expect(
            player.get_by_role("link", name="Administration", exact=True)
        ).to_have_count(0)
        for library in (page, player):
            expect(
                library.locator("#admin, #settings, #profile, #add-game, #games select")
            ).to_have_count(0)
            expect(
                library.get_by_role("button", name="Edit", exact=True)
            ).to_have_count(0)
            expect(
                library.get_by_role("button", name="Remove from catalog", exact=True)
            ).to_have_count(0)
            expect(
                library.get_by_role("heading", name="Disabled QA game", exact=True)
            ).to_have_count(0)
        assert (
            page.locator("#games h3").all_text_contents()
            == player.locator("#games h3").all_text_contents()
        )
        # The home library lists only the current account's games even for admins.
        response = player.request.post(URL + "/api/instances", data={"game": "desktop"})
        assert response.status == 201, response.text()
        other = response.json()["id"]
        page.get_by_role("button", name="Refresh instances", exact=True).click()
        expect(page.locator("#instances .instance")).to_have_count(0)
        # Administrators launch from the same card into the same viewer as players.
        card = page.locator("article").filter(
            has=page.get_by_role("heading", name="Test desktop", exact=True)
        )
        card.get_by_role("button", name="Launch instance", exact=True).click()
        page.wait_for_url("**/play/*", timeout=60000)
        own = page.url.rsplit("/", 1)[1]
        rendered(page)
        page.on("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Stop instance", exact=True).click()
        page.wait_for_url(URL + "/")
        own = None
        expect(page.locator("#instances .instance")).to_have_count(0)
        page.get_by_role("link", name="Administration", exact=True).click()
        page.wait_for_url(URL + "/admin")
        expect(page.locator("#section-access")).to_be_visible()
        expect(page.locator(".admin-section:visible")).to_have_count(1)
        # Search narrows accounts, and section navigation preserves unsaved forms.
        page.get_by_label("Search accounts", exact=True).fill(username)
        expect(page.locator("#users .account:visible")).to_have_count(1)
        account = page.locator("#users .account:visible")
        account.get_by_text("Game access and instance limits", exact=True).click()
        account.get_by_label("Total instances (blank uses the platform limit)").fill(
            "3"
        )
        nav = page.locator("#admin-nav")
        nav.get_by_role("link", name="Games", exact=True).click()
        expect(page.locator(".admin-section:visible")).to_have_count(1)
        page.get_by_label("Search games", exact=True).fill(hidden_id)
        expect(page.locator("#games article")).to_have_count(1)
        expect(
            page.get_by_role("heading", name="Disabled QA game", exact=True)
        ).to_be_visible()
        page.get_by_label("Search games", exact=True).fill("no-match-here")
        expect(
            page.get_by_text("No games match your search.", exact=True)
        ).to_be_visible()
        page.get_by_label("Search games", exact=True).fill("")
        page.get_by_role("button", name="Add game", exact=True).click()
        page.locator("#profile").get_by_label("JSON definition").fill(
            '{"draft": "keep me"}'
        )
        nav.get_by_role("link", name="Platform", exact=True).click()
        expect(page.locator("#settings")).to_be_visible()
        page.go_back()
        expect(page.locator("#profile").get_by_label("JSON definition")).to_have_value(
            '{"draft": "keep me"}'
        )
        nav.get_by_role("link", name="Access", exact=True).click()
        expect(
            page.locator("#users .account:visible").get_by_label(
                "Total instances (blank uses the platform limit)"
            )
        ).to_have_value("3")
        page.get_by_label("Search accounts", exact=True).fill("no-match-here")
        expect(
            page.get_by_text("No accounts match your search.", exact=True)
        ).to_be_visible()
        page.get_by_label("Search accounts", exact=True).fill("")
        page.screenshot(path=str(ARTIFACTS / "admin-access.png"))
        # Bookmarks/reloads retain the section, and the instance search finds owners.
        nav.get_by_role("link", name="Instances", exact=True).click()
        page.reload()
        expect(page.locator("#section-instances")).to_be_visible()
        page.get_by_label("Search instances", exact=True).fill(username)
        expect(page.locator("#instances .instance")).to_have_count(1)
        page.get_by_label("Search instances", exact=True).fill("no-match-here")
        expect(
            page.get_by_text("No instances match your search.", exact=True)
        ).to_be_visible()
        page.get_by_label("Search instances", exact=True).fill(username)
        page.locator("#instances").get_by_role(
            "button", name="Stop", exact=True
        ).click()
        expect(page.get_by_text("Instance stopped.", exact=True)).to_be_visible()
        other = None
        # Every saved preset styles the whole workspace, and mobile uses a scrollable nav.
        original = page.request.get(URL + "/api/catalog").json()["settings"][
            "appearance"
        ]
        for theme in ("classic", "midnight", "forest"):
            assert page.request.put(
                URL + "/api/admin/settings", data={"appearance": {"theme": theme}}
            ).ok
            page.goto(URL + "/admin#access")
            page.reload()
            page.wait_for_function(
                "t => document.documentElement.dataset.theme === t", arg=theme
            )
            expect(page.locator("#section-access")).to_be_visible()
            page.screenshot(path=str(ARTIFACTS / ("admin-" + theme + ".png")))
        assert page.request.put(
            URL + "/api/admin/settings", data={"appearance": original}
        ).ok
        for section in ("access", "games", "platform", "appearance", "instances"):
            page.goto(URL + "/admin#" + section)
            expect(page.locator("#section-" + section)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            expect(page.locator(".admin-section:visible")).to_have_count(1)
        page.screenshot(path=str(ARTIFACTS / "admin-mobile.png"))
        page.get_by_role("link", name="Back to library", exact=True).click()
        expect(page.get_by_role("heading", name="Choose where to play")).to_be_visible()
        response = player.request.get(URL + "/admin")
        assert response.status == 403
        assert not errors, errors
        print(
            "PASS: one admin-only library link, identical cards and auto-launch, own instances only, separate protected workspace, searches, drafts, history, bookmarks, themes and mobile"
        )
    finally:
        if original is not None:
            setup.put(
                URL + "/api/admin/settings",
                headers=headers,
                data={"appearance": original},
            )
        for sid in (own, other):
            if sid:
                setup.delete(URL + "/api/instances/" + sid, headers=headers, data={})
        setup.delete(URL + "/api/admin/games/" + hidden_id, headers=headers, data={})
        browser.close()
        setup.dispose()
