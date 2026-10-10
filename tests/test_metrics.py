"""Measured image reads must not be confused with display refresh or game FPS."""

import unittest
from runtime.gamedock_metrics import CaptureMetrics


class Metrics(unittest.TestCase):
    def test_capture_rate_uses_successful_reads_and_expires_when_idle(self):
        now = [0.0]
        metrics = CaptureMetrics(
            {"metrics_interval": 2, "refresh_rate": 60}, clock=lambda: now[0]
        )
        for i in range(10):
            now[0] = (i + 1) / 10
            metrics.read(0.005, 1280 * 720)
        for i in range(20):
            metrics.cycle()
        now[0] = 2
        sample = metrics.snapshot()
        self.assertEqual(sample["capture_fps"], 5)
        self.assertEqual(sample["capture_cycles_fps"], 10)
        self.assertEqual(sample["capture_ms"], 5)
        self.assertEqual(sample["target_hz"], 60)
        self.assertIsNone(sample["game_cpu_percent"])
        now[0] = 5
        idle = metrics.snapshot()
        self.assertEqual(idle["capture_fps"], 0)
        self.assertEqual(idle["capture_cycles_fps"], 0)
        self.assertEqual(idle["capture_reads"], 10)

    def test_disabled_diagnostics_do_no_capture_accounting(self):
        metrics = CaptureMetrics({"diagnostics_enabled": False})
        metrics.read(0.01, 100)
        metrics.cycle()
        self.assertEqual(metrics.snapshot(), {"enabled": False})
        self.assertEqual(metrics.total, 0)
        self.assertFalse(metrics.reads)


if __name__ == "__main__":
    unittest.main()
