"""Version-checked primary-display sharing adapter for Selkies 2.0.0.

The portal authenticates each socket and isolates each owner's container.
Only legacy primary controllers are joined; secure-mode sharing is untouched.
Native viewer fan-out handles video/audio/visibility and preserves input roles.
Fail the image build if upstream changes any patched contract.
"""
import ast
from pathlib import Path

HELPERS = r'''
def _gamedock_join_primary(server, websocket, display_id):
    if server.is_secure_mode or display_id != "primary":
        return False
    owner = (server.display_clients.get("primary") or {}).get("ws")
    return owner is not None and owner is not websocket and owner in server.clients


def _gamedock_promote_primary(server, departing):
    if server.is_secure_mode:
        return None
    entry = server.display_clients.get("primary")
    if not entry or entry.get("ws") is not departing:
        return None
    successor = next((ws for ws in server.clients
                      if client_permissions.get(ws, {}).get("_gamedock_primary")
                      and client_permissions.get(ws, {}).get("role") == "controller"), None)
    if successor is None:
        return None
    entry["ws"] = successor
    entry["acknowledged_frame_id"] = -1
    entry["unacked_since"] = None
    entry["stall_gated_at"] = None
    entry["last_ack_update_time"] = time.monotonic()
    entry.get("sent_timestamps", {}).clear()
    return successor

'''


def patch_source(source):
    if "def _gamedock_join_primary(" in source:
        raise ValueError("Selkies sharing adapter is already installed")
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("Unsupported Selkies source contract: " + old[:100])
        source = source.replace(old, new)

    replace("class DataStreamingServer(BaseStreamingService):", HELPERS + "\nclass DataStreamingServer(BaseStreamingService):")
    replace('''                    message = msg.data
                    if message == "_gz,1":''', '''                    message = msg.data
                    # A shared controller promoted after the owner left now ACKs
                    # and controls the existing primary entry, without reconnect.
                    primary = self.display_clients.get("primary") or {}
                    if (client_permissions.get(websocket, {}).get("_gamedock_primary")
                            and primary.get("ws") is websocket):
                        client_display_id = "primary"
                    if message == "_gz,1":''')
    replace('''                            if client_role == 'viewer':
                                data_logger.info''', '''                            shared_controller = (client_role == "controller" and
                                                 _gamedock_join_primary(self, websocket, display_id))
                            if shared_controller:
                                client_perms["_gamedock_primary"] = True
                                client_display_id = None
                            if client_role == 'viewer' or shared_controller:
                                data_logger.info''')
    replace('''                                self._schedule_idr_for_display('primary')

                                continue

                            if display_id != 'primary':''', '''                                self._schedule_idr_for_display('primary')
                                watch = self._stream_watches.get("primary")
                                if shared_controller and watch and watch.info:
                                    await self._send_stream_message(websocket, {
                                        "type": "stream_info", "displayId": "primary", "info": watch.info})

                                continue

                            if display_id != 'primary':''')
    replace('''            self.clients.discard(websocket)
            data_logger.debug(f"Cleaning up Data WS handler''', '''            self.clients.discard(websocket)
            if _gamedock_promote_primary(self, websocket) is not None:
                self._schedule_idr_for_display("primary")
            data_logger.debug(f"Cleaning up Data WS handler''')
    replace('''    def _watch_stream(self, display_id: str, module: Any) -> None:''', '''        if display_id == "primary":
            owner = (self.display_clients.get("primary") or {}).get("ws")
            for client in self.clients:
                if client is not owner and client_permissions.get(client, {}).get("_gamedock_primary"):
                    await self._send_stream_message(client, {
                        "type": "stream_info", "displayId": display_id, "info": info})

    def _watch_stream(self, display_id: str, module: Any) -> None:''')
    replace('''    async def _stop_primary_if_unconsumed(self, reason: str) -> None:''', '''        # Sharing tabs subscribe independently; host/encode figures are common.
        # Do not report the owner's RTT as the joining tab's own RTT.
        owner = (self.display_clients.get("primary") or {}).get("ws")
        for ws in self._stats_subscribers & self.clients:
            if ws is owner or not client_permissions.get(ws, {}).get("_gamedock_primary"):
                continue
            stats = dict(host)
            watch = self._stream_watches.get("primary")
            if watch is not None:
                stats.update(watch.rates())
            asyncio.ensure_future(self._send_stream_message(ws, {
                "type": "stream_stats", "displayId": "primary", "stats": stats}))

    async def _stop_primary_if_unconsumed(self, reason: str) -> None:''')
    ast.parse(source)
    return source


if __name__ == "__main__":
    import selkies
    target = Path(selkies.__file__).parent / "websockets_mode.py"
    target.write_text(patch_source(target.read_text()))
