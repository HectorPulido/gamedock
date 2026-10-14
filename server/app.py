import asyncio
import hashlib
import hmac
import html
import math
import mimetypes
import json
import os
import re
import secrets
import sqlite3
import time
import contextlib
from pathlib import Path

import aiohttp
from aiohttp import web

from server.viewers import Presence, DesktopStopped
from network.policy import validate_policy, DNS
from runtime.gpu import validate_gpu, docker_gpu
from runtime.streaming import (
    STREAMING_DEFAULTS,
    STREAMING_FIELDS,
    STREAMING_PRESETS,
    validate_streaming,
)

ROOT = Path(__file__).resolve().parent.parent
# Initial defaults; administrators can change these without rebuilding.
DESKTOP_TOOLBAR = True


# Defaults also support databases and game profiles created before these settings.
RESOURCE_DEFAULTS = {"memory_mb": 4096, "cpus": 2}
THEME_COLORS = (
    "background",
    "surface",
    "text",
    "muted",
    "accent",
    "accent_text",
    "border",
    "art",
    "danger",
    "danger_background",
    "focus",
    "player_background",
    "player_header",
    "player_text",
)


def validate_resources(data, nullable=False):
    for field, minimum, maximum in (("memory_mb", 128, 1048576), ("cpus", 0.1, 256)):
        if field not in data or (nullable and data[field] is None):
            continue
        value = data[field]
        if (
            type(value) not in (int, float)
            or not minimum <= value <= maximum
            or not math.isfinite(value)
            or (field == "memory_mb" and type(value) is not int)
        ):
            raise ValueError(
                f"{field} must be between {minimum} and {maximum}"
                + (" (whole MiB)" if field == "memory_mb" else "")
            )


def validate_appearance(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid appearance")
    allowed = {
        "theme",
        "colors",
        "font",
        "radius",
        "content_width",
        "logo_url",
        "background_image",
        "footer",
        "custom_css",
    }
    if set(value) - allowed:
        raise ValueError("Unknown appearance setting")
    if value.get("theme", "classic") not in ("classic", "midnight", "forest"):
        raise ValueError("Unknown theme")
    colors = value.get("colors", {})
    if (
        not isinstance(colors, dict)
        or set(colors) - set(THEME_COLORS)
        or any(
            not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c)
            for c in colors.values()
        )
    ):
        raise ValueError("Colors must use #RRGGBB")
    if value.get("font", "trebuchet") not in ("trebuchet", "system", "verdana", "mono"):
        raise ValueError("Unknown font")
    for field, default, minimum, maximum in (
        ("radius", 7, 0, 32),
        ("content_width", 1180, 800, 1920),
    ):
        number = value.get(field, default)
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError("Invalid " + field)
    for field in ("logo_url", "background_image"):
        url = value.get(field, "")
        if (
            not isinstance(url, str)
            or len(url) > 1000
            or (url and not re.match(r"^https?://", url))
        ):
            raise ValueError(field + ": use an HTTP(S) URL")
    for field, length in (("footer", 500), ("custom_css", 20000)):
        if (
            not isinstance(value.get(field, ""), str)
            or len(value.get(field, "")) > length
        ):
            raise ValueError("Invalid " + field)
    return value


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    return salt + ":" + digest


def validate_profile(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid profile")
    for key in ("id", "name", "image"):
        if (
            not isinstance(data.get(key), str)
            or not data[key].strip()
            or len(data[key]) > 200
        ):
            raise ValueError("Missing " + key)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", data["id"]):
        raise ValueError("Invalid game ID")
    command = data.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 64
        or any(not isinstance(x, str) or "\x00" in x or len(x) > 4096 for x in command)
    ):
        raise ValueError("The command must be a list of arguments")
    resolutions = data.get("resolutions", ["1280x720"])
    if not isinstance(resolutions, list) or not 1 <= len(resolutions) <= 12:
        raise ValueError("Invalid resolutions")
    for resolution in resolutions:
        if not isinstance(resolution, str) or not re.fullmatch(
            r"\d{3,4}x\d{3,4}", resolution
        ):
            raise ValueError("Invalid resolution")
        w, h = map(int, resolution.split("x"))
        if not (640 <= w <= 3840 and 480 <= h <= 2160):
            raise ValueError("Resolution out of range")
    env = data.get("env", {})
    if (
        not isinstance(env, dict)
        or len(env) > 40
        or any(
            not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", k)
            or not isinstance(v, str)
            or len(v) > 4096
            or "\x00" in v
            for k, v in env.items()
        )
    ):
        raise ValueError("Invalid environment variables")
    if any(
        k in env
        for k in (
            "DISPLAY",
            "XDG_RUNTIME_DIR",
            "GAMEDOCK_RESOLUTION",
            "GAMEDOCK_STREAMING",
            "GAMEDOCK_ADMIN_SESSION",
            "GAMEDOCK_GPU",
            "GAMEDOCK_GPU_VENDOR",
            "NVIDIA_VISIBLE_DEVICES",
            "NVIDIA_DRIVER_CAPABILITIES",
            "GAMEDOCK_IDLE_FIX",
            "HOME",
        )
    ):
        raise ValueError("Reserved environment variable")
    if (
        not isinstance(data.get("description", ""), str)
        or len(data.get("description", "")) > 2000
    ):
        raise ValueError("Invalid description")
    banner = data.get("banner", "")
    if (
        not isinstance(banner, str)
        or len(banner) > 1000
        or (banner and not re.match(r"^https?://", banner))
    ):
        raise ValueError("Banner: use an HTTP(S) URL")
    default_resolution = data.get("default_resolution", resolutions[0])
    if default_resolution not in resolutions:
        raise ValueError("Default resolution must be one of the available resolutions")
    if type(data.get("internet_access", False)) is not bool:
        raise ValueError("Invalid internet access setting")
    if type(data.get("enabled", True)) is not bool:
        raise ValueError("Invalid game availability")
    if (
        type(data.get("max_per_user", 1)) is not int
        or not 0 <= data.get("max_per_user", 1) <= 100
    ):
        raise ValueError("Game instance limit must be between 0 and 100")
    network_policy = validate_policy(
        data.get("network_policy"), data.get("internet_access", False)
    )
    if type(data.get("pids_limit", 256)) is not int or not 64 <= data.get("pids_limit", 256) <= 16384:
        raise ValueError("Process/thread limit must be an integer between 64 and 16384")
    validate_resources(data, nullable=True)
    validate_streaming(data.get("streaming", {}))
    validate_gpu(data.get("gpu", {}))
    profile = {
        k: data.get(k, default)
        for k, default in [
            ("id", ""),
            ("name", ""),
            ("image", ""),
            ("command", []),
            ("resolutions", resolutions),
            ("env", {}),
            ("description", ""),
            ("banner", ""),
            ("default_resolution", default_resolution),
            ("max_per_user", 1),
            ("enabled", True),
            ("internet_access", False),
            ("pids_limit", 256),
            ("memory_mb", None),
            ("cpus", None),
            ("streaming", {}),
            ("gpu", {"vendor": "none"}),
        ]
    }
    profile["network_policy"] = network_policy
    return profile


