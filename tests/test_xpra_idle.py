"""Execute inside the runtime image to exercise the installed Xpra idle patch."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from xpra.server.source.idle_mixin import IdleConnection
    from xpra.server.source.window import WindowsConnection
    from xpra.server.window.compress import WindowSource
except ImportError:
    IdleConnection = WindowsConnection = WindowSource = None


@unittest.skipUnless(IdleConnection, "Requires Xpra; run inside gamedock-runtime")
class IdleRecovery(unittest.TestCase):
    def test_refresh_batching_can_be_independent(self):
        from xpra.server.window.batch_config import DamageBatchConfig
        for enabled, expected in (("1", 33), ("0", 5)):
            with patch.dict(os.environ, {"GAMEDOCK_BATCH_MATCH_REFRESH": enabled}):
                batch = DamageBatchConfig()
                batch.min_delay = 5
                batch.match_vrefresh(30)
                self.assertEqual(batch.min_delay, expected)
                batch.match_vrefresh(20)
                self.assertEqual(batch.min_delay, 50 if enabled == "1" else 5)

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

    def test_map_clears_stale_iconic_and_clamps_saved_batch_delay(self):
        with patch.dict(os.environ, {"GAMEDOCK_IDLE_FIX": "1"}):
            batch = SimpleNamespace(locked=True, delay=1000, saved=900, min_delay=5, max_delay=50)
            window = SimpleNamespace(iconic=True, is_idle=True, batch_config=batch)
            window.unlock_batch_delay = lambda: WindowSource.unlock_batch_delay(window)
            window.no_idle = lambda: WindowSource.no_idle(window)
            WindowSource.map(window, (0, 0, 1280, 720))
            self.assertFalse(window.iconic)
            self.assertFalse(window.is_idle)
            self.assertFalse(batch.locked)
            self.assertEqual(batch.delay, 50)

    def test_hidden_iconic_window_keeps_its_batch_lock(self):
        batch = SimpleNamespace(locked=True, delay=1000, saved=20, min_delay=5, max_delay=50)
        window = SimpleNamespace(iconic=True, batch_config=batch)
        WindowSource.unlock_batch_delay(window)
        self.assertTrue(batch.locked)
        self.assertEqual(batch.delay, 1000)

    def test_unmap_map_cycles_restore_normal_delay(self):
        with patch.dict(os.environ, {"GAMEDOCK_IDLE_FIX": "1"}):
            batch = SimpleNamespace(locked=False, delay=20, saved=20, min_delay=5, max_delay=50)
            window = SimpleNamespace(iconic=False, is_idle=False, batch_config=batch,
                                     cancel_damage=lambda: None,
                                     statistics=SimpleNamespace(reset=lambda: None))
            window.lock_batch_delay = lambda delay: WindowSource.lock_batch_delay(window, delay)
            window.unlock_batch_delay = lambda: WindowSource.unlock_batch_delay(window)
            window.no_idle = lambda: WindowSource.no_idle(window)
            window.go_idle = lambda: WindowSource.go_idle(window)
            for _ in range(4):
                WindowSource.unmap(window)
                window.iconic = True
                self.assertTrue(batch.locked)
                WindowSource.map(window, (0, 0, 1280, 720))
                self.assertFalse(batch.locked)
                self.assertEqual(batch.delay, 20)

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
