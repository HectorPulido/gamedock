"""Measured image reads must not be confused with display refresh or game FPS."""

import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
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

    def test_wine_orphans_exec_isolation_pss_and_pid_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc"
            cgroup = Path(tmp) / "cgroup"
            cgroup.mkdir()
            (cgroup / "memory.current").write_text(str(3800 * 1024**2))
            (cgroup / "cpu.stat").write_text("usage_usec 1000000\n")

            def process(pid, ppid, name, ticks, mib, start=1):
                folder = proc / str(pid)
                folder.mkdir(parents=True, exist_ok=True)
                fields = ["0"] * 22
                fields[0], fields[1] = "S", str(ppid)
                fields[11], fields[19], fields[21] = (
                    str(ticks),
                    str(start),
                    str(mib * 1024**2 // os.sysconf("SC_PAGE_SIZE")),
                )
                (folder / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
                (folder / "smaps_rollup").write_text(f"Pss: {mib * 512} kB\n")

            process(1, 0, "docker-init", 1, 1)
            process(57, 1, "python3", 1, 10)
            process(71, 57, "python3", 100, 150)
            process(58, 57, "Xvfb", 100, 70)
            process(72, 57, "Launcher", 100, 600)
            process(887, 1, "Dofus.exe", 1000, 2600)
            process(92, 1, "wineserver", 100, 20)
            process(999, 0, "python3", 10000, 2000)
            process(1000, 999, "helper", 10000, 2000)
            metrics = CaptureMetrics({}, proc_root=proc, cgroup_root=cgroup)
            with (
                patch("os.getpid", return_value=71),
                patch("os.getppid", return_value=57),
            ):
                first = metrics.cpu(1)
                self.assertEqual(first["game_rss_mb"], 3220)
                self.assertEqual(first["game_pss_mb"], 1610)
                self.assertEqual(first["game_processes"], 3)
                self.assertEqual(first["stream_rss_mb"], 220)
                self.assertEqual(first["container_memory_mb"], 3800)
                process(887, 1, "Dofus.exe", 1100, 2600)
                (cgroup / "cpu.stat").write_text("usage_usec 1500000\n")
                second = metrics.cpu(2)
                self.assertGreater(second["game_cpu_percent"], 0)
                self.assertEqual(second["container_cpu_percent"], 50)
                # A recycled PID must not inherit its predecessor's tick counter.
                process(887, 1, "Dofus.exe", 99999, 2600, start=2)
                third = metrics.cpu(3)
                self.assertEqual(third["game_cpu_percent"], 0)

    def test_disabled_diagnostics_do_no_capture_accounting(self):
        metrics = CaptureMetrics({"diagnostics_enabled": False})
        metrics.read(0.01, 100)
        metrics.cycle()
        self.assertEqual(metrics.snapshot(), {"enabled": False})
        self.assertEqual(metrics.total, 0)
        self.assertFalse(metrics.reads)


if __name__ == "__main__":
    unittest.main()