class Docker:
    def __init__(self):
        self.namespace = os.getenv("GAMEDOCK_NAMESPACE", "gamedock")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", self.namespace):
            raise RuntimeError(
                "GAMEDOCK_NAMESPACE: use 1 to 40 lowercase letters, digits, underscores, or hyphens"
            )
        self.portal = os.getenv("PORTAL_CONTAINER", os.getenv("HOSTNAME", ""))
        self.http = None
        self.connection_lock = asyncio.Lock()

    async def request(self, method, path, body=None, missing=False):
        async with self.http.request(
            method, "http://docker/v1.45" + path, json=body
        ) as response:
            text = await response.text()
            if missing and response.status == 404:
                return None
            if response.status >= 400:
                raise RuntimeError("Docker: " + text[:300])
            return json.loads(text) if text else None

    async def start(self, sid, uid, profile, resolution):
        name = "gamedock-" + sid
        session_network = "gamedock-session-" + sid
        gateway = "gamedock-gateway-" + sid
        policy = validate_policy(
            profile.get("network_policy"), profile.get("internet_access", False)
        )
        volume = self.namespace + "-user-" + str(uid) + "-" + profile["id"]
        # Docker initializes a fresh named volume from /data, including ownership.
        definition = {
            "Image": profile["image"],
            "Cmd": profile["command"],
            "Env": [
                "GAMEDOCK_RESOLUTION=" + resolution,
                "GAMEDOCK_STREAMING="
                + json.dumps(
                    {
                        key: value
                        for key, value in profile.get(
                            "streaming", STREAMING_DEFAULTS
                        ).items()
                        if STREAMING_FIELDS[key]["group"] != "Viewer"
                    }
                ),
            ]
            + [k + "=" + v for k, v in profile["env"].items()
               if k != "GAMEDOCK_ADMIN_SESSION"]
            + ["GAMEDOCK_ADMIN_SESSION=" + ("1" if profile.get("_admin_session") is True else "0")],
            "Labels": {
                "io.gamedock.managed": "true",
                "io.gamedock.session": sid,
                "io.gamedock.user": str(uid),
            },
            "HostConfig": {
                "Init": True,
                "NetworkMode": "container:" + gateway,
                "Memory": profile["memory_mb"] * 1024**2,
                "NanoCpus": round(profile["cpus"] * 1_000_000_000),
                "PidsLimit": profile.get("pids_limit", 256),
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Mounts": [{"Type": "volume", "Source": volume, "Target": "/data"}],
            },
        }
        # Explicit operator opt-in; never run sessions privileged.
        if os.environ.get("GAMEDOCK_UINPUT") == "1":
            definition["HostConfig"].setdefault("Devices", []).append(
                {
                    "PathOnHost": "/dev/uinput",
                    "PathInContainer": "/dev/uinput",
                    "CgroupPermissions": "rw",
                }
            )
            definition["User"] = "0:0"
            definition["Env"].append("GAMEDOCK_UINPUT=1")
            definition["HostConfig"]["CapAdd"] = ["MKNOD", "SETUID", "SETGID", "CHOWN"]
            definition["HostConfig"]["DeviceCgroupRules"] = ["c 13:* r"]
            definition["HostConfig"]["Tmpfs"] = {
                "/dev/input": "rw,nosuid,noexec,mode=0770,uid=1000,gid=0"
            }
        gpu_host, gpu_env = docker_gpu(profile.get("gpu", {}))
        definition["HostConfig"].update(gpu_host)
        definition["Env"].extend(gpu_env)
        try:
            await self.request(
                "POST",
                "/networks/create",
                {
                    "Name": session_network,
                    "CheckDuplicate": True,
                    "Driver": "bridge",
                    "Internal": policy["mode"] == "offline",
                    "Labels": {
                        "io.gamedock.managed": "true",
                        "io.gamedock.session": sid,
                    },
                },
            )
            await self.request(
                "POST",
                "/networks/" + session_network + "/connect",
                {"Container": self.portal},
            )
            attached = await self.request("GET", "/networks/" + session_network)
            # Explicit service exceptions must never expose the privileged portal
            # or Docker bridge host itself (including custom public-address pools).
            protected = [
                c["IPv4Address"].split("/")[0] + "/32"
                for c in attached.get("Containers", {}).values()
                if c.get("IPv4Address")
            ]
            protected += [
                c["Gateway"] + "/32"
                for c in attached.get("IPAM", {}).get("Config", [])
                if c.get("Gateway")
            ]
            await self.request(
                "POST",
                "/containers/create?name=" + gateway,
                {
                    "Image": os.getenv(
                        "GAMEDOCK_NETWORK_IMAGE", "gamedock-network:local"
                    ),
                    "Env": [
                        "GAMEDOCK_NETWORK_POLICY=" + json.dumps(policy),
                        "GAMEDOCK_NETWORK_PROTECTED=" + json.dumps(protected),
                        "GAMEDOCK_NETWORK_PORTAL_IP="
                        + (protected[0].split("/")[0] if protected else ""),
                    ],
                    "Labels": {
                        "io.gamedock.managed": "true",
                        "io.gamedock.session": sid,
                        "io.gamedock.portal-ip": protected[0].split("/")[0]
                        if protected
                        else "",
                    },
                    "HostConfig": {
                        "NetworkMode": session_network,
                        "CapDrop": ["ALL"],
                        "CapAdd": ["NET_ADMIN"],
                        "SecurityOpt": ["no-new-privileges:true"],
                        "Dns": list(DNS),
                        "Memory": 64 * 1024**2,
                        "PidsLimit": 32,
                        "ReadonlyRootfs": True,
                        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=1m"},
                    },
                },
            )
            await self.request("POST", "/containers/" + gateway + "/start")
            for _ in range(100):
                guard = await self.request("GET", "/containers/" + gateway + "/json")
                if not guard.get("State", {}).get("Running"):
                    raise RuntimeError(
                        "Session network firewall failed; launch blocked"
                    )
                if guard["State"].get("Health", {}).get("Status") == "healthy":
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Session network firewall not ready; launch blocked")
            await self.request("POST", "/containers/create?name=" + name, definition)
            await self.request("POST", "/containers/" + name + "/start")
        except Exception:
            await self.stop(sid)
            raise

    async def inspect(self, sid):
        info = await self.request(
            "GET", "/containers/gamedock-" + sid + "/json", missing=True
        )
        if info and info.get("HostConfig", {}).get("NetworkMode", "").startswith(
            "container:"
        ):
            gateway = await self.request(
                "GET", "/containers/gamedock-gateway-" + sid + "/json", missing=True
            )
            if not gateway or not gateway["State"]["Running"]:
                # Never continue a game with a missing firewall owner.
                await self.stop(sid)
                return None
            info["NetworkSettings"]["Networks"] = gateway["NetworkSettings"]["Networks"]
        return info

    async def ensure_connection(self, sid):
        async with self.connection_lock:
            network = "gamedock-session-" + sid
            info = await self.request("GET", "/networks/" + network)
            if not any(
                c.get("Name") == self.portal or cid.startswith(self.portal)
                for cid, c in info.get("Containers", {}).items()
            ):
                endpoint = {"Container": self.portal}
                gateway = await self.request(
                    "GET", "/containers/gamedock-gateway-" + sid + "/json", missing=True
                )
                if gateway:
                    portal_ip = (
                        gateway.get("Config", {})
                        .get("Labels", {})
                        .get("io.gamedock.portal-ip")
                    )
                    if portal_ip:
                        endpoint["EndpointConfig"] = {
                            "IPAMConfig": {"IPv4Address": portal_ip}
                        }
                await self.request(
                    "POST", "/networks/" + network + "/connect", endpoint
                )

    async def stop(self, sid):
        await self.request(
            "DELETE", "/containers/gamedock-" + sid + "?force=true", missing=True
        )
        await self.request(
            "DELETE",
            "/containers/gamedock-gateway-" + sid + "?force=true",
            missing=True,
        )
        network = "gamedock-session-" + sid
        info = await self.request("GET", "/networks/" + network, missing=True)
        if info:
            if any(
                c.get("Name") == self.portal or cid.startswith(self.portal)
                for cid, c in info.get("Containers", {}).items()
            ):
                await self.request(
                    "POST",
                    "/networks/" + network + "/disconnect",
                    {"Container": self.portal, "Force": True},
                )
            await self.request("DELETE", "/networks/" + network, missing=True)


