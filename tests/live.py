"""Real Docker/API/CLI test; run only against a disposable QA deployment."""

import json
import gzip
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

URL = os.getenv("QA_URL", "http://localhost:18088")


def api(path, method="GET", body=None, token="", expected=200):
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        URL + "/api" + path,
        headers=headers,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        response = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as error:
        assert error.code == expected, (path, error.code, error.read())
        return json.load(error)
    with response:
        assert response.status == expected
        return json.load(response)


admin_password = next(
    line.split("=", 1)[1]
    for line in Path("/tmp/gamedock-qa.env").read_text().splitlines()
    if line.startswith("ADMIN_PASSWORD=")
)
admin = api("/auth/login", "POST", {"username": "admin", "password": admin_password})[
    "token"
]
old = api("/catalog", token=admin)["settings"]
api(
    "/admin/settings",
    "PUT",
    {**old, "name": "GameDock QA", "banner": "Real desktop validation"},
    admin,
)
assert api("/catalog")["settings"]["name"] == "GameDock QA"
profile = {
    "id": "qa-native",
    "name": "QA native program",
    "image": "gamedock-runtime:local",
    "command": [
        "xterm",
        "-title",
        "GameDock QA",
        "-e",
        "sh",
        "-c",
        'printf "GameDock QA\\n"; echo persistent > /data/qa.txt; sleep 180',
    ],
    "resolutions": ["1280x720", "1920x1080"],
    "env": {},
}
api("/admin/games", "PUT", profile, admin)
other = api(
    "/auth/register",
    "POST",
    {
        "username": "other_" + secrets.token_hex(3),
        "password": secrets.token_urlsafe(20),
    },
)["token"]
with tempfile.TemporaryDirectory() as directory:
    credentials = str(Path(directory) / "session.json")
    cli = ["python3", "cli/gamedock.py", "--url", URL, "--credentials", credentials]
    result = subprocess.run(
        cli + ["register", "cli_" + secrets.token_hex(3)],
        input=secrets.token_urlsafe(20) + "\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert Path(credentials).stat().st_mode & 0o777 == 0o600
    token = json.loads(Path(credentials).read_text())["token"]
    ids = []
    try:
        for resolution in profile["resolutions"]:
            result = subprocess.run(
                cli + ["launch", "qa-native", "--resolution", resolution],
                text=True,
                capture_output=True,
            )
            assert result.returncode == 0, result.stderr
            sid = result.stdout.splitlines()[0]
            ids.append(sid)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                output = subprocess.run(
                    ["docker", "exec", "gamedock-" + sid, "xdpyinfo"],
                    text=True,
                    capture_output=True,
                )
                if resolution in output.stdout:
                    break
                time.sleep(0.5)
            else:
                raise AssertionError(output.stderr)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ["docker", "exec", "gamedock-" + sid, "cat", "/data/qa.txt"],
                    text=True,
                    capture_output=True,
                )
                if result.returncode == 0:
                    assert result.stdout.strip() == "persistent"
                    break
                time.sleep(0.5)
            else:
                raise AssertionError("Configured command did not execute")
            req = urllib.request.Request(
                URL + "/desktop/" + sid + "/",
                headers={"Authorization": "Bearer " + token},
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        body = response.read()
                        if response.headers.get("Content-Encoding") == "gzip":
                            body = gzip.decompress(body)
                        assert b"xpra" in body.lower()
                        break
                except urllib.error.HTTPError as error:
                    if error.code != 503:
                        raise
                time.sleep(0.5)
            else:
                raise AssertionError("Xpra HTTP viewer not ready")
            req = urllib.request.Request(
                URL + "/desktop/" + sid + "/",
                headers={"Authorization": "Bearer " + other},
            )
            try:
                urllib.request.urlopen(req)
                raise AssertionError("Cross-account desktop access allowed")
            except urllib.error.HTTPError as error:
                assert error.code == 404
            info = json.loads(
                subprocess.check_output(["docker", "inspect", "gamedock-" + sid])
            )[0]
            assert not info["HostConfig"]["PortBindings"], "Session port exposed"
            assert info["Config"]["User"] == "player"
            assert info["Mounts"][0]["Name"].startswith("gamedock-qa-user-"), (
                "Volume is not scoped to the QA deployment"
            )
            assert list(info["NetworkSettings"]["Networks"]) == [
                "gamedock-session-" + sid
            ]
            net = json.loads(
                subprocess.check_output(
                    ["docker", "network", "inspect", "gamedock-session-" + sid]
                )
            )[0]
            assert len(net["Containers"]) == 2, "Session shares network with a sibling"
        peer = json.loads(
            subprocess.check_output(["docker", "inspect", "gamedock-" + ids[1]])
        )[0]
        peer_ip = next(iter(peer["NetworkSettings"]["Networks"].values()))["IPAddress"]
        attempt = subprocess.run(
            [
                "docker",
                "exec",
                "gamedock-" + ids[0],
                "python3",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://"
                + peer_ip
                + ":6084',timeout=2)",
            ],
            capture_output=True,
        )
        assert attempt.returncode != 0, "Sibling network is reachable"
        if os.getenv("QA_RECREATE") == "1":
            pid = peer["State"]["Pid"]
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    "gamedock-qa",
                    "--env-file",
                    "/tmp/gamedock-qa.env",
                    "up",
                    "-d",
                    "--force-recreate",
                    "--no-build",
                ],
                env={**os.environ, "PORT": "18088"},
                check=True,
                capture_output=True,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    assert len(api("/instances", token=token)) == 2
                    break
                except (OSError, AssertionError):
                    time.sleep(0.5)
            else:
                raise AssertionError(
                    "Portal did not recover persisted accounts and instances"
                )
            peer_now = json.loads(
                subprocess.check_output(["docker", "inspect", "gamedock-" + ids[1]])
            )[0]
            assert peer_now["State"]["Pid"] == pid, (
                "Portal recreation restarted the game"
            )
            req = urllib.request.Request(
                URL + "/desktop/" + ids[1] + "/",
                headers={"Authorization": "Bearer " + token},
            )
            with urllib.request.urlopen(req) as response:
                assert response.status == 200
            print(
                "PASS: portal recreation retains account token and game process and reconnects the private session network"
            )
        subprocess.run(
            [
                "docker",
                "exec",
                "gamedock-" + ids[0],
                "sh",
                "-c",
                "echo retained > /data/restart-marker",
            ],
            check=True,
        )
        api("/instances/" + ids[0], "DELETE", {}, token)
        replacement = api(
            "/instances", "POST", {"game": "qa-native"}, token, expected=201
        )["id"]
        ids.append(replacement)
        retained = subprocess.check_output(
            [
                "docker",
                "exec",
                "gamedock-" + replacement,
                "cat",
                "/data/restart-marker",
            ],
            text=True,
        )
        assert retained.strip() == "retained", (
            "Game files lost after replacing instance"
        )
        print(
            "PASS: CLI registration, native command, two desktops, two actual resolutions, persistent data, Xpra HTTP, cross-user denial, no published session ports"
        )
    finally:
        for sid in ids:
            api("/instances/" + sid, "DELETE", {}, token)
        subprocess.run(cli + ["logout"], check=True, capture_output=True)
        assert not Path(credentials).exists()
        api("/admin/games/qa-native", "DELETE", {}, admin)
        api("/admin/settings", "PUT", old, admin)
