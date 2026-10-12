"""Viewer transitions, proxy leases, heartbeat, authorization and stop races."""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer
import tests.test_api as api_tests
from server.app import expire_viewers
from server.viewers import Presence, DesktopStopped


class ViewerPolicy(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = api_tests.API.asyncSetUp
    asyncTearDown = api_tests.API.asyncTearDown
    login = api_tests.API.login

    async def setup_instance(self, action="stop"):
        self.headers = await self.login("admin", "login")
        response = await self.client.put(
            "/api/admin/settings",
            headers=self.headers,
            json={
                "idle_minutes": 0,
                "viewer_action": action,
                "viewer_disconnect_seconds": 60,
                "viewer_first_connect_seconds": 180,
            },
        )
        self.assertEqual(response.status, 200)
        response = await self.client.post(
            "/api/instances", headers=self.headers, json={"game": "desktop"}
        )
        self.sid = (await response.json())["id"]
        self.presence = self.app["viewers"][self.sid]
        self.zero = AsyncMock(return_value={"viewers": 0, "ever_seen": False})
        self.stop = AsyncMock(wraps=self.docker.stop)
        self.docker.stop = self.stop

    def attach(self):
        token = object()
        self.presence.connect(token)
        self.presence.ever_seen = True
        return token

    async def sweep(self, now):
        with patch("server.app.query_viewers", self.zero):
            await expire_viewers(self.app, now)

    async def test_legacy_default_is_disabled_and_invalid_settings_rejected(self):
        from server.app import config

        self.assertEqual(config(self.app)["viewer_action"], "disabled")
        admin = await self.login("admin", "login")
        for body in (
            {"viewer_action": "pause"},
            {"viewer_disconnect_seconds": True},
            {"viewer_first_connect_seconds": 0},
        ):
            response = await self.client.put(
                "/api/admin/settings", headers=admin, json=body
            )
            self.assertEqual(response.status, 400)

    async def test_connected_without_input_never_expires(self):
        await self.setup_instance()
        self.attach()
        self.app["db"].execute("UPDATE instances SET last_activity=0")
        await self.sweep(time.time() + 10000)
        self.stop.assert_not_awaited()
        self.zero.assert_not_awaited()

    async def test_last_disconnect_grace_stop_is_idempotent_and_frees_slot(self):
        await self.setup_instance()
        token = self.attach()
        now = time.time()
        self.presence.disconnect(token, now)
        await self.sweep(now + 59.9)
        self.stop.assert_not_awaited()
        await self.sweep(now + 60)
        await self.sweep(now + 100)
        self.stop.assert_awaited_once_with(self.sid)
        self.assertEqual(
            self.app["db"]
            .execute("SELECT status FROM instances WHERE id=?", (self.sid,))
            .fetchone()[0],
            "stopped",
        )
        response = await self.client.post(
            "/api/instances", headers=self.headers, json={"game": "desktop"}
        )
        self.assertEqual(response.status, 201)

    async def test_two_viewers_and_reconnection_cancel_stop(self):
        await self.setup_instance()
        one, two = self.attach(), self.attach()
        now = time.time()
        self.presence.disconnect(one, now)
        await self.sweep(now + 100)
        self.assertEqual(len(self.presence.leases), 1)
        self.presence.disconnect(two, now + 100)
        await self.sweep(now + 159)
        self.attach()
        await self.sweep(now + 1000)
        self.stop.assert_not_awaited()

    async def test_new_instance_gets_separate_first_viewer_grace(self):
        await self.setup_instance()
        start = self.presence.since
        await self.sweep(start + 179.9)
        self.stop.assert_not_awaited()
        await self.sweep(start + 180)
        self.stop.assert_awaited_once()

    async def test_disabled_policy_preserves_previous_behavior(self):
        await self.setup_instance("disabled")
        self.presence.disconnect(self.attach(), time.time())
        await self.sweep(time.time() + 10000)
        self.stop.assert_not_awaited()

    async def test_restart_reconciles_connected_and_grants_fresh_grace(self):
        await self.setup_instance()
        self.app["viewers"].clear()  # Exactly the in-memory state after portal restart.
        now = time.time()
        self.zero.return_value = {"viewers": 2, "ever_seen": True}
        await self.sweep(now)
        state = self.app["viewers"][self.sid]
        self.assertEqual(state.observed, 2)
        self.stop.assert_not_awaited()
        self.zero.return_value = {"viewers": 0, "ever_seen": True}
        await self.sweep(now + 100)
        self.stop.assert_not_awaited()
        await self.sweep(now + 159.9)
        self.stop.assert_not_awaited()
        await self.sweep(now + 160)
        self.stop.assert_awaited_once()

    async def test_unavailable_or_invalid_presence_never_stops(self):
        await self.setup_instance()
        now = time.time()
        self.presence.disconnect(self.attach(), now)
        self.zero.side_effect = TimeoutError()
        await self.sweep(now + 100)
        self.assertFalse(self.presence.known)
        self.stop.assert_not_awaited()
        self.zero.side_effect = None
        self.zero.return_value = {"viewers": -1, "ever_seen": True}
        await self.sweep(now + 101)
        self.stop.assert_not_awaited()
        self.zero.return_value = {"viewers": 1, "ever_seen": True}
        await self.sweep(now + 102)
        self.assertTrue(self.presence.known)
        self.stop.assert_not_awaited()

    async def test_simultaneous_sweeps_stop_only_once(self):
        await self.setup_instance()
        self.presence.disconnect(self.attach(), time.time() - 100)
        with patch("server.app.query_viewers", self.zero):
            await asyncio.gather(expire_viewers(self.app), expire_viewers(self.app))
        self.stop.assert_awaited_once()

    async def test_partial_stop_retries_guard_cleanup_and_updates_state(self):
        await self.setup_instance()
        self.presence.disconnect(self.attach(), time.time() - 100)

        async def partial_stop(sid):
            self.docker.active.pop(sid, None)
            raise RuntimeError("Temporary network cleanup failure")

        self.stop.side_effect = partial_stop
        await self.sweep(time.time())
        self.stop.side_effect = None
        self.zero.side_effect = DesktopStopped()
        await self.sweep(time.time())
        self.assertEqual(self.stop.await_count, 2)
        self.assertEqual(
            self.app["db"]
            .execute("SELECT status FROM instances WHERE id=?", (self.sid,))
            .fetchone()[0],
            "stopped",
        )

    async def test_connection_during_runtime_query_cancels_stale_expiry(self):
        await self.setup_instance()
        self.presence.disconnect(self.attach(), time.time() - 100)
        sampling, release = asyncio.Event(), asyncio.Event()

        async def delayed_query(app, sid):
            sampling.set()
            await release.wait()
            return {"viewers": 0, "ever_seen": True}

        with patch("server.app.query_viewers", delayed_query):
            cleanup = asyncio.create_task(expire_viewers(self.app))
            await sampling.wait()
            # The query must not hold the registration lock.
            async with self.app["launch_lock"]:
                self.attach()
            release.set()
            await cleanup
        self.stop.assert_not_awaited()

    async def test_revoked_socket_releases_lease(self):
        await self.setup_instance()
        ws = await self.open_proxy()
        self.app["db"].execute("DELETE FROM tokens")
        for _ in range(40):
            if not self.presence.leases:
                break
            await asyncio.sleep(0.1)
        self.assertFalse(self.presence.leases)
        await ws.close()

    async def open_proxy(self, autoping=True):
        async def upstream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for message in ws:
                if message.type == web.WSMsgType.TEXT:
                    await ws.send_str(message.data)
            return ws

        upstream_app = web.Application()
        upstream_app.router.add_get("/", upstream)
        self.upstream = TestServer(upstream_app)
        await self.upstream.start_server()
        self.addAsyncCleanup(self.upstream.close)
        self.docker.active[self.sid]["NetworkSettings"] = {
            "Networks": {"gamedock-session-" + self.sid: {"IPAddress": "127.0.0.1"}}
        }
        self.docker.ensure_connection = AsyncMock()
        original = self.app["http"].ws_connect
        self.app["http"].ws_connect = lambda url, **kwargs: original(
            url.with_port(self.upstream.port), **kwargs
        )
        ws = await self.client.ws_connect(
            "/desktop/" + self.sid + "/", headers=self.headers, autoping=autoping
        )
        self.addAsyncCleanup(ws.close)
        return ws

    async def test_real_proxy_tracks_only_websockets_and_releases_finally(self):
        await self.setup_instance()
        response = await self.client.post(
            "/api/instances/" + self.sid + "/activity", headers=self.headers, json={}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.presence.leases), 0)
        ws = await self.open_proxy()
        await ws.send_str("test")
        self.assertEqual((await ws.receive()).data, "test")
        self.assertEqual(len(self.presence.leases), 1)
        await ws.close()
        for _ in range(100):
            if not self.presence.leases:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(self.presence.leases)
        self.assertIsNotNone(self.presence.since)

    async def test_dead_socket_heartbeat_without_browser_exit_events(self):
        await self.setup_instance()
        ws = await self.open_proxy(autoping=False)
        # Do not read or answer PING. The server detects the dead peer itself.
        for _ in range(190):
            if not self.presence.leases:
                break
            await asyncio.sleep(0.1)
        self.assertFalse(self.presence.leases)

    async def test_incoming_handshake_reservation_wins_over_expiry(self):
        await self.setup_instance()
        self.presence.disconnect(self.attach(), time.time() - 100)
        entered, release = asyncio.Event(), asyncio.Event()

        async def pending(request):
            entered.set()
            await release.wait()
            raise web.HTTPServiceUnavailable()

        with patch("server.app.desktop_proxy", pending):
            attempt = asyncio.create_task(
                self.client.get(
                    "/desktop/" + self.sid + "/",
                    headers={**self.headers, "Upgrade": "websocket"},
                )
            )
            await entered.wait()
            await self.sweep(time.time())
            self.stop.assert_not_awaited()
            release.set()
            self.assertEqual((await attempt).status, 503)
        self.assertFalse(self.presence.leases)

    async def test_invalid_origin_and_unowned_instance_do_not_register(self):
        await self.setup_instance()
        for headers in (
            {**self.headers, "Origin": "https://evil.invalid"},
            await self.login("alice"),
        ):
            response = await self.client.get(
                "/desktop/" + self.sid + "/",
                headers={**headers, "Upgrade": "websocket"},
            )
            self.assertIn(response.status, (403, 404))
        self.assertFalse(self.presence.leases)