@web.middleware
async def security(request, handler):
    try:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin != request.app["origin"]:
                raise web.HTTPForbidden(text="Invalid origin")
            if (
                request.path.startswith("/api/")
                and request.content_type != "application/json"
            ):
                raise web.HTTPUnsupportedMediaType(text="JSON is required")
            if request.path.startswith("/api/") and not isinstance(
                await request.json(), dict
            ):
                raise ValueError("A JSON object is required")
        token = request.cookies.get(request.app["cookie_name"], "")
        if request.headers.get("Authorization", "").startswith("Bearer "):
            token = request.headers["Authorization"][7:]
        request["user"] = None
        request["digest"] = hashlib.sha256(token.encode()).hexdigest() if token else ""
        if token:
            row = (
                request.app["db"]
                .execute(
                    "SELECT users.* FROM tokens JOIN users ON users.id=tokens.uid WHERE digest=? AND expires>? AND enabled=1",
                    (hashlib.sha256(token.encode()).hexdigest(), time.time()),
                )
                .fetchone()
            )
            if row:
                request["user"] = dict(row)
        response = await handler(request)
    except ValueError as exc:
        response = web.json_response({"error": str(exc)}, status=400)
    except web.HTTPException as exc:
        response = web.json_response({"error": exc.text}, status=exc.status)
    except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
        request.app["logger"].exception("Runtime unavailable")
        response = web.json_response(
            {"error": "The desktop service did not respond. Please try again."},
            status=503,
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.path.startswith(("/api/", "/desktop/")):
        response.headers["Cache-Control"] = "no-store"
    return response


def user(request, admin=False):
    u = request["user"]
    if not u:
        raise web.HTTPUnauthorized(text="Sign in")
    if admin and not u["admin"]:
        raise web.HTTPForbidden(text="Administrator access is required")
    return u


def config(app):
    saved = json.loads(
        app["db"].execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
    )
    return {
        "desktop_toolbar": DESKTOP_TOOLBAR,
        "invite_required": True,
        "idle_minutes": 30,
        "viewer_action": "disabled",
        "viewer_disconnect_seconds": 60,
        "viewer_first_connect_seconds": 180,
        **RESOURCE_DEFAULTS,
        "appearance": {},
        **saved,
        "streaming": {**STREAMING_DEFAULTS, **saved.get("streaming", {})},
    }


def policy(app, uid):
    row = (
        app["db"]
        .execute("SELECT definition FROM user_policies WHERE uid=?", (uid,))
        .fetchone()
    )
    return json.loads(row[0]) if row else {"max_instances": None, "games": None}


def game_limit(app, u, game):
    if u["admin"]:
        return 100
    grants = policy(app, u["id"])["games"]
    return min(
        game.get("max_per_user", 1),
        grants.get(game["id"], 0) if grants is not None else 100,
    )


def public_user(u):
    return {k: u[k] for k in ("id", "username", "admin", "enabled")}


async def catalog(request):
    cfg = config(request.app)
    games = (
        [
            json.loads(r[0])
            for r in request.app["db"].execute(
                "SELECT definition FROM games ORDER BY id"
            )
        ]
        if request["user"]
        else []
    )
    if request["user"] and not request["user"]["admin"]:
        games = [
            {k: v for k, v in g.items() if k not in ("env", "command", "image")}
            for g in games
            if g.get("enabled", True)
            and game_limit(request.app, request["user"], g) > 0
        ]
    return web.json_response(
        {
            "settings": cfg,
            "user": public_user(request["user"]) if request["user"] else None,
            "games": games,
            "streaming_schema": STREAMING_FIELDS
            if request["user"] and request["user"]["admin"]
            else None,
            "streaming_presets": STREAMING_PRESETS
            if request["user"] and request["user"]["admin"]
            else None,
            "policy": policy(request.app, request["user"]["id"])
            if request["user"]
            else None,
        }
    )


async def auth(request):
    app = request.app
    # Limit password hashing and brute force by actual TCP peer; no trusted proxy headers.
    now = time.time()
    key = request.remote or "unknown"
    attempts = app["attempts"]
    attempts[key] = [t for t in attempts.get(key, []) if t > now - 60]
    if len(attempts[key]) >= 15:
        raise web.HTTPTooManyRequests(text="Wait a minute before trying again")
    attempts[key].append(now)
    if len(attempts) > 10000:
        for peer in list(attempts):
            if not attempts[peer] or attempts[peer][-1] < now - 60:
                del attempts[peer]
    body = await request.json()
    username, password = body.get("username", ""), body.get("password", "")
    if not isinstance(username, str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{3,32}", username
    ):
        raise ValueError("Username: 3 to 32 letters, digits, hyphens, or underscores")
    username = username.lower()
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise ValueError("Password: 10 to 256 characters")
    if request.match_info["action"] == "register":
        if not config(app)["registration"]:
            raise web.HTTPForbidden(text="Registration is closed")
        invitation = body.get("invite", "")
        if not isinstance(invitation, str) or len(invitation) > 128:
            raise ValueError("Invalid invitation code")
        hashed = await asyncio.to_thread(password_hash, password)
        try:
            app["db"].execute("BEGIN IMMEDIATE")
            if config(app)["invite_required"]:
                digest = hashlib.sha256(invitation.strip().encode()).hexdigest()
                result = app["db"].execute(
                    "UPDATE invitations SET uses=uses+1 WHERE digest=? AND revoked=0 AND uses<max_uses AND (expires IS NULL OR expires>?)",
                    (digest, time.time()),
                )
                if result.rowcount != 1:
                    raise web.HTTPForbidden(
                        text="An invitation code is required or the code has expired"
                    )
            app["db"].execute(
                "INSERT INTO users(username,password) VALUES (?,?)", (username, hashed)
            )
            app["db"].execute("COMMIT")
        except sqlite3.IntegrityError:
            app["db"].execute("ROLLBACK")
            raise web.HTTPConflict(text="That username already exists")
        except Exception:
            app["db"].execute("ROLLBACK")
            raise
    row = (
        app["db"]
        .execute("SELECT * FROM users WHERE username=?", (username,))
        .fetchone()
    )
    expected = row["password"] if row else app["dummy_hash"]
    hashed = await asyncio.to_thread(password_hash, password, expected.split(":")[0])
    if not hmac.compare_digest(hashed, expected) or not row or not row["enabled"]:
        raise web.HTTPUnauthorized(text="Invalid credentials")
    token = secrets.token_urlsafe(32)
    app["db"].execute("DELETE FROM tokens WHERE expires<=?", (now,))
    app["db"].execute(
        "INSERT INTO tokens VALUES (?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), row["id"], now + 86400),
    )
    response = web.json_response({"user": public_user(row), "token": token})
    response.set_cookie(
        request.app["cookie_name"],
        token,
        httponly=True,
        samesite="Strict",
        secure=app["origin"].startswith("https://"),
        max_age=86400,
        path="/",
    )
    return response


async def logout(request):
    user(request)
    request.app["db"].execute("DELETE FROM tokens WHERE digest=?", (request["digest"],))
    response = web.json_response({"ok": True})
    response.del_cookie(request.app["cookie_name"], path="/")
    return response


def owned(request):
    u = user(request)
    sid = request.match_info["sid"]
    if not re.fullmatch(r"[a-f0-9]{32}", sid):
        raise web.HTTPNotFound(text="Instance not found")
    row = (
        request.app["db"]
        .execute("SELECT * FROM instances WHERE id=?", (sid,))
        .fetchone()
    )
    if not row or (row["uid"] != u["id"] and not u["admin"]):
        raise web.HTTPNotFound(text="Instance not found")
    return dict(row)


async def instances(request):
    u = user(request)
    app = request.app
    if request.method == "GET":
        async with app["launch_lock"]:
            rows = (
                app["db"]
                .execute(
                    "SELECT * FROM instances WHERE uid=? OR ?=1 ORDER BY created DESC",
                    (u["id"], u["admin"]),
                )
                .fetchall()
            )
            result = []
            for row in rows:
                item = dict(row)
                if item["status"] in ("running", "starting"):
                    info = await app["docker"].inspect(item["id"])
                    item["status"] = (
                        "running" if info and info["State"]["Running"] else "stopped"
                    )
                    if info and not info["State"]["Running"]:
                        await app["docker"].stop(item["id"])
                    app["db"].execute(
                        "UPDATE instances SET status=? WHERE id=?",
                        (item["status"], item["id"]),
                    )
                item["viewers"] = (
                    app["viewers"]
                    .setdefault(item["id"], Presence())
                    .report(config(app), time.time())
                )
                result.append(item)
            return web.json_response(result)
    body = await request.json()
    async with app["launch_lock"]:
        if (
            not app["db"]
            .execute("SELECT 1 FROM users WHERE id=? AND enabled=1", (u["id"],))
            .fetchone()
        ):
            raise web.HTTPForbidden(text="Account disabled")
        cfg = config(app)
        # Reconcile before enforcing limits; stopped containers don't consume slots.
        for row in (
            app["db"]
            .execute("SELECT id FROM instances WHERE status IN ('starting','running')")
            .fetchall()
        ):
            info = await app["docker"].inspect(row["id"])
            if not info or not info["State"]["Running"]:
                if info:
                    await app["docker"].stop(row["id"])
                app["db"].execute(
                    "UPDATE instances SET status='stopped' WHERE id=?", (row["id"],)
                )
        count = (
            app["db"]
            .execute(
                "SELECT count(*) FROM instances WHERE status IN ('starting','running')"
            )
            .fetchone()[0]
        )
        own = (
            app["db"]
            .execute(
                "SELECT count(*) FROM instances WHERE uid=? AND status IN ('starting','running')",
                (u["id"],),
            )
            .fetchone()[0]
        )
        user_limit = policy(app, u["id"])["max_instances"]
        if count >= cfg["max_instances"] or own >= min(
            cfg["per_user"],
            user_limit if user_limit is not None and not u["admin"] else 100,
        ):
            raise web.HTTPConflict(text="The instance limit has been reached")
        row = (
            app["db"]
            .execute("SELECT definition FROM games WHERE id=?", (body.get("game"),))
            .fetchone()
        )
        if not row:
            raise ValueError("Game not found")
        profile = json.loads(row[0])
        limit = game_limit(app, u, profile)
        if not u["admin"] and (not profile.get("enabled", True) or limit <= 0):
            raise web.HTTPForbidden(text="You do not have access to this game")
        game_count = (
            app["db"]
            .execute(
                "SELECT count(*) FROM instances WHERE uid=? AND game=? AND status IN ('starting','running')",
                (u["id"], profile["id"]),
            )
            .fetchone()[0]
        )
        if game_count >= limit:
            raise web.HTTPConflict(
                text="The instance limit for this game has been reached"
            )
        default_resolution = profile.get(
            "default_resolution", profile["resolutions"][0]
        )
        resolution = body.get("resolution", default_resolution)
        if not u["admin"] and resolution != default_resolution:
            raise web.HTTPForbidden(text="Only administrators can choose a resolution")
        if resolution not in profile["resolutions"]:
            raise ValueError("Resolution not allowed")
        profile = {
            **profile,
            **{
                key: profile.get(key) if profile.get(key) is not None else cfg[key]
                for key in RESOURCE_DEFAULTS
            },
        }
        profile["streaming"] = validate_streaming(
            {**cfg["streaming"], **profile.get("streaming", {})}, complete=True
        )
        # Launch authority comes only from the authenticated account, never
        # request JSON or a stored game profile. This metadata is not persisted.
        profile["_admin_session"] = bool(u["admin"])
        sid = secrets.token_hex(16)
        app["db"].execute(
            "INSERT INTO instances(id,uid,game,resolution,status,created,last_activity) VALUES (?,?,?,?,?,?,?)",
            (
                sid,
                u["id"],
                profile["id"],
                resolution,
                "starting",
                time.time(),
                time.time(),
            ),
        )
        try:
            await app["docker"].start(sid, u["id"], profile, resolution)
        except Exception:
            app["db"].execute("UPDATE instances SET status='failed' WHERE id=?", (sid,))
            raise
        app["db"].execute("UPDATE instances SET status='running' WHERE id=?", (sid,))
        app["viewers"][sid] = Presence(known=True, since=time.time())
    return web.json_response(
        {"id": sid, "url": "/play/" + sid, "status": "running"}, status=201
    )


async def terminate(request):
    instance = owned(request)
    async with request.app["launch_lock"]:
        await request.app["docker"].stop(instance["id"])
        request.app["db"].execute(
            "UPDATE instances SET status='stopped' WHERE id=?", (instance["id"],)
        )
    return web.json_response({"ok": True})


async def admin_settings(request):
    user(request, True)
    body = await request.json()
    cfg = config(request.app)
    for field in ("name", "banner"):
        if field in body:
            if not isinstance(body[field], str) or len(body[field]) > (
                80 if field == "name" else 500
            ):
                raise ValueError("Invalid settings")
            cfg[field] = body[field]
    if not cfg["name"].strip():
        raise ValueError("The name cannot be empty")
    if "banner_image" in body:
        image = body["banner_image"]
        if (
            not isinstance(image, str)
            or len(image) > 1000
            or (image and not re.match(r"^https?://", image))
        ):
            raise ValueError("Banner image: use an HTTP(S) URL")
        cfg["banner_image"] = image
    for field in ("registration", "desktop_toolbar", "invite_required"):
        if field in body:
            if type(body[field]) is not bool:
                raise ValueError("Invalid " + field)
            cfg[field] = body[field]
    if "viewer_action" in body:
        if body["viewer_action"] not in ("disabled", "stop"):
            raise ValueError("Invalid viewer disconnect action")
        cfg["viewer_action"] = body["viewer_action"]
    for key in ("viewer_disconnect_seconds", "viewer_first_connect_seconds"):
        if key in body:
            if type(body[key]) is not int or not 1 <= body[key] <= 86400:
                raise ValueError(
                    "Viewer grace periods must be between 1 and 86400 seconds"
                )
            cfg[key] = body[key]
    if "idle_minutes" in body:
        if (
            type(body["idle_minutes"]) is not int
            or not 0 <= body["idle_minutes"] <= 1440
        ):
            raise ValueError("Inactivity timeout must be between 0 and 1440 minutes")
        cfg["idle_minutes"] = body["idle_minutes"]
    for field in ("max_instances", "per_user"):
        if field in body:
            if type(body[field]) is not int or not 1 <= body[field] <= 100:
                raise ValueError("Invalid limit")
            cfg[field] = body[field]
    validate_resources(body)
    for key in RESOURCE_DEFAULTS:
        if key in body:
            cfg[key] = body[key]
    if "streaming" in body:
        cfg["streaming"] = validate_streaming(
            {**cfg["streaming"], **validate_streaming(body["streaming"])}, complete=True
        )
    if "appearance" in body:
        cfg["appearance"] = validate_appearance(body["appearance"])
    request.app["db"].execute(
        "UPDATE settings SET value=? WHERE id=1", (json.dumps(cfg),)
    )
    return web.json_response(cfg)


async def admin_games(request):
    user(request, True)
    if request.method == "PATCH":
        body = await request.json()
        if (
            not isinstance(body, dict)
            or set(body) != {"enabled"}
            or type(body["enabled"]) is not bool
        ):
            raise web.HTTPBadRequest(text="Expected an enabled boolean")
        row = (
            request.app["db"]
            .execute(
                "SELECT definition FROM games WHERE id=?", (request.match_info["game"],)
            )
            .fetchone()
        )
        if not row:
            raise web.HTTPNotFound(text="Game not found")
        profile = json.loads(row["definition"])
        profile["enabled"] = body["enabled"]
        request.app["db"].execute(
            "UPDATE games SET definition=? WHERE id=?",
            (json.dumps(profile), request.match_info["game"]),
        )
        return web.json_response(profile)
    if request.method == "DELETE":
        request.app["db"].execute(
            "DELETE FROM games WHERE id=?", (request.match_info["game"],)
        )
        return web.json_response({"ok": True})
    profile = validate_profile(await request.json())
    request.app["db"].execute(
        "INSERT OR REPLACE INTO games VALUES (?,?)",
        (profile["id"], json.dumps(profile)),
    )
    return web.json_response(profile)


async def admin_users(request):
    current = user(request, True)
    if request.method == "GET":
        return web.json_response(
            [
                {**public_user(r), "policy": policy(request.app, r["id"])}
                for r in request.app["db"].execute("SELECT * FROM users ORDER BY id")
            ]
        )
    uid = int(request.match_info["uid"])
    body = await request.json()
    if (
        not request.app["db"]
        .execute("SELECT 1 FROM users WHERE id=?", (uid,))
        .fetchone()
    ):
        raise web.HTTPNotFound(text="Account not found")
    if "policy" in body:
        value = body["policy"]
        if not isinstance(value, dict):
            raise ValueError("Invalid account limits")
        maximum, games = value.get("max_instances"), value.get("games")
        if maximum is not None and (
            type(maximum) is not int or not 0 <= maximum <= 100
        ):
            raise ValueError("Account limit must be between 0 and 100")
        if games is not None and (
            not isinstance(games, dict)
            or any(
                not isinstance(k, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", k)
                or type(v) is not int
                or not 0 <= v <= 100
                for k, v in games.items()
            )
        ):
            raise ValueError("Invalid game allowances")
        if games is not None and any(
            not request.app["db"]
            .execute("SELECT 1 FROM games WHERE id=?", (k,))
            .fetchone()
            for k in games
        ):
            raise ValueError("Unknown game in account limits")
        request.app["db"].execute(
            "INSERT OR REPLACE INTO user_policies VALUES (?,?)",
            (uid, json.dumps({"max_instances": maximum, "games": games})),
        )
        return web.json_response({"ok": True})
    if uid == current["id"]:
        raise ValueError("You cannot disable your own account")
    if type(body.get("enabled")) is not bool:
        raise ValueError("Invalid status")
    async with request.app["launch_lock"]:
        request.app["db"].execute(
            "UPDATE users SET enabled=? WHERE id=?", (int(body["enabled"]), uid)
        )
        if not body["enabled"]:
            request.app["db"].execute("DELETE FROM tokens WHERE uid=?", (uid,))
            for row in (
                request.app["db"]
                .execute(
                    "SELECT id FROM instances WHERE uid=? AND status IN ('starting','running')",
                    (uid,),
                )
                .fetchall()
            ):
                await request.app["docker"].stop(row["id"])
                request.app["db"].execute(
                    "UPDATE instances SET status='stopped' WHERE id=?", (row["id"],)
                )
    return web.json_response({"ok": True})


async def proxy(request):
    instance = owned(request)
    origin = request.headers.get("Origin")
    if origin and origin != request.app["origin"]:
        raise web.HTTPForbidden(text="Invalid origin")
    # Selkies multiplexes video, audio and control on one streaming socket.
    # File-manager/auxiliary sockets are not viewers. Keep the root path for
    # existing runtimes during a rolling image migration.
    streaming = request.match_info.get("tail", "") in ("", "api/websockets")
    if request.headers.get("Upgrade", "").lower() != "websocket" or not streaming:
        return await desktop_proxy(request)
    app, sid, token = request.app, instance["id"], object()
    # Reserve before any network await. Cleanup and incoming handshakes share a lock.
    async with app["launch_lock"]:
        instance = owned(request)
        if instance["status"] != "running":
            raise web.HTTPConflict(text="Instance stopped")
        presence = app["viewers"].setdefault(sid, Presence())
        presence.connect(token)
    try:
        return await desktop_proxy(request)
    finally:
        async with app["launch_lock"]:
            presence.disconnect(token, time.time())


async def desktop_proxy(request):
    instance = owned(request)
    origin = request.headers.get("Origin")
    if origin and origin != request.app["origin"]:
        raise web.HTTPForbidden(text="Invalid origin")
    if instance["status"] != "running":
        raise web.HTTPConflict(text="Instance stopped")
    info = await request.app["docker"].inspect(instance["id"])
    if not info or not info["State"]["Running"]:
        raise web.HTTPGone(text="The desktop has stopped")
    await request.app["docker"].ensure_connection(instance["id"])
    # Resolve only the container's network address; never accept a client-supplied target.
    network = info["NetworkSettings"]["Networks"].get(
        "gamedock-session-" + instance["id"]
    )
    if not network or not network["IPAddress"]:
        raise web.HTTPServiceUnavailable(text="The desktop is not ready yet")
    from yarl import URL

    tail = request.match_info.get(
        "tail", "gamedock-controller" if request.method == "POST" else ""
    )
    target = URL.build(
        scheme="http",
        host=network["IPAddress"],
        port=6084,
        path="/" + tail,
        query_string=request.query_string,
    )
    http = request.app["http"]
    native_api = (tail.startswith("api/") and bool(request["user"]["admin"])
                  and instance["uid"] == request["user"]["id"])
    if request.method not in ("GET", "HEAD") and tail != "gamedock-controller" and not native_api:
        raise web.HTTPForbidden(text="Native desktop settings require administrator access")
    if request.method == "POST" and tail == "gamedock-controller":
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(text="JSON is required")
        body = await request.json()
        from runtime.gamepad import validate_state

        axes, buttons = validate_state(body)
        if (
            any(abs(value) > 0.15 for value in axes) or any(buttons)
        ) and time.time() - instance["last_activity"] >= 5:
            request.app["db"].execute(
                "UPDATE instances SET last_activity=? WHERE id=? AND status='running'",
                (time.time(), instance["id"]),
            )
        target = target.with_port(6085).with_path("/").with_query(None)
        try:
            async with http.post(
                target, json=body, timeout=aiohttp.ClientTimeout(total=2)
            ) as upstream:
                return web.Response(
                    status=upstream.status,
                    body=await upstream.read(),
                    content_type="application/json",
                )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPServiceUnavailable(
                text="Controller requires an updated runtime image"
            )
    if request.headers.get("Upgrade", "").lower() == "websocket":
        protocols = [
            p.strip()
            for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if p.strip()
        ]
        # The streaming backend owns heartbeat and RTT measurement. Acknowledging
        # control frames here would measure only the backend-to-portal hop.
        async with http.ws_connect(
            target, protocols=protocols, max_msg_size=16 * 1024**2, autoping=False
        ) as upstream:
            downstream = web.WebSocketResponse(
                protocols=protocols, max_msg_size=16 * 1024**2, autoping=False
            )
            await downstream.prepare(request)
            presence = request.app["viewers"].get(instance["id"])
            if presence and request.match_info.get("tail", "") in ("", "api/websockets"):
                presence.ever_seen = True

            async def pump(source, dest):
                async for message in source:
                    # Revocation applies to already connected desktops too.
                    if (
                        not request.app["db"]
                        .execute(
                            "SELECT 1 FROM users WHERE id=? AND enabled=1",
                            (request["user"]["id"],),
                        )
                        .fetchone()
                    ):
                        break
                    if message.type == aiohttp.WSMsgType.BINARY:
                        await dest.send_bytes(message.data)
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        await dest.send_str(message.data)
                    elif message.type == aiohttp.WSMsgType.PING:
                        await dest.ping(message.data)
                    elif message.type == aiohttp.WSMsgType.PONG:
                        await dest.pong(message.data)
                await dest.close()

            async def revocation():
                while True:
                    await asyncio.sleep(1)
                    valid = (
                        request.app["db"]
                        .execute(
                            "SELECT 1 FROM tokens JOIN users ON users.id=tokens.uid WHERE digest=? AND expires>? AND enabled=1",
                            (request["digest"], time.time()),
                        )
                        .fetchone()
                    )
                    running = (
                        request.app["db"]
                        .execute(
                            "SELECT 1 FROM instances WHERE id=? AND status='running'",
                            (instance["id"],),
                        )
                        .fetchone()
                    )
                    if not valid or not running:
                        await downstream.close()
                        await upstream.close()
                        return

            tasks = [
                asyncio.create_task(pump(upstream, downstream)),
                asyncio.create_task(pump(downstream, upstream)),
                asyncio.create_task(revocation()),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await downstream.close()
            return downstream
    try:
        async with http.request(
            request.method, target, allow_redirects=False,
            data=await request.read() if native_api and request.method not in ("GET", "HEAD") else None,
            headers={"Content-Type": request.headers["Content-Type"]} if "Content-Type" in request.headers else {},
        ) as upstream:
            body = await upstream.read()
            headers = {
                k: v
                for k, v in upstream.headers.items()
                if k.lower() in ("content-type", "content-encoding", "cache-control")
            }
            headers["Cache-Control"] = "no-store"
            return web.Response(body=body, status=upstream.status, headers=headers)
    except aiohttp.ClientConnectorError:
        if tail:
            raise
        return web.Response(
            status=503,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
            text="""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="2"><title>Starting desktop</title><link rel="stylesheet" href="/assets/style.css"><main style="padding-top:12vh"><h1>Starting your desktop.</h1><p>It will open automatically in a few seconds.</p><a href="/">Back to the library</a></main></html>""",
        )


async def player(request):
    instance = owned(request)
    if instance["status"] != "running":
        return web.Response(status=302, headers={"Location": "/"})
    return await platform_page(request, "player.html")


async def instance_details(request):
    return web.json_response(owned(request))


async def activity(request):
    instance = owned(request)
    if instance["status"] != "running":
        raise web.HTTPConflict(text="Instance stopped")
    async with request.app["launch_lock"]:
        request.app["db"].execute(
            "UPDATE instances SET last_activity=? WHERE id=? AND status='running'",
            (time.time(), instance["id"]),
        )
    return web.json_response({"ok": True})


async def expire_idle(app, now=None):
    minutes = config(app)["idle_minutes"]
    if not minutes:
        return
    async with app["launch_lock"]:
        for row in (
            app["db"]
            .execute(
                "SELECT id FROM instances WHERE status='running' AND last_activity<=?",
                ((time.time() if now is None else now) - minutes * 60,),
            )
            .fetchall()
        ):
            await app["docker"].stop(row["id"])
            app["db"].execute(
                "UPDATE instances SET status='stopped' WHERE id=?", (row["id"],)
            )


async def query_viewers(app, sid):
    """Internal-only, bounded, cheap snapshot. Never query full streaming diagnostics."""
    info = await app["docker"].inspect(sid)
    if not info or not info["State"]["Running"]:
        raise DesktopStopped()
    await app["docker"].ensure_connection(sid)
    network = info["NetworkSettings"]["Networks"]["gamedock-session-" + sid]
    from yarl import URL

    target = URL.build(
        scheme="http", host=network["IPAddress"], port=6085, path="/viewers"
    )
    async with app["http"].get(
        target, timeout=aiohttp.ClientTimeout(total=2)
    ) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.content.iter_chunked(4097):
            body.extend(chunk)
            if len(body) > 4096:
                raise ValueError("Invalid viewer snapshot size")
        data = json.loads(body)
    updated = data["updated"]
    if type(updated) not in (int, float) or not 0 <= time.time() - updated <= 5:
        raise ValueError("Stale viewer presence")
    return data


async def stop_unviewed(app, sid):
    try:
        await app["docker"].stop(sid)
    except Exception:
        app["logger"].exception("Viewer cleanup failed for %s; retrying", sid)
        return
    app["db"].execute(
        "UPDATE instances SET status='stopped' WHERE id=? AND status='running'", (sid,)
    )


async def expire_viewers(app, now=None):
    rows = (
        app["db"].execute("SELECT id FROM instances WHERE status='running'").fetchall()
    )
    for row in rows:
        sid = row["id"]
        async with app["launch_lock"]:
            cfg = config(app)
            clock = time.time() if now is None else now
            presence = app["viewers"].setdefault(sid, Presence())
            if presence.leases:
                continue
            # Also reconcile unknown sessions while disabled so the panel is useful.
            if (
                presence.known
                and not presence.observed
                and not presence.due(cfg, clock)
            ):
                continue
            generation = presence.generation
        # Do not block incoming viewer reservations while waiting for the runtime.
        try:
            data = await query_viewers(app, sid)
        except DesktopStopped:
            # Also finish a previous partial stop (game removed, guard/network
            # cleanup failed). Unknown/failed queries never enter this path.
            async with app["launch_lock"]:
                if generation == presence.generation and not presence.leases:
                    running = (
                        app["db"]
                        .execute(
                            "SELECT 1 FROM instances WHERE id=? AND status='running'",
                            (sid,),
                        )
                        .fetchone()
                    )
                    if running:
                        await stop_unviewed(app, sid)
            continue
        except Exception:
            async with app["launch_lock"]:
                if generation == presence.generation and not presence.leases:
                    presence.known = False
            continue
        async with app["launch_lock"]:
            if presence.leases or generation != presence.generation:
                continue  # A connection changed while we sampled; discard stale data.
            running = (
                app["db"]
                .execute(
                    "SELECT 1 FROM instances WHERE id=? AND status='running'", (sid,)
                )
                .fetchone()
            )
            if not running:
                continue
            cfg = config(app)
            clock = time.time() if now is None else now
            try:
                presence.reconcile(data, clock, app["portal_started"])
            except (KeyError, TypeError, ValueError):
                presence.known = False
                continue
            # Atomic final check through stop. Handshakes reserve using this lock.
            if presence.due(cfg, clock) and not presence.leases:
                await stop_unviewed(app, sid)


async def idle_worker(app):
    while True:
        await asyncio.sleep(5)
        for cleanup in (expire_idle, expire_viewers):
            try:
                await cleanup(app)
            except Exception:
                app["logger"].exception("Session cleanup failed; retrying")


async def invitations(request):
    user(request, True)
    db = request.app["db"]
    if request.method == "GET":
        return web.json_response(
            [
                dict(row)
                for row in db.execute(
                    "SELECT id,label,max_uses,uses,expires,revoked FROM invitations ORDER BY rowid DESC"
                )
            ]
        )
    if request.method == "DELETE":
        db.execute(
            "UPDATE invitations SET revoked=1 WHERE id=?", (request.match_info["iid"],)
        )
        return web.json_response({"ok": True})
    body = await request.json()
    label, uses, days = (
        body.get("label", ""),
        body.get("max_uses", 1),
        body.get("expires_days", 7),
    )
    if not isinstance(label, str) or len(label) > 100:
        raise ValueError("Invitation label must be at most 100 characters")
    if type(uses) is not int or not 1 <= uses <= 1000:
        raise ValueError("Invitation uses must be between 1 and 1000")
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError("Invitation validity must be between 1 and 365 days")
    code = secrets.token_urlsafe(24)
    iid = secrets.token_hex(16)
    db.execute(
        "INSERT INTO invitations(id,digest,label,max_uses,expires) VALUES (?,?,?,?,?)",
        (
            iid,
            hashlib.sha256(code.encode()).hexdigest(),
            label,
            uses,
            time.time() + days * 86400,
        ),
    )
    return web.json_response({"id": iid, "code": code}, status=201)


async def lifecycle(app):
    app["http"] = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), auto_decompress=False
    )
    app["docker"].http = aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(
            path=os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
        ),
        timeout=aiohttp.ClientTimeout(total=45),
    )
    cleanup = asyncio.create_task(idle_worker(app))
    yield
    cleanup.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup
    await app["http"].close()
    await app["docker"].http.close()
    app["db"].close()


