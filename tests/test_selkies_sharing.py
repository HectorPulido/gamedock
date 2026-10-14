"""Primary sharing stays within one portal-authorized owner container."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import time
import unittest

spec = importlib.util.spec_from_file_location("sharing_patch", Path(__file__).parents[1] / "runtime/patch-selkies-sessions.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

class Sharing(unittest.TestCase):
    def setUp(self):
        self.permissions = {}
        self.ns = {"client_permissions": self.permissions, "time": time}
        exec(patch.HELPERS, self.ns)
        self.owner, self.tab, self.third = object(), object(), object()
        self.server = SimpleNamespace(is_secure_mode=False,
            clients={self.owner, self.tab}, display_clients={"primary": {
                "ws": self.owner, "sent_timestamps": {7: 123}, "unacked_since": 12}})

    def test_join_never_replaces_existing_owner(self):
        self.assertTrue(self.ns["_gamedock_join_primary"](self.server, self.tab, "primary"))
        self.assertIs(self.server.display_clients["primary"]["ws"], self.owner)
        self.assertFalse(self.ns["_gamedock_join_primary"](self.server, self.owner, "primary"))
        self.assertFalse(self.ns["_gamedock_join_primary"](self.server, self.tab, "display2"))

    def test_secure_sessions_do_not_acquire_extra_authority(self):
        self.server.is_secure_mode = True
        self.permissions[self.tab] = {"_gamedock_primary": True, "role": "controller"}
        self.assertFalse(self.ns["_gamedock_join_primary"](self.server, self.tab, "primary"))
        self.assertIsNone(self.ns["_gamedock_promote_primary"](self.server, self.owner))

    def test_owner_close_promotes_only_registered_shared_controller(self):
        self.permissions[self.tab] = {"_gamedock_primary": True, "role": "controller"}
        self.server.clients.remove(self.owner)
        successor = self.ns["_gamedock_promote_primary"](self.server, self.owner)
        self.assertIs(successor, self.tab)
        self.assertIs(self.server.display_clients["primary"]["ws"], self.tab)
        self.assertEqual(self.server.display_clients["primary"]["sent_timestamps"], {})
        self.assertIsNone(self.server.display_clients["primary"]["unacked_since"])
        self.assertIsNone(self.ns["_gamedock_promote_primary"](self.server, self.owner))

    def test_unregistered_viewer_is_not_promoted(self):
        self.server.clients.remove(self.owner)
        self.permissions[self.tab] = {"role": "viewer", "_gamedock_primary": True}
        self.assertIsNone(self.ns["_gamedock_promote_primary"](self.server, self.owner))

    def test_version_drift_fails_image_build(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Selkies source"):
            patch.patch_source("class DataStreamingServer(BaseStreamingService): pass")
