"""Run against disposable QA deployment, never a production database."""

import os
import secrets
import time
import http.client
import json
import socket
from playwright.sync_api import sync_playwright

url = os.getenv("QA_URL", "http://localhost:18088")


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
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_role("heading", name="Entra a tu biblioteca").wait_for()
    page.screenshot(path="/artifacts/login.png", full_page=True)
    username, password = "qa_" + secrets.token_hex(4), secrets.token_urlsafe(20)
    page.get_by_label("Usuario", exact=True).fill(username)
    page.get_by_label("Contraseña", exact=True).fill(password)
    page.get_by_role("button", name="Crear cuenta").click()
    page.get_by_role("heading", name="Elige dónde jugar").wait_for()
    page.locator("article").filter(
        has=page.get_by_role("heading", name="Escritorio de prueba", exact=True)
    ).get_by_role("button", name="Abrir instancia").click()
    page.get_by_role("link", name="Conectar").wait_for(timeout=60000)
    page.screenshot(path="/artifacts/library.png", full_page=True)
    with page.expect_popup() as popup:
        page.get_by_role("link", name="Conectar").click()
    desktop = popup.value
    closed = []
    desktop.on("websocket", lambda ws: ws.on("close", lambda: closed.append(True)))
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        response = desktop.goto(desktop.url)
        if response.status == 200:
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Desktop did not become ready")
    desktop.wait_for_load_state()
    print("Desktop buttons:", desktop.get_by_role("button").all_text_contents())
    print("Desktop title:", desktop.title())
    print("Desktop body:", desktop.locator("body").inner_text()[:1000])
    assert "xpra" in desktop.content().lower(), "Not an Xpra viewer"
    connect = desktop.get_by_role("button", name="Connect", exact=True)
    if connect.count() and connect.is_visible():
        connect.click()
    desktop.locator("canvas").first.wait_for(state="visible", timeout=45000)
    desktop.wait_for_function(
        """() => [...document.querySelectorAll('canvas')].some(c => {
      if(c.width < 640 || c.height < 480) return false;
      const ctx=c.getContext('2d'); if(!ctx) return false;
      const data=ctx.getImageData(0,0,c.width,c.height).data; const colors=new Set();
      for(let i=0;i<data.length;i+=160) if(data[i+3]) colors.add(data.slice(i,i+4).join(','));
      return colors.size>3;
    })""",
        timeout=45000,
    )
    desktop.screenshot(path="/artifacts/desktop.png", full_page=True)
    sid = page.get_by_role("link", name="Conectar").get_attribute("href").split("/")[2]
    desktop.mouse.click(640, 300)
    desktop.keyboard.type("printf keyboard-ok > /data/browser-input.txt", delay=20)
    desktop.keyboard.press("Enter")
    deadline = time.monotonic() + 10
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
    desktop.screenshot(path="/artifacts/desktop-input.png", full_page=True)
    before_logout = len(closed)
    page.get_by_role("button", name="Salir", exact=True).click()
    page.get_by_role("heading", name="Entra a tu biblioteca").wait_for()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(closed) == before_logout:
        page.wait_for_timeout(100)
    assert len(closed) > before_logout, "Logout did not close the connected WebSocket"
    response = desktop.reload()
    assert response.status == 401, "Logged-out desktop remains accessible"
    page.get_by_label("Usuario", exact=True).fill(username)
    page.get_by_label("Contraseña", exact=True).fill(password)
    page.get_by_role("button", name="Iniciar sesión", exact=True).click()
    page.get_by_role("link", name="Conectar").wait_for()
    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Terminar", exact=True).click()
    page.get_by_text("Detenida", exact=False).wait_for()
    page.get_by_role("button", name="Salir", exact=True).click()
    page.get_by_role("heading", name="Entra a tu biblioteca").wait_for()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path="/artifacts/mobile.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "Mobile overflow"
    )
    assert not errors, errors
    browser.close()
print(
    "PASS: register, launch, rendered desktop, actual keyboard input, logout denial, login, stop, responsive layout"
)