async def admin_page(request):
    if not request["user"]:
        return web.Response(status=302, headers={"Location": "/"})
    user(request, True)
    return await platform_page(request, "admin.html")


async def platform_page(request, filename="index.html"):
    name = html.escape(config(request.app)["name"])
    document = request.app["pages"][filename].replace("GameDock", name)
    document = document.replace(
        '"/assets/', '"/assets/' + request.app["asset_version"] + "/"
    )
    return web.Response(
        text=document,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "X-GameDock-Build": request.app["asset_version"],
        },
    )


async def asset(request):
    path = request.match_info["path"]
    versioned = "/" in path
    if versioned:
        version, path = path.split("/", 1)
        if version != request.app["asset_version"]:
            return web.Response(
                status=410,
                text="The interface has been updated. Reload this page.",
                headers={"Cache-Control": "no-store"},
            )
    data = request.app["assets"].get(path)
    if data is None:
        raise web.HTTPNotFound()
    return web.Response(
        body=data,
        content_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable"
            if versioned
            else "no-store",
            "X-GameDock-Build": request.app["asset_version"],
        },
    )


def create_app(db_path=None, docker=None):
    import logging

    app = web.Application(middlewares=[security], client_max_size=64 * 1024)
    app["logger"] = logging.getLogger("gamedock")
    # Freeze a coherent bundle at startup, including HTML referencing its version.
    files = {
        p.name: p.read_bytes() for p in sorted((ROOT / "web").iterdir()) if p.is_file()
    }
    app["assets"] = {
        name: data for name, data in files.items() if not name.endswith(".html")
    }
    app["pages"] = {
        name: data.decode() for name, data in files.items() if name.endswith(".html")
    }
    app["asset_version"] = hashlib.sha256(
        b"".join(name.encode() + b"\0" + data for name, data in files.items())
    ).hexdigest()
    app["origin"] = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")
    cookie_name = os.getenv("GAMEDOCK_SESSION_COOKIE", "gamedock")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cookie_name):
        raise ValueError("Invalid session cookie name")
    app["cookie_name"] = cookie_name
    path = db_path or os.getenv("DATABASE", "/data/gamedock.sqlite")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        """CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS tokens(digest TEXT PRIMARY KEY,uid INTEGER NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,definition TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS instances(id TEXT PRIMARY KEY,uid INTEGER NOT NULL,game TEXT NOT NULL,resolution TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);"""
    )
    db.executescript(
        """CREATE TABLE IF NOT EXISTS user_policies(uid INTEGER PRIMARY KEY,definition TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS invitations(id TEXT PRIMARY KEY,digest TEXT UNIQUE NOT NULL,label TEXT NOT NULL,max_uses INTEGER NOT NULL,uses INTEGER NOT NULL DEFAULT 0,expires REAL,revoked INTEGER NOT NULL DEFAULT 0);"""
    )
    if "last_activity" not in {
        row[1] for row in db.execute("PRAGMA table_info(instances)")
    }:
        db.execute(
            "ALTER TABLE instances ADD COLUMN last_activity REAL NOT NULL DEFAULT 0"
        )
        db.execute("UPDATE instances SET last_activity=?", (time.time(),))
    fresh = not db.execute("SELECT 1 FROM settings").fetchone()
    db.execute(
        "INSERT OR IGNORE INTO settings VALUES (1,?)",
        (
            json.dumps(
                {
                    "name": "GameDock",
                    "banner": "Your library. Your desktop. Ready to play.",
                    "registration": True,
                    "max_instances": 8,
                    "per_user": 2,
                }
            ),
        ),
    )
    if not db.execute("SELECT 1 FROM users WHERE admin=1").fetchone():
        password = os.getenv("ADMIN_PASSWORD", "")
        if len(password) < 12:
            raise RuntimeError(
                "Set ADMIN_PASSWORD to at least 12 characters before the first startup"
            )
        username = os.getenv("ADMIN_USER", "admin").lower()
        if not re.fullmatch(r"[a-z0-9_-]{3,32}", username):
            raise RuntimeError("Invalid ADMIN_USER")
        db.execute(
            "INSERT INTO users(username,password,admin) VALUES (?,?,1)",
            (username, password_hash(password)),
        )
    if fresh:
        profile = validate_profile(
            {
                "id": "desktop",
                "name": "Test desktop",
                "image": "gamedock-runtime:local",
                "command": ["xterm"],
                "resolutions": ["1280x720", "1920x1080"],
                "description": "An isolated desktop for testing the connection, keyboard, and resolution.",
            }
        )
        db.execute(
            "INSERT INTO games VALUES (?,?)", (profile["id"], json.dumps(profile))
        )
    app["db"], app["docker"] = db, docker or Docker()
    app["dummy_hash"] = password_hash(secrets.token_hex(20))
    app["attempts"], app["launch_lock"] = {}, asyncio.Lock()
    app["viewers"], app["portal_started"] = {}, time.time()
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/catalog", catalog)
    app.router.add_post("/api/auth/{action:login|register}", auth)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/instances", instances)
    app.router.add_post("/api/instances", instances)
    app.router.add_delete("/api/instances/{sid}", terminate)
    app.router.add_get("/play/{sid}", player)
    app.router.add_post("/api/instances/{sid}/activity", activity)
    app.router.add_get("/api/instances/{sid}", instance_details)
    app.router.add_get("/api/admin/invitations", invitations)
    app.router.add_post("/api/admin/invitations", invitations)
    app.router.add_delete("/api/admin/invitations/{iid}", invitations)
    app.router.add_put("/api/admin/settings", admin_settings)
    app.router.add_put("/api/admin/games", admin_games)
    app.router.add_patch("/api/admin/games/{game}", admin_games)
    app.router.add_delete("/api/admin/games/{game}", admin_games)
    app.router.add_get("/api/admin/users", admin_users)
    app.router.add_patch("/api/admin/users/{uid}", admin_users)
    app.router.add_post("/desktop/{sid}/gamedock-controller", proxy)
    app.router.add_route("*", "/desktop/{sid}/{tail:.*}", proxy)
    app.router.add_get("/", platform_page)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/admin/", admin_page)
    app.router.add_get("/assets/{path:.*}", asset)
    return app


if __name__ == "__main__":
    from server.tls import server_tls

    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        ssl_context=server_tls(),
    )
