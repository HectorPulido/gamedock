"""Cheap runtime publisher counts UI sources without querying Xpra info."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from runtime.gamedock_presence import instrument
from server.viewers import Presence


class RuntimePresence(unittest.TestCase):
    def test_new_proxy_replaces_stale_restart_observation(self):
        state = Presence(known=True, observed=2, ever_seen=True)
        state.connect(object())
        self.assertEqual(state.observed, 0)
        self.assertEqual(len(state.leases), 1)

    def test_publish_counts_only_open_window_sources_and_remembers_viewers(self):
        callbacks = []
        glib = SimpleNamespace(
            timeout_add=lambda interval, fn: callbacks.append((interval, fn))
        )

        class Server:
            def init(self, opts):
                self._server_sources = {}

        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"XDG_RUNTIME_DIR": root}
        ), patch.dict("sys.modules", {"gi.repository": SimpleNamespace(GLib=glib)}):
            instrument(Server)
            server = Server()
            server.init(None)
            path = Path(root) / "viewers.json"
            self.assertEqual(json.loads(path.read_text())["viewers"], 0)
            self.assertFalse(json.loads(path.read_text())["ever_seen"])
            self.assertEqual(callbacks[0][0], 1000)
            server._server_sources = {
                "viewer": SimpleNamespace(window_enabled=True, is_closed=lambda: False),
                "closed": SimpleNamespace(window_enabled=True, is_closed=lambda: True),
                "metrics": SimpleNamespace(
                    window_enabled=False, is_closed=lambda: False
                ),
            }
            self.assertTrue(callbacks[0][1]())
            self.assertEqual(json.loads(path.read_text())["viewers"], 1)
            server._server_sources.clear()
            callbacks[0][1]()
            data = json.loads(path.read_text())
            self.assertEqual(data["viewers"], 0)
            self.assertTrue(data["ever_seen"])
            self.assertGreater(data["updated"], 0)
