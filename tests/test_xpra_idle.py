"""Execute inside the runtime image to exercise the installed Xpra idle patch."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from xpra.server.source.idle_mixin import IdleConnection
    from xpra.server.source.window import WindowsConnection
except ImportError:
    IdleConnection = WindowsConnection = None


@unittest.skipUnless(IdleConnection, "Requires Xpra; run inside gamedock-runtime")
class IdleRecovery(unittest.TestCase):
    def test_input_reconciles_a_window_even_when_connection_is_active(self):
        for enabled in ("1", "0"):
            with (
                self.subTest(enabled=enabled),
                patch.dict(os.environ, {"GAMEDOCK_IDLE_FIX": enabled}),
            ):
                window = SimpleNamespace(delay=1000)
                window.no_idle = lambda: setattr(window, "delay", 5)
                source = SimpleNamespace(
                    idle=False,
                    last_user_event=0,
                    notification_callbacks={},
                    all_window_sources=lambda: [window],
                    cancel_idle_grace_timeout=lambda: None,
                    schedule_idle_grace_timeout=lambda: None,
                    cancel_idle_timeout=lambda: None,
                    schedule_idle_timeout=lambda: None,
                )
                source.no_idle = lambda: WindowsConnection.no_idle(source)
                IdleConnection.do_user_event(source)
                self.assertEqual(window.delay, 5 if enabled == "1" else 1000)
                self.assertGreater(source.last_user_event, 0)

    def test_disabled_patch_preserves_normal_whole_connection_recovery(self):
        with patch.dict(os.environ, {"GAMEDOCK_IDLE_FIX": "0"}):
            window = SimpleNamespace(idle=True)
            window.no_idle = lambda: setattr(window, "idle", False)
            source = SimpleNamespace(idle=True, all_window_sources=lambda: [window])
            WindowsConnection.no_idle(source)
            self.assertFalse(source.idle)
            self.assertFalse(window.idle)


if __name__ == "__main__":
    unittest.main()
