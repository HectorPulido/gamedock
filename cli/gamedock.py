#!/usr/bin/env python3
"""Dependency-free API client. Tokens are stored with mode 0600."""

import argparse
import getpass
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

parser = argparse.ArgumentParser(prog="gamedock")
parser.add_argument("--url", default=os.getenv("GAMEDOCK_URL", "http://localhost:8080"))
parser.add_argument(
    "--credentials", default=str(Path.home() / ".config/gamedock/session.json")
)
sub = parser.add_subparsers(dest="action", required=True)
for name in ("login", "register"):
    sub.add_parser(name).add_argument("username")
launch = sub.add_parser("launch")
launch.add_argument("game")
launch.add_argument("--resolution")
sub.add_parser("list")
sub.add_parser("games")
sub.add_parser("logout")
sub.add_parser("stop").add_argument("id")
sub.add_parser("profile").add_argument("file")
args = parser.parse_args()
credentials = Path(args.credentials)
url = args.url.rstrip("/")
token = ""
if credentials.exists():
    saved = json.loads(credentials.read_text())
    if saved.get("url") == url:
        token = saved["token"]


def request(path, method="GET", body=None):
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        parser.exit(1, json.load(error).get("error", str(error)) + "\n")


if args.action in ("login", "register"):
    result = request(
        "/auth/" + args.action,
        "POST",
        {"username": args.username, "password": getpass.getpass("Password: ")},
    )
    credentials.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"url": url, "token": result["token"]}, output)
    print("Signed in as " + result["user"]["username"])
elif args.action == "launch":
    body = {"game": args.game}
    if args.resolution:
        body["resolution"] = args.resolution
    result = request("/instances", "POST", body)
    print(result["id"] + "\n" + url + result["url"])
elif args.action == "stop":
    print(json.dumps(request("/instances/" + args.id, "DELETE", {})))
elif args.action == "logout":
    request("/logout", "POST", {})
    credentials.unlink(missing_ok=True)
    print("Signed out")
elif args.action == "profile":
    print(
        json.dumps(
            request("/admin/games", "PUT", json.loads(Path(args.file).read_text())),
            ensure_ascii=False,
            indent=2,
        )
    )
elif args.action == "games":
    print(json.dumps(request("/catalog")["games"], ensure_ascii=False, indent=2))
else:
    print(json.dumps(request("/instances"), ensure_ascii=False, indent=2))
