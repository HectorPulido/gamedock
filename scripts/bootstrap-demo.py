"""Register the bundled demo using the portal container's configured credentials."""

import json
import os
import urllib.request


def api(path, body, token="", method="POST"):
    request = urllib.request.Request(
        "http://127.0.0.1:8080/api" + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


token = api(
    "/auth/login",
    {"username": os.environ["ADMIN_USER"], "password": os.environ["ADMIN_PASSWORD"]},
)["token"]
api("/admin/games", json.loads(os.environ["GAMEDOCK_DEMO_PROFILE"]), token, "PUT")
api("/logout", {}, token)
print("GameDock is ready at " + os.environ["PUBLIC_URL"])
print("OpenTTD is installed and registered. Sign in using the credentials in .env.")
