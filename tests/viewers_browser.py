"""Real browser + Xpra + Docker acceptance test, against a disposable QA portal.

Requires Docker socket and Playwright. Restarts ONLY QA_PORTAL_CONTAINER.
"""

import http.client
import io
import json
import os
from pathlib import Path
import socket
import tarfile
import time
from playwright.sync_api import sync_playwright, expect
from browser_helpers import rendered

URL = os.getenv("QA_URL", "http://localhost:18089")
PORTAL = os.getenv("QA_PORTAL_CONTAINER", "gamedock-viewers-portal-qa")
assert PORTAL.endswith("-qa"), "Only a disposable QA portal may be restarted"
PASSWORD = os.getenv("QA_PASSWORD", "gamedock-viewers-test-password")
ARTIFACTS = Path(os.getenv("QA_ARTIFACTS", "/artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
events = []


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        self.sock.connect("/var/run/docker.sock")


def docker(method, path):
    conn = UnixHTTP("localhost", timeout=15)
    conn.request(method, "/v1.45" + path)
    response = conn.getresponse()
    body = response.read()
    status = response.status
    conn.close()
    return status, body


def record(name, **data):
    events.append({"test": name, **data})
    print(json.dumps(events[-1]), flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    req = ctx.request

    def api(path, body=None, method="GET"):
        response = req.fetch(URL + "/api" + path, method=method, data=body)
        assert response.ok, (response.status, response.text())
        return response.json()

    api("/auth/login", {"username": "admin", "password": PASSWORD}, "POST")
    api(
        "/admin/settings",
        {
            "idle_minutes": 0,
            "viewer_action": "stop",
            "viewer_disconnect_seconds": 12,
            "viewer_first_connect_seconds": 45,
            "max_instances": 4,
            "per_user": 4,
        },
        "PUT",
    )
    profile = {
        "id": "viewers-live-qa",
        "name": "Viewer lifecycle QA",
        "image": "gamedock-runtime:local",
        "command": [
            "sh",
            "-c",
            "test -f /data/viewer-marker || printf persistent > /data/viewer-marker; exec glxgears",
        ],
        "resolutions": ["1280x720"],
    }
    api("/admin/games", profile, "PUT")
    sid = None
    pages = []

    def instance():
        return next(i for i in api("/instances") if i["id"] == sid)

    def wait_for(predicate, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = instance()
            if predicate(value):
                return value
            time.sleep(0.25)
        raise AssertionError(instance())

    def open_viewer():
        page = ctx.new_page()
        pages.append(page)
        trace = []
        opened = time.monotonic()
        page.on("pageerror", lambda error: trace.append({"error": str(error)}))
        page.on(
            "requestfailed",
            lambda request: trace.append(
                {"failed": request.url, "error": request.failure}
            ),
        )
        page.on(
            "response",
            lambda response: trace.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "seconds": round(time.monotonic() - opened, 2),
                }
            )
            if response.status >= 400 or "/api/" in response.url
            else None,
        )
        page.goto(URL + "/play/" + sid)
        try:
            rendered(page)
        except Exception:
            page.screenshot(path=str(ARTIFACTS / "viewer-failure.png"), full_page=True)
            details = {
                "instance": instance(),
                "trace": trace,
                "frames": [
                    {"url": f.url, "text": f.locator("body").inner_text()[:2000]}
                    for f in page.frames
                ],
            }
            for name in ("gamedock-" + sid, PORTAL):
                status, log = docker(
                    "GET",
                    "/containers/" + name + "/logs?stdout=true&stderr=true&tail=70",
                )
                details[name] = {"status": status, "log": log.decode(errors="replace")}
            (ARTIFACTS / "viewer-failure.json").write_text(
                json.dumps(details, indent=2)
            )
            print(json.dumps(details), flush=True)
            raise
        return page

    try:
        sid = api("/instances", {"game": profile["id"]}, "POST")["id"]
        time.sleep(15 if not os.getenv("QA_FAST_RESTART") else 2)
        first = instance()
        assert (
            first["status"] == "running"
            and first["viewers"]["waiting_for_first_viewer"]
        )
        record("first_viewer_grace", presence=first["viewers"])
        one = open_viewer()
        wait_for(lambda i: i["viewers"]["count"] == 1)
        time.sleep(15 if not os.getenv("QA_FAST_RESTART") else 2)
        assert instance()["status"] == "running"
        record("connected_without_input", presence=instance()["viewers"])
        status, raw = docker(
            "GET", "/containers/gamedock-" + sid + "/stats?stream=false"
        )
        assert status == 200
        stats = json.loads(raw)
        previous_cpu = stats["precpu_stats"].get("cpu_usage", {}).get("total_usage", 0)
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - previous_cpu
        system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats[
            "precpu_stats"
        ].get("system_cpu_usage", 0)
        cpu_percent = (
            100 * cpu_delta / system_delta * stats["cpu_stats"].get("online_cpus", 1)
            if system_delta > 0
            else None
        )
        record(
            "running_resources",
            cpu_percent=round(cpu_percent, 2) if cpu_percent is not None else None,
            cpu_total_ns=stats["cpu_stats"]["cpu_usage"]["total_usage"],
            memory_bytes=stats["memory_stats"].get("usage"),
            pids=stats.get("pids_stats"),
        )
        two = open_viewer()
        wait_for(lambda i: i["viewers"]["count"] == 2)
        one.close()
        wait_for(lambda i: i["viewers"]["count"] == 1)
        time.sleep(15 if not os.getenv("QA_FAST_RESTART") else 2)
        assert instance()["status"] == "running"
        record("one_of_two_closed", presence=instance()["viewers"])
        two.close()
        wait_for(lambda i: i["viewers"]["count"] == 0)
        time.sleep(3)
        three = open_viewer()
        value = wait_for(lambda i: i["viewers"]["count"] == 1)
        assert not value["viewers"]["stop_pending"]
        record("reconnect_same_instance", id=sid, presence=value["viewers"])
        # Restart can interrupt initial player HTTP/API loading. Use the actual
        # default grace here; HTTP requests deliberately are not viewer leases.
        api("/admin/settings", {"viewer_disconnect_seconds": 60}, "PUT")
        for cycle in range(int(os.getenv("QA_RESTART_CYCLES", "1"))):
            assert docker("POST", "/containers/" + PORTAL + "/restart?t=1")[0] == 204
            end = time.monotonic() + 25
            while True:
                try:
                    value = instance()
                    break
                except Exception:
                    assert time.monotonic() < end
                    time.sleep(0.25)
            assert value["status"] == "running"
            record("portal_restart", presence=value["viewers"])
            three.close()
            four = open_viewer()
            wait_for(lambda i: i["viewers"]["count"] == 1)
            three = four
        api("/admin/settings", {"viewer_disconnect_seconds": 12}, "PUT")
        four.close()
        wait_for(lambda i: i["viewers"]["count"] == 0)
        started = time.monotonic()
        value = wait_for(lambda i: i["status"] == "stopped", timeout=30)
        assert docker("GET", "/containers/gamedock-" + sid + "/json")[0] == 404
        assert docker("GET", "/containers/gamedock-gateway-" + sid + "/json")[0] == 404
        record(
            "automatic_stop",
            elapsed_seconds=round(time.monotonic() - started, 2),
            container_removed=True,
            game_processes_remaining=0,
        )
        sid = api("/instances", {"game": profile["id"]}, "POST")["id"]
        deadline = time.monotonic() + 15
        while True:
            status, archive = docker(
                "GET",
                "/containers/gamedock-" + sid + "/archive?path=/data/viewer-marker",
            )
            if status == 200:
                break
            assert time.monotonic() < deadline
            time.sleep(0.25)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            assert tar.extractfile(tar.getmembers()[0]).read() == b"persistent"
        record("slot_and_volume_reused", new_id=sid, marker_preserved=True)
        admin = ctx.new_page()
        admin.goto(URL + "/admin#instances")
        admin.get_by_role("heading", name="Instances", exact=True).wait_for()
        admin.screenshot(
            path=str(ARTIFACTS / "viewer-presence-admin.png"), full_page=True
        )
        admin.goto(URL + "/admin#platform")
        expect(admin.locator("[name=viewer_action]")).to_have_value("stop")
        expect(admin.locator("[name=viewer_disconnect_seconds]")).to_have_value("12")
        admin.locator("[name=viewer_action]").select_option("disabled")
        admin.locator("[name=viewer_disconnect_seconds]").fill("60")
        admin.locator("[name=viewer_first_connect_seconds]").fill("180")
        with admin.expect_response(
            lambda r: r.url.endswith("/api/admin/settings")
            and r.request.method == "PUT"
        ) as saved:
            admin.get_by_role("button", name="Save settings", exact=True).click()
        assert saved.value.ok
        admin.reload()
        expect(admin.locator("[name=viewer_action]")).to_have_value("disabled")
        expect(admin.locator("[name=viewer_first_connect_seconds]")).to_have_value(
            "180"
        )
        admin.set_viewport_size({"width": 390, "height": 844})
        assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
        record(
            "viewer_settings_saved",
            action="disabled",
            disconnect_seconds=60,
            first_viewer_seconds=180,
        )
    finally:
        for page in pages:
            if not page.is_closed():
                page.close()
        if sid:
            api("/instances/" + sid, {}, "DELETE")
        api("/admin/games/" + profile["id"], {}, "DELETE")
        browser.close()
        (ARTIFACTS / "viewers-browser.json").write_text(json.dumps(events, indent=2))
