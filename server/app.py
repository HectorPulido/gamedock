import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
# Show Xpra's floating controls by default. Set False for a clean game view.
DESKTOP_TOOLBAR = True


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
        k in env for k in ("DISPLAY", "XDG_RUNTIME_DIR", "GAMEDOCK_RESOLUTION", "HOME")
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
    return {
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
        ]
    }


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
        volume = self.namespace + "-user-" + str(uid) + "-" + profile["id"]
        # Docker initializes a fresh named volume from /data, including ownership.
        definition = {
            "Image": profile["image"],
            "Cmd": profile["command"],
            "Env": ["GAMEDOCK_RESOLUTION=" + resolution]
            + [k + "=" + v for k, v in profile["env"].items()],
            "Labels": {
                "io.gamedock.managed": "true",
                "io.gamedock.session": sid,
                "io.gamedock.user": str(uid),
            },
            "HostConfig": {
                "Init": True,
                "NetworkMode": session_network,
                "Memory": 4 * 1024**3,
                "NanoCpus": 2_000_000_000,
                "PidsLimit": 256,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Mounts": [{"Type": "volume", "Source": volume, "Target": "/data"}],
            },
            "ExposedPorts": {"6084/tcp": {}},
        }
        try:
            await self.request(
                "POST",
                "/networks/create",
                {
                    "Name": session_network,
                    "CheckDuplicate": True,
                    "Driver": "bridge",
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
            await self.request("POST", "/containers/create?name=" + name, definition)
            await self.request("POST", "/containers/" + name + "/start")
        except Exception:
            await self.stop(sid)
            raise

    async def inspect(self, sid):
        return await self.request(
            "GET", "/containers/gamedock-" + sid + "/json", missing=True
        )

    async def ensure_connection(self, sid):
        async with self.connection_lock:
            network = "gamedock-session-" + sid
            info = await self.request("GET", "/networks/" + network)
            if not any(
                cid.startswith(self.portal) for cid in info.get("Containers", {})
            ):
                await self.request(
                    "POST",
                    "/networks/" + network + "/connect",
                    {"Container": self.portal},
                )

    async def stop(self, sid):
        await self.request(
            "DELETE", "/containers/gamedock-" + sid + "?force=true", missing=True
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
        token = request.cookies.get("gamedock", "")
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
    return json.loads(
        app["db"].execute("SELECT value FROM settings WHERE id=1").fetchone()[0]
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
        ]
    return web.json_response(
        {
            "settings": cfg,
            "user": public_user(request["user"]) if request["user"] else None,
            "games": games,
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
        hashed = await asyncio.to_thread(password_hash, password)
        try:
            app["db"].execute(
                "INSERT INTO users(username,password) VALUES (?,?)", (username, hashed)
            )
        except sqlite3.IntegrityError:
            raise web.HTTPConflict(text="That username already exists")
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
        "gamedock",
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
    response.del_cookie("gamedock", path="/")
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
        if count >= cfg["max_instances"] or own >= cfg["per_user"]:
            raise web.HTTPConflict(text="The instance limit has been reached")
        row = (
            app["db"]
            .execute("SELECT definition FROM games WHERE id=?", (body.get("game"),))
            .fetchone()
        )
        if not row:
            raise ValueError("Game not found")
        profile = json.loads(row[0])
        resolution = body.get("resolution", profile["resolutions"][0])
        if resolution not in profile["resolutions"]:
            raise ValueError("Resolution not allowed")
        sid = secrets.token_hex(16)
        app["db"].execute(
            "INSERT INTO instances VALUES (?,?,?,?,?,?)",
            (sid, u["id"], profile["id"], resolution, "starting", time.time()),
        )
        try:
            await app["docker"].start(sid, u["id"], profile, resolution)
        except Exception:
            app["db"].execute("UPDATE instances SET status='failed' WHERE id=?", (sid,))
            raise
        app["db"].execute("UPDATE instances SET status='running' WHERE id=?", (sid,))
    return web.json_response(
        {"id": sid, "url": "/desktop/" + sid + "/", "status": "running"}, status=201
    )


async def terminate(request):
    instance = owned(request)
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
    if "registration" in body:
        if not isinstance(body["registration"], bool):
            raise ValueError("Invalid registration setting")
        cfg["registration"] = body["registration"]
    for field in ("max_instances", "per_user"):
        if field in body:
            if type(body[field]) is not int or not 1 <= body[field] <= 100:
                raise ValueError("Invalid limit")
            cfg[field] = body[field]
    request.app["db"].execute(
        "UPDATE settings SET value=? WHERE id=1", (json.dumps(cfg),)
    )
    return web.json_response(cfg)


async def admin_games(request):
    user(request, True)
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
                public_user(r)
                for r in request.app["db"].execute("SELECT * FROM users ORDER BY id")
            ]
        )
    uid = int(request.match_info["uid"])
    if uid == current["id"]:
        raise ValueError("You cannot disable your own account")
    body = await request.json()
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
    if instance["status"] != "running":
        raise web.HTTPConflict(text="Instance stopped")
    if (
        request.match_info.get("tail", "") in ("", "index.html")
        and "floating_menu" not in request.query
        and request.headers.get("Upgrade", "").lower() != "websocket"
    ):
        return web.HTTPFound(
            location=str(
                request.rel_url.update_query(
                    floating_menu="true" if DESKTOP_TOOLBAR else "false"
                )
            )
        )
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

    tail = request.match_info.get("tail", "")
    target = URL.build(
        scheme="http",
        host=network["IPAddress"],
        port=6084,
        path="/" + tail,
        query_string=request.query_string,
    )
    http = request.app["http"]
    if request.headers.get("Upgrade", "").lower() == "websocket":
        protocols = [
            p.strip()
            for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
            if p.strip()
        ]
        async with http.ws_connect(
            target, protocols=protocols, max_msg_size=16 * 1024**2
        ) as upstream:
            downstream = web.WebSocketResponse(
                protocols=protocols, max_msg_size=16 * 1024**2
            )
            await downstream.prepare(request)

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
        async with http.get(target, allow_redirects=False) as upstream:
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
    yield
    await app["http"].close()
    await app["docker"].http.close()
    app["db"].close()


def create_app(db_path=None, docker=None):
    import logging

    app = web.Application(middlewares=[security], client_max_size=64 * 1024)
    app["logger"] = logging.getLogger("gamedock")
    app["origin"] = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")
    path = db_path or os.getenv("DATABASE", "/data/gamedock.sqlite")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS tokens(digest TEXT PRIMARY KEY,uid INTEGER NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,definition TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS instances(id TEXT PRIMARY KEY,uid INTEGER NOT NULL,game TEXT NOT NULL,resolution TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);""")
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
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/catalog", catalog)
    app.router.add_post("/api/auth/{action:login|register}", auth)
    app.router.add_post("/api/logout", logout)
    app.router.add_get("/api/instances", instances)
    app.router.add_post("/api/instances", instances)
    app.router.add_delete("/api/instances/{sid}", terminate)
    app.router.add_put("/api/admin/settings", admin_settings)
    app.router.add_put("/api/admin/games", admin_games)
    app.router.add_delete("/api/admin/games/{game}", admin_games)
    app.router.add_get("/api/admin/users", admin_users)
    app.router.add_patch("/api/admin/users/{uid}", admin_users)
    app.router.add_get("/desktop/{sid}/{tail:.*}", proxy)
    app.router.add_get("/", lambda _: web.FileResponse(ROOT / "web/index.html"))
    app.router.add_static("/assets/", ROOT / "web")
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
