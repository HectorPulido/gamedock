"""Exercise the real inactivity worker against a disposable QA project only."""

import json
import os
from pathlib import Path
import time
import urllib.request

URL = os.getenv("QA_URL", "http://localhost:18088")
password = next(
    line.split("=", 1)[1]
    for line in Path(os.getenv("QA_ENV_FILE", "/tmp/gamedock-qa.env"))
    .read_text()
    .splitlines()
    if line.startswith("ADMIN_PASSWORD=")
)
token = ""


def api(path, body=None, method=None):
    request = urllib.request.Request(
        URL + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ("POST" if body is not None else "GET"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


token = api("/auth/login", {"username": "admin", "password": password})["token"]
original = api("/catalog")["settings"]
sid = None
try:
    api("/admin/settings", {"idle_minutes": 1}, "PUT")
    sid = api("/instances", {"game": "desktop"})["id"]
    deadline = time.monotonic() + 85
    while time.monotonic() < deadline:
        details = api("/instances/" + sid)
        if details["status"] == "stopped":
            break
        time.sleep(2)
    else:
        raise AssertionError("Background worker did not stop the idle instance")
    print(
        "PASS: actual background worker stops an inactive Docker desktop within the configured timeout plus one sweep"
    )
finally:
    api("/admin/settings", {"idle_minutes": original["idle_minutes"]}, "PUT")
    if sid and api("/instances/" + sid)["status"] == "running":
        api("/instances/" + sid, {}, "DELETE")
    api("/logout", {})
