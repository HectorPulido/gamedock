import os
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from server.app import create_app, validate_profile


class FakeDocker:
    def __init__(self):
        self.active = {}

    async def start(self, sid, uid, profile, resolution):
        self.active[sid] = {"State": {"Running": True}}

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
        result = await self.client.post(
            "/api/auth/" + action, json={"username": name, "password": password}
        )
        self.assertEqual(result.status, 200, await result.text())
        return {"Authorization": "Bearer " + (await result.json())["token"]}

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

    async def test_desktop_toolbar_defaults(self):
        alice = await self.login()
        response = await self.client.post(
            "/api/instances", json={"game": "desktop"}, headers=alice
        )
        url = (await response.json())["url"]
        for enabled in (True, False):
            with patch("server.app.DESKTOP_TOOLBAR", enabled):
                response = await self.client.get(
                    url + "?autohide=true", headers=alice, allow_redirects=False
                )
            self.assertEqual(response.status, 302)
            self.assertIn(
                "floating_menu=" + str(enabled).lower(), response.headers["Location"]
            )
            self.assertIn("autohide=true", response.headers["Location"])

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
        self.assertEqual(response.status, 400)
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
