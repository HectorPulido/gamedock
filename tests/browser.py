"""Real desktop, navigation, permissions, and keyboard tests in disposable QA."""

import http.client
import json
import secrets
import socket
import time
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, admin_token, invitation, rendered, centered


def docker(method, path, body):
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
    assert response.status < 400, data
    connection.close()
    return data


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    # API setup uses a separate context so the player's cookie starts empty.
    setup = p.request.new_context()
    admin = admin_token(setup)
    profile = setup.get(
        URL + "/api/catalog", headers={"Authorization": "Bearer " + admin}
    ).json()["games"]
    desktop = next(g for g in profile if g["id"] == "desktop")
    assert setup.put(
        URL + "/api/admin/games",
        data={**desktop, "max_per_user": 2},
        headers={"Authorization": "Bearer " + admin},
    ).ok
    code = invitation(setup, admin)
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(URL)
    page.screenshot(path=str(ARTIFACTS / "login.png"), full_page=True)
    username, password = "qa_" + secrets.token_hex(4), secrets.token_urlsafe(20)
    page.get_by_label("Username", exact=True).fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Invitation code (for new accounts)").fill(code)
    page.get_by_role("button", name="Create account", exact=True).click()
    expect(page.get_by_role("heading", name="Choose where to play")).to_be_visible()
    expect(page.locator("#games select:visible")).to_have_count(0)
    page.screenshot(path=str(ARTIFACTS / "library.png"), full_page=True)
    card = page.locator("article").filter(
        has=page.get_by_role("heading", name="Test desktop", exact=True)
    )
    card.get_by_role("button", name="Launch instance").click()
    page.wait_for_url("**/play/*", timeout=60000)
    first = page.url
    sid = first.rsplit("/", 1)[1]
    closed = []
    page.on("websocket", lambda ws: ws.on("close", lambda: closed.append(True)))
    remote = rendered(page)
    centered(page)
    page.screenshot(path=str(ARTIFACTS / "desktop.png"), full_page=True)
    # Actual keyboard input through the centered/scaled iframe.
    remote.locator("canvas").first.click(position={"x": 640, "y": 300})
    page.keyboard.type("printf keyboard-ok > /data/browser-input.txt", delay=20)
    page.keyboard.press("Enter")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        definition = json.loads(
            docker(
                "POST",
                "/containers/gamedock-" + sid + "/exec",
                {
                    "Cmd": ["cat", "/data/browser-input.txt"],
                    "AttachStdout": True,
                    "AttachStderr": True,
                },
            )
        )
        result = docker(
            "POST",
            "/exec/" + definition["Id"] + "/start",
            {"Detach": False, "Tty": False},
        )
        if b"keyboard-ok" in result:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Keyboard input did not reach the application")
    page.screenshot(path=str(ARTIFACTS / "desktop-input.png"), full_page=True)
    activity = page.request.get(URL + "/api/instances/" + sid).json()["last_activity"]
    assert activity > time.time() - 20
    page.get_by_role("link", name="Back to library").click()
    card = page.locator("article").filter(
        has=page.get_by_role("heading", name="Test desktop", exact=True)
    )
    card.get_by_role("button", name="Launch instance").click()
    page.wait_for_url("**/play/*", timeout=60000)
    second = page.url
    assert second != first
    rendered(page)
    page.get_by_role("button", name="Previous instance").click()
    page.wait_for_url(first)
    rendered(page)
    page.set_viewport_size({"width": 900, "height": 700})
    page.wait_for_timeout(300)
    centered(page)
    # Sign out in another tab closes the active desktop connection.
    library = page.context.new_page()
    library.goto(URL)
    before = len(closed)
    library.get_by_role("button", name="Sign out", exact=True).click()
    expect(
        library.get_by_role("heading", name="Sign in to your library")
    ).to_be_visible()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(closed) == before:
        page.wait_for_timeout(100)
    assert len(closed) > before, "Logout did not close the connected WebSocket"
    assert page.request.get(URL + "/desktop/" + sid + "/").status == 401
    library.get_by_label("Username", exact=True).fill(username)
    library.get_by_label("Password", exact=True).fill(password)
    library.get_by_role("button", name="Sign in", exact=True).click()
    expect(library.get_by_role("link", name="Connect").first).to_be_visible()
    library.on("dialog", lambda dialog: dialog.accept())
    while library.get_by_role("button", name="Stop", exact=True).count():
        count = library.get_by_role("button", name="Stop", exact=True).count()
        library.get_by_role("button", name="Stop", exact=True).first.click()
        expect(library.get_by_role("button", name="Stop", exact=True)).to_have_count(
            count - 1, timeout=60000
        )
    expect(library.locator("#instances .instance")).to_have_count(0)
    expect(
        library.get_by_text("No running instances. Choose a game to start playing.")
    ).to_be_visible()
    library.get_by_role("button", name="Sign out", exact=True).click()
    library.set_viewport_size({"width": 390, "height": 844})
    library.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
    assert library.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not errors, errors
    browser.close()
    setup.dispose()
print(
    "PASS: invitation registration, automatic launch, centered/scaled desktop, keyboard, previous instance, logout revocation, stop, hidden history, responsive layout"
)
