import os
import json
import asyncio
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp.test_utils import TestClient, TestServer
from server.app import create_app, validate_profile, expire_idle, Docker


class FakeDocker:
    def __init__(self):
        self.active = {}
        self.profiles = {}

    async def start(self, sid, uid, profile, resolution):
        self.active[sid] = {"State": {"Running": True}}
        self.profiles[sid] = dict(profile)

    async def inspect(self, sid):
        return self.active.get(sid)

    async def stop(self, sid):
        self.active.pop(sid, None)


class API(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["ADMIN_PASSWORD"] = "test-admin-password"
        self.docker = FakeDocker()
        self.app = create_app(":memory:", self.docker)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def login(self, name="alice", action="register"):
        password = "test-admin-password" if name == "admin" else "test-password-123"
        body = {"username": name, "password": password}
        if action == "register":
            admin = await self.login("admin", "login")
            result = await self.client.post(
                "/api/admin/invitations", json={}, headers=admin
            )
            body["invite"] = (await result.json())["code"]
        result = await self.client.post("/api/auth/" + action, json=body)
        self.assertEqual(result.status, 200, await result.text())
        return {"Authorization": "Bearer " + (await result.json())["token"]}

    async def test_controller_session_authorization_and_payload_validation(self):
        admin = await self.login("admin", "login")
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "desktop"}
        )
        sid = (await response.json())["id"]
        path = f"/desktop/{sid}/gamedock-controller"
        alice = await self.login()
        response = await self.client.post(path, headers=alice, json={})
        self.assertIn(response.status, (403, 404))
        response = await self.client.post(
            path, headers={**admin, "Origin": "https://evil.example"}, json={}
        )
        self.assertEqual(response.status, 403)
        info = {
            "State": {"Running": True},
            "NetworkSettings": {
                "Networks": {"gamedock-session-" + sid: {"IPAddress": "127.0.0.1"}}
            },
        }
        with (
            patch.object(self.docker, "inspect", AsyncMock(return_value=info)),
            patch.object(self.docker, "ensure_connection", AsyncMock(), create=True),
        ):
            response = await self.client.post(
                path, headers=admin, json={"axes": [999, 0, 0, 0]}
            )
            self.assertEqual(response.status, 400)
            response = await self.client.post(path, headers=admin, data="{}")
            self.assertEqual(response.status, 415)

    async def test_streaming_permissions_inheritance_and_saved_defaults(self):
        admin = await self.login("admin", "login")
        alice = await self.login()
        response = await self.client.put(
            "/api/admin/settings", headers=alice, json={"streaming": {"quality": 95}}
        )
        self.assertEqual(response.status, 403)
        for invalid in (
            {"quality": 101},
            {"idle_fix": "yes"},
            {"batch_min_delay": 50},
            {"evil": 1},
        ):
            response = await self.client.put(
                "/api/admin/settings", headers=admin, json={"streaming": invalid}
            )
            self.assertEqual(response.status, 400)
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "desktop"}
        )
        first = (await response.json())["id"]
        response = await self.client.put(
            "/api/admin/settings",
            headers=admin,
            json={
                "streaming": {"quality": 95, "min_quality": 85, "idle_fix": False},
                "max_instances": 5,
                "per_user": 5,
            },
        )
        self.assertEqual(response.status, 200)
        cfg = (await response.json())["streaming"]
        self.assertEqual(cfg["batch_max_delay"], 40)
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "desktop"}
        )
        second = (await response.json())["id"]
        self.assertEqual(self.docker.profiles[first]["streaming"]["quality"], 0)
        self.assertEqual(self.docker.profiles[second]["streaming"]["quality"], 95)
        self.assertFalse(self.docker.profiles[second]["streaming"]["idle_fix"])
        profile = {
            "id": "custom",
            "name": "Custom",
            "image": "gamedock-runtime:local",
            "command": ["xterm"],
            "streaming": {
                "quality": 100,
                "min_quality": 100,
                "encoding": "png",
                "encodings": "png,rgb",
            },
        }
        response = await self.client.put(
            "/api/admin/games", headers=admin, json=profile
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "custom"}
        )
        third = (await response.json())["id"]
        settings = self.docker.profiles[third]["streaming"]
        self.assertEqual(settings["quality"], 100)
        self.assertEqual(settings["encoding"], "png")
        self.assertFalse(settings["idle_fix"])
        response = await self.client.get("/api/catalog", headers=admin)
        self.assertIn("batch_max_delay", (await response.json())["streaming_schema"])
        profile["env"] = {"GAMEDOCK_STREAMING": "{}"}
        with self.assertRaises(ValueError):
            validate_profile(profile)

    async def test_network_policy_permissions_and_launch_inheritance(self):
        admin = await self.login("admin", "login")
        alice = await self.login()
        profile = {
            "id": "nettest",
            "name": "Network test",
            "image": "runtime:local",
            "command": ["xterm"],
            "network_policy": {
                "mode": "allowlist",
                "allow": [{"cidr": "192.168.0.7/32", "port": 5555, "protocol": "tcp"}],
            },
        }
        response = await self.client.put(
            "/api/admin/games", headers=alice, json=profile
        )
        self.assertEqual(response.status, 403)
        response = await self.client.put(
            "/api/admin/games", headers=admin, json=profile
        )
        self.assertEqual(response.status, 200, await response.text())
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "nettest"}
        )
        self.assertEqual(response.status, 201, await response.text())
        policy = self.docker.profiles[(await response.json())["id"]]["network_policy"]
        self.assertEqual(policy["mode"], "allowlist")
        self.assertEqual(policy["allow"], profile["network_policy"]["allow"])
        profile["network_policy"]["allow"][0]["port"] = 0
        response = await self.client.put(
            "/api/admin/games", headers=admin, json=profile
        )
        self.assertEqual(response.status, 400)

    async def test_coherent_versioned_assets_and_cache_policy(self):
        response = await self.client.get("/")
        document = await response.text()
        version = response.headers["X-GameDock-Build"]
        self.assertEqual(len(version), 64)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("/assets/" + version + "/app.js", document)
        self.assertIn("/assets/" + version + "/style.css", document)
        current = await self.client.get("/assets/" + version + "/app.js")
        self.assertEqual(current.status, 200)
        self.assertIn("immutable", current.headers["Cache-Control"])
        self.assertEqual(current.headers["X-GameDock-Build"], version)
        legacy = await self.client.get("/assets/app.js")
        self.assertEqual(await legacy.read(), await current.read())
        self.assertEqual(legacy.headers["Cache-Control"], "no-store")
        stale = await self.client.get("/assets/" + "0" * 64 + "/app.js")
        self.assertEqual(stale.status, 410)
        self.assertEqual(stale.headers["Cache-Control"], "no-store")
        self.assertNotIn("const $", await stale.text())
        missing = await self.client.get("/assets/" + version + "/unknown.js")
        self.assertEqual(missing.status, 404)

    async def test_accounts_ownership_and_revocation(self):
        alice = await self.login()
        bob = await self.login("bob")
        instance = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        self.assertEqual(instance.status, 201)
        sid = (await instance.json())["id"]
        response = await self.client.delete(
            "/api/instances/" + sid, json={}, headers=bob
        )
        self.assertEqual(response.status, 404)
        response = await self.client.get("/desktop/" + sid + "/", headers=bob)
        self.assertEqual(response.status, 404)
        response = await self.client.get("/api/instances", headers=bob)
        self.assertEqual(await response.json(), [])
        response = await self.client.post("/api/logout", json={}, headers=alice)
        self.assertEqual(response.status, 200)
        self.client.session.cookie_jar.clear()
        response = await self.client.get("/api/instances", headers=alice)
        self.assertEqual(response.status, 401)

    async def test_legacy_toolbar_setting_does_not_redirect_selkies(self):
        alice = await self.login()
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        sid = (await response.json())["id"]
        # No runtime means 410. The obsolete toolbar query must not redirect
        # before we inspect the actual instance.
        self.docker.active.pop(sid)
        for enabled in (True, False):
            with patch("server.app.DESKTOP_TOOLBAR", enabled):
                response = await self.client.get(
                    "/desktop/" + sid + "/?autohide=true", headers=alice,
                    allow_redirects=False,
                )
            self.assertEqual(response.status, 410)
            self.assertNotIn("Location", response.headers)

    async def test_admin_settings_profiles_and_disabled_user(self):
        alice = await self.login()
        admin = await self.login("admin", "login")
        response = await self.client.put(
            "/api/admin/settings",
            json={
                "name": "TestDock",
                "registration": False,
                "per_user": 1,
                "banner_image": "https://example.com/banner.png",
            },
            headers=admin,
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/auth/register",
            json={"username": "charlie", "password": "test-password-123"},
        )
        self.assertEqual(response.status, 403)
        response = await self.client.put(
            "/api/admin/settings", json={"name": "hacked"}, headers=alice
        )
        self.assertEqual(response.status, 403)
        profile = {
            "id": "test",
            "name": "Test",
            "image": "test:local",
            "command": ["test", "argument with spaces"],
            "env": {"PRIVATE_KEY": "secret"},
            "resolutions": ["800x600"],
        }
        response = await self.client.put(
            "/api/admin/games", json=profile, headers=admin
        )
        self.assertEqual(response.status, 200)
        result = await self.client.get("/api/catalog", headers=alice)
        game = next(g for g in (await result.json())["games"] if g["id"] == "test")
        self.assertNotIn("env", game)
        response = await self.client.post(
            "/api/instances",
            json={"game": "test", "resolution": "1920x1080"},
            headers=alice,
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/instances",
            json={"game": "test", "resolution": "800x600"},
            headers=alice,
        )
        self.assertEqual(response.status, 201)
        response = await self.client.post(
            "/api/instances", json={"game": "test"}, headers=alice
        )
        self.assertEqual(response.status, 409)
        response = await self.client.patch(
            "/api/admin/users/2", json={"enabled": False}, headers=admin
        )
        self.assertEqual(response.status, 200)
        self.assertFalse(self.docker.active)
        self.client.session.cookie_jar.clear()
        response = await self.client.get("/api/instances", headers=alice)
        self.assertEqual(response.status, 401)

    async def test_invitation_lifecycle(self):
        admin = await self.login("admin", "login")
        body = {"username": "newplayer", "password": "test-password-123"}
        response = await self.client.post("/api/auth/register", json=body)
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/admin/invitations", json={"max_uses": 1}, headers=admin
        )
        invite = await response.json()
        response = await self.client.get("/api/admin/invitations", headers=admin)
        self.assertNotIn("code", (await response.json())[0])
        body["invite"] = invite["code"]
        response = await self.client.post("/api/auth/register", json=body)
        self.assertEqual(response.status, 200)
        body["username"] = "anotherplayer"
        response = await self.client.post("/api/auth/register", json=body)
        self.assertEqual(response.status, 403)
        for mode in ("revoked", "expired"):
            response = await self.client.post(
                "/api/admin/invitations", json={}, headers=admin
            )
            invite = await response.json()
            if mode == "revoked":
                await self.client.delete(
                    "/api/admin/invitations/" + invite["id"], json={}, headers=admin
                )
            else:
                self.app["db"].execute(
                    "UPDATE invitations SET expires=0 WHERE id=?", (invite["id"],)
                )
            body["invite"] = invite["code"]
            response = await self.client.post("/api/auth/register", json=body)
            self.assertEqual(response.status, 403)

    async def test_invitation_concurrent_redemption(self):
        admin = await self.login("admin", "login")
        response = await self.client.post(
            "/api/admin/invitations", json={}, headers=admin
        )
        code = (await response.json())["code"]
        responses = await asyncio.gather(
            *[
                self.client.post(
                    "/api/auth/register",
                    json={
                        "username": name,
                        "password": "test-password-123",
                        "invite": code,
                    },
                )
                for name in ("playerone", "playertwo")
            ]
        )
        self.assertEqual(sorted(response.status for response in responses), [200, 403])
        response = await self.client.get("/api/admin/invitations", headers=admin)
        self.assertEqual((await response.json())[0]["uses"], 1)

    async def test_account_game_and_resolution_policy(self):
        alice = await self.login()
        admin = await self.login("admin", "login")
        response = await self.client.get("/api/catalog", headers=alice)
        uid = (await response.json())["user"]["id"]
        response = await self.client.patch(
            "/api/admin/users/" + str(uid),
            json={"policy": {"max_instances": 2, "games": {"desktop": 0}}},
            headers=admin,
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/catalog", headers=alice)
        self.assertEqual((await response.json())["games"], [])
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        self.assertEqual(response.status, 403)
        await self.client.patch(
            "/api/admin/users/" + str(uid),
            json={"policy": {"max_instances": 2, "games": {"desktop": 1}}},
            headers=admin,
        )
        response = await self.client.post(
            "/api/instances",
            json={"game": "desktop", "resolution": "1920x1080"},
            headers=alice,
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        self.assertEqual(response.status, 201)
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        self.assertEqual(response.status, 409)
        response = await self.client.patch(
            "/api/admin/users/" + str(uid),
            json={"policy": {"games": None}},
            headers=alice,
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/instances",
            json={"game": "desktop", "resolution": "1920x1080"},
            headers=admin,
        )
        self.assertEqual(response.status, 201)

    async def test_activity_and_inactivity_cleanup(self):
        alice = await self.login()
        bob = await self.login("bob")
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        sid = (await response.json())["id"]
        self.app["db"].execute(
            "UPDATE instances SET last_activity=0 WHERE id=?", (sid,)
        )
        response = await self.client.post(
            "/api/instances/" + sid + "/activity", json={}, headers=bob
        )
        self.assertEqual(response.status, 404)
        response = await self.client.post(
            "/api/instances/" + sid + "/activity", json={}, headers=alice
        )
        self.assertEqual(response.status, 200)
        await expire_idle(self.app)
        self.assertIn(sid, self.docker.active)
        self.app["db"].execute(
            "UPDATE instances SET last_activity=0 WHERE id=?", (sid,)
        )
        await expire_idle(self.app)
        self.assertNotIn(sid, self.docker.active)
        response = await self.client.get("/api/instances/" + sid, headers=alice)
        self.assertEqual((await response.json())["status"], "stopped")

    async def test_toolbar_admin_setting(self):
        alice = await self.login()
        admin = await self.login("admin", "login")
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        sid = (await response.json())["id"]
        await self.client.put(
            "/api/admin/settings",
            json={"desktop_toolbar": False, "idle_minutes": 0},
            headers=admin,
        )
        self.docker.active.pop(sid)
        response = await self.client.get(
            "/desktop/" + sid + "/?floating_menu=true",
            headers=alice,
            allow_redirects=False,
        )
        self.assertEqual(response.status, 410)
        self.assertNotIn("Location", response.headers)
        response = await self.client.get("/play/" + sid, headers=alice)
        self.assertEqual(response.status, 200)
        self.assertIn("Back to library", await response.text())

    async def test_legacy_database_activity_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.sqlite")
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE instances(id TEXT PRIMARY KEY,uid INTEGER NOT NULL,game TEXT NOT NULL,resolution TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL)"
            )
            sid = "a" * 32
            db.execute(
                "INSERT INTO instances VALUES (?,?,?,?,?,?)",
                (sid, 1, "desktop", "1280x720", "running", 123),
            )
            db.commit()
            db.close()
            migrated = create_app(path, FakeDocker())
            row = (
                migrated["db"]
                .execute("SELECT * FROM instances WHERE id=?", (sid,))
                .fetchone()
            )
            self.assertEqual(row["created"], 123)
            self.assertGreater(row["last_activity"], 123)
            migrated["db"].close()

    async def test_open_registration_switch(self):
        admin = await self.login("admin", "login")
        await self.client.put(
            "/api/admin/settings", json={"invite_required": False}, headers=admin
        )
        response = await self.client.post(
            "/api/auth/register",
            json={"username": "openplayer", "password": "test-password-123"},
        )
        self.assertEqual(response.status, 200)

    async def test_input_and_origin(self):
        admin = await self.login("admin", "login")
        response = await self.client.put(
            "/api/admin/settings",
            json={"name": "x"},
            headers={**admin, "Origin": "https://evil.example"},
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post("/api/instances", json=[], headers=admin)
        self.assertEqual(response.status, 400)
        response = await self.client.post("/api/instances", data="{}", headers=admin)
        self.assertEqual(response.status, 415)
        for bad in (
            ["shell string"],
            {"id": "../x"},
            {
                "id": "x",
                "name": "x",
                "image": "x",
                "command": ["x"],
                "resolutions": ["9999x9999"],
            },
        ):
            with self.assertRaises(ValueError):
                validate_profile(bad)

    async def test_resource_defaults_overrides_and_permissions(self):
        alice = await self.login()
        admin = await self.login("admin", "login")
        response = await self.client.put(
            "/api/admin/settings", headers=alice, json={"memory_mb": 512, "cpus": 0.5}
        )
        self.assertEqual(response.status, 403)
        response = await self.client.post(
            "/api/instances", headers=alice, json={"game": "desktop", "cpus": 200}
        )
        first = (await response.json())["id"]
        self.assertEqual(self.docker.profiles[first]["memory_mb"], 4096)
        self.assertEqual(self.docker.profiles[first]["cpus"], 2)
        await self.client.delete("/api/instances/" + first, headers=alice, json={})
        response = await self.client.put(
            "/api/admin/settings", headers=admin, json={"memory_mb": 768, "cpus": 0.5}
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/instances", headers=alice, json={"game": "desktop"}
        )
        second = (await response.json())["id"]
        self.assertEqual(self.docker.profiles[second]["memory_mb"], 768)
        self.assertEqual(self.docker.profiles[second]["cpus"], 0.5)
        games = (await (await self.client.get("/api/catalog", headers=admin)).json())[
            "games"
        ]
        profile = games[0]
        profile.update(memory_mb=1024, cpus=1.25)
        response = await self.client.put(
            "/api/admin/games", headers=admin, json=profile
        )
        self.assertEqual(response.status, 200)
        await self.client.delete("/api/instances/" + second, headers=alice, json={})
        response = await self.client.post(
            "/api/instances", headers=alice, json={"game": "desktop"}
        )
        third = (await response.json())["id"]
        self.assertEqual(self.docker.profiles[third]["memory_mb"], 1024)
        self.assertEqual(self.docker.profiles[third]["cpus"], 1.25)
        # Existing sessions keep their original limits.
        self.assertEqual(self.docker.profiles[first]["memory_mb"], 4096)
        for values in (
            {"cpus": 0},
            {"cpus": True},
            {"cpus": None},
            {"cpus": 257},
            {"memory_mb": 127},
            {"memory_mb": 512.5},
            {"memory_mb": "1024"},
            {"memory_mb": 1048577},
        ):
            response = await self.client.put(
                "/api/admin/settings", headers=admin, json=values
            )
            self.assertEqual(response.status, 400, values)
            if list(values.values()) != [None]:
                with self.assertRaises(ValueError):
                    validate_profile({**profile, **values})
        profile.update(memory_mb=None, cpus=None)
        self.assertIsNone(validate_profile(profile)["memory_mb"])

    async def test_profile_process_thread_quota_validation(self):
        admin = await self.login("admin", "login")
        catalog = await (await self.client.get("/api/catalog", headers=admin)).json()
        profile = catalog["games"][0]
        self.assertEqual(validate_profile(profile)["pids_limit"], 256)
        for invalid in (True, False, None, 63, 16385, 1024.0, "1024"):
            response = await self.client.put("/api/admin/games", headers=admin,
                json={**profile, "pids_limit": invalid})
            self.assertEqual(response.status, 400, invalid)
        for valid in (64, 1024, 16384):
            response = await self.client.put("/api/admin/games", headers=admin,
                json={**profile, "pids_limit": valid})
            self.assertEqual(response.status, 200)
            stored = await (await self.client.get("/api/catalog", headers=admin)).json()
            self.assertEqual(next(game for game in stored["games"]
                if game["id"] == profile["id"])["pids_limit"], valid)

    async def test_docker_resource_payload(self):
        docker = Docker()

        async def response(method, path, *args, **kwargs):
            if path.endswith("/json"):
                return {"State": {"Running": True, "Health": {"Status": "healthy"}}}
            return {}

        docker.request = AsyncMock(side_effect=response)
        await docker.start(
            "test",
            2,
            {
                "id": "desktop",
                "image": "runtime:local",
                "command": ["xterm"],
                "env": {},
                "memory_mb": 1536,
                "cpus": 0.75,
                "streaming": {
                    "canvas_filter": "fsr",
                    "viewer_scale": "fit",
                    "restore_focus": False,
                    "quality": 80,
                    "diagnostics_enabled": False,
                },
            },
            "1280x720",
        )
        call = next(
            c
            for c in docker.request.call_args_list
            if "/containers/create?name=gamedock-test" == c.args[1]
        )
        host = call.args[2]["HostConfig"]
        streaming = json.loads(
            next(
                value.split("=", 1)[1]
                for value in call.args[2]["Env"]
                if value.startswith("GAMEDOCK_STREAMING=")
            )
        )
        self.assertEqual(streaming, {"quality": 80, "diagnostics_enabled": False})
        self.assertEqual(host["PidsLimit"], 256)
        self.assertEqual(host["Memory"], 1536 * 1024**2)
        self.assertEqual(host["NanoCpus"], 750000000)
        self.assertEqual(host["CapDrop"], ["ALL"])
        self.assertNotIn("PortBindings", host)
        self.assertEqual(host["NetworkMode"], "container:gamedock-gateway-test")
        self.assertNotIn("NET_ADMIN", host.get("CapAdd", []))
        guard = next(
            c.args[2]
            for c in docker.request.call_args_list
            if c.args[1] == "/containers/create?name=gamedock-gateway-test"
        )
        self.assertEqual(guard["HostConfig"]["CapAdd"], ["NET_ADMIN"])
        self.assertTrue(guard["HostConfig"]["ReadonlyRootfs"])
        self.assertNotIn("Mounts", guard["HostConfig"])
        await docker.start("quota", 2, {
            "id": "desktop", "image": "runtime:local", "command": ["xterm"],
            "env": {}, "memory_mb": 1536, "cpus": .75, "pids_limit": 1024,
        }, "1280x720")
        configured = next(c.args[2]["HostConfig"] for c in docker.request.call_args_list
            if c.args[1] == "/containers/create?name=gamedock-quota")
        self.assertEqual(configured["PidsLimit"], 1024)

    async def test_brand_appearance_validation_and_public_pages(self):
        admin = await self.login("admin", "login")
        appearance = {
            "theme": "forest",
            "font": "system",
            "radius": 12,
            "content_width": 1300,
            "colors": {"accent": "#285634"},
            "logo_url": "https://example.com/logo.png",
            "footer": "Welcome",
            "custom_css": ".intro { padding-top: 20px; }",
        }
        response = await self.client.put(
            "/api/admin/settings",
            headers=admin,
            json={"name": "miservidor <test>", "appearance": appearance},
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get("/")
        page = await response.text()
        self.assertIn("<title>miservidor &lt;test&gt;</title>", page)
        self.assertNotIn("GameDock", page)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        catalog = await (await self.client.get("/api/catalog")).json()
        self.assertEqual(catalog["settings"]["appearance"], appearance)
        response = await self.client.post(
            "/api/instances", headers=admin, json={"game": "desktop"}
        )
        sid = (await response.json())["id"]
        page = await (await self.client.get("/play/" + sid, headers=admin)).text()
        self.assertIn("miservidor &lt;test&gt;", page)
        self.assertNotIn("GameDock", page)
        for invalid in (
            [],
            {"theme": "unknown"},
            {"font": "script"},
            {"radius": -1},
            {"content_width": 100},
            {"colors": {"accent": "red; display:none"}},
            {"colors": {"unknown": "#ffffff"}},
            {"logo_url": "javascript:alert(1)"},
            {"custom_css": "x" * 20001},
            {"unknown": True},
        ):
            response = await self.client.put(
                "/api/admin/settings", headers=admin, json={"appearance": invalid}
            )
            self.assertEqual(response.status, 400, invalid)
        catalog = await (await self.client.get("/api/catalog")).json()
        self.assertEqual(catalog["settings"]["appearance"], appearance)

    async def test_separate_admin_page_permissions(self):
        response = await self.client.get("/admin", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/")
        alice = await self.login()
        response = await self.client.get("/admin", headers=alice)
        self.assertEqual(response.status, 403)
        admin = await self.login("admin", "login")
        response = await self.client.get("/admin", headers=admin)
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn('id="admin-nav"', page)
        self.assertIn('id="settings"', page)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = await self.client.get("/", headers=admin)
        page = await response.text()
        for admin_control in (
            'id="settings"',
            'id="profile"',
            'id="admin"',
            'id="appearance"',
            'id="add-game"',
        ):
            self.assertNotIn(admin_control, page)

    async def test_reconcile_process_exit(self):
        alice = await self.login()
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        sid = (await response.json())["id"]
        self.docker.active.pop(sid)
        response = await self.client.get("/api/instances", headers=alice)
        self.assertEqual((await response.json())[0]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
