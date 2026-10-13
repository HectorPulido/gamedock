"""Session-local HTTP/WebSocket adapter; no host ports or privileged access.

The only presence leases are accepted streaming WebSockets. Diagnostics and
HTTP requests never keep an unattended game alive. The native dashboard is
hidden before its first paint; GameDock provides the player controls.
"""

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import time

from aiohttp import ClientError, ClientSession, WSMsgType, web
from gamedock_metrics import CaptureMetrics


HIDE_DASHBOARD = b"<style>.sidebar,.toggle-handle{display:none!important;pointer-events:none!important}</style>"


class Presence:
    def __init__(self, path):
        self.path = Path(path)
        self.leases = set()
        self.ever_seen = False

    def publish(self):
        self.ever_seen |= bool(self.leases)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({
            'updated': time.time(), 'viewers': len(self.leases),
            'ever_seen': self.ever_seen,
        }))
        temporary.replace(self.path)


async def lifecycle(app):
    app['client'] = ClientSession()
    async def heartbeat():
        while True:
            app['presence'].publish()
            await asyncio.sleep(1)
    task = asyncio.create_task(heartbeat())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await app['client'].close()


async def proxy(request):
    target = 'http://127.0.0.1:8082' + request.rel_url.raw_path_qs
    client = request.app['client']
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        # A successful backend handshake establishes a lease; failed handshakes
        # and ordinary requests do not. Stats travel on this same connection.
        protocols = tuple(p.strip() for p in request.headers.get('Sec-WebSocket-Protocol', '').split(',') if p.strip())
        try:
            backend = await client.ws_connect(target, protocols=protocols, max_msg_size=0,
                                              compress=0, autoping=False)
        except (ClientError, OSError):
            raise web.HTTPBadGateway(text='Desktop is not ready')
        async with backend:
            frontend = web.WebSocketResponse(protocols=protocols, max_msg_size=0, compress=False, autoping=False)
            await frontend.prepare(request)
            lease = object()
            presence = request.app['presence']
            streaming = request.path == '/api/websockets'
            if streaming:
                presence.leases.add(lease)
                presence.publish()
            async def relay(source, destination):
                async for message in source:
                    if message.type == WSMsgType.BINARY:
                        await destination.send_bytes(message.data)
                    elif message.type == WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type == WSMsgType.PING:
                        await destination.ping(message.data)
                    elif message.type == WSMsgType.PONG:
                        await destination.pong(message.data)
                await destination.close()
            tasks = [asyncio.create_task(relay(frontend, backend)),
                     asyncio.create_task(relay(backend, frontend))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await frontend.close()
                if streaming:
                    presence.leases.discard(lease)
                    presence.publish()
            return frontend
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in {'host', 'connection', 'transfer-encoding', 'content-length'}}
    async with client.request(request.method, target, headers=headers,
                              data=await request.read(), allow_redirects=False) as response:
        body = await response.read()
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in {'content-encoding', 'content-length', 'transfer-encoding', 'connection'}}
        return web.Response(status=response.status, body=body, headers=headers)


async def static(request):
    root = request.app['root']
    relative = request.match_info['path'] or 'index.html'
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise web.HTTPNotFound()
    if path.name == 'index.html':
        body = path.read_bytes().replace(b'</head>', HIDE_DASHBOARD + b'</head>', 1)
        return web.Response(body=body, content_type='text/html',
                            headers={'Cache-Control': 'no-store'})
    return web.FileResponse(path)


async def metrics(request):
    """Process/cgroup usage only; delivered FPS belongs to the browser decoder."""
    meter = request.app['metrics']
    if not meter.enabled:
        return web.json_response({'enabled': False, 'backend': 'selkies'},
                                 headers={'Cache-Control': 'no-store'})
    return web.json_response({
        'enabled': meter.enabled, 'backend': 'selkies',
        'target_hz': meter.settings.get('refresh_rate', 30),
        'gpu_vendor': meter.graphics.get('vendor', 'none'),
        'gpu_renderer': meter.graphics.get('renderer', ''),
        **meter.cpu(time.monotonic()),
    }, headers={'Cache-Control': 'no-store'})


def application(root='/usr/share/selkies/selkies-dashboard', runtime=None):
    runtime = runtime or os.environ.get('XDG_RUNTIME_DIR', '/tmp/gamedock-runtime')
    app = web.Application(client_max_size=64 * 1024)
    app['root'] = Path(root).resolve()
    app['presence'] = Presence(Path(runtime) / 'viewers.json')
    app['metrics'] = CaptureMetrics(json.loads(os.environ.get('GAMEDOCK_STREAMING', '{}')))
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/api/gamedock/metrics', metrics)
    app.router.add_route('*', '/api/{path:.*}', proxy)
    app.router.add_get('/{path:.*}', static)
    return app


if __name__ == '__main__':
    web.run_app(application(), host='0.0.0.0', port=6084, access_log=None)
