"""Integration tests for the session gateway, independent of a real GPU."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from aiohttp import WSServerHandshakeError, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from selkies_gateway import application, Presence


class Gateway(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'index.html').write_text('<html><head></head><body>game</body></html>')
        backend = web.Application()
        async def stream(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            async for message in socket:
                if message.type == web.WSMsgType.TEXT:
                    await socket.send_str(message.data)
                elif message.type == web.WSMsgType.BINARY:
                    await socket.send_bytes(message.data)
            return socket
        backend.router.add_get('/api/websockets', stream)
        async def health(request):
            return web.json_response({'ok': True})
        backend.router.add_get('/api/health', health)
        self.backend = TestServer(backend, host='127.0.0.1', port=8082)
        await self.backend.start_server()
        self.app = application(self.root, self.root)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.backend.close()
        self.directory.cleanup()

    async def test_dashboard_hidden_before_paint_and_assets_confined(self):
        response = await self.client.get('/')
        html = await response.text()
        self.assertLess(html.index('.sidebar,.toggle-handle'), html.index('</head>'))
        self.assertIn('display:none!important', html)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response = await self.client.get('/%2e%2e/etc/passwd')
        self.assertEqual(response.status, 404)

    async def test_only_streaming_websocket_is_a_presence_lease(self):
        response = await self.client.get('/api/health')
        self.assertEqual(await response.json(), {'ok': True})
        self.assertEqual(len(self.app['presence'].leases), 0)
        socket = await self.client.ws_connect('/api/websockets')
        await socket.send_str('_stats,1')
        self.assertEqual((await socket.receive()).data, '_stats,1')
        await socket.send_bytes(b'video-data')
        self.assertEqual((await socket.receive()).data, b'video-data')
        self.assertEqual(len(self.app['presence'].leases), 1)
        sample = json.loads((self.root / 'viewers.json').read_text())
        self.assertEqual(sample['viewers'], 1)
        self.assertTrue(sample['ever_seen'])
        await socket.close()
        for _ in range(30):
            if not self.app['presence'].leases:
                break
            await asyncio.sleep(.01)
        self.assertEqual(len(self.app['presence'].leases), 0)
        self.assertTrue(self.app['presence'].ever_seen)

    async def test_ping_round_trip_reaches_backend(self):
        socket = await self.client.ws_connect('/api/websockets', autoping=False)
        await socket.ping(b'latency-probe')
        message = await socket.receive(timeout=2)
        self.assertEqual(message.type, WSMsgType.PONG)
        self.assertEqual(message.data, b'latency-probe')
        await socket.close()

    async def test_failed_websocket_does_not_count_and_metrics_are_explicit(self):
        with self.assertRaises(WSServerHandshakeError) as failure:
            await self.client.ws_connect('/api/missing')
        self.assertEqual(failure.exception.status, 502)
        self.assertEqual(len(self.app['presence'].leases), 0)
        response = await self.client.get('/api/gamedock/metrics')
        sample = await response.json()
        self.assertEqual(sample['backend'], 'selkies')
        self.assertIn('container_memory_mb', sample)
        self.assertNotIn('capture_fps', sample)


if __name__ == '__main__':
    unittest.main()
