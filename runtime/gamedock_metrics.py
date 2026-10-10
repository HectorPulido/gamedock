"""Lightweight Xpra capture telemetry, attached to its existing info response."""

from collections import deque
import functools
import json
import os
from pathlib import Path
from threading import Lock
import time


class CaptureMetrics:
    def __init__(self, settings, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.settings = settings
        self.enabled = settings.get("diagnostics_enabled", True)
        self.window = settings.get("metrics_interval", 2)
        self.reads = deque(maxlen=4096)
        self.cycles = deque(maxlen=4096)
        self.total = 0
        self.lock = Lock()
        self.cpu_previous = None

    def read(self, elapsed, pixels):
        if self.enabled:
            with self.lock:
                self.total += 1
                self.reads.append((self.clock(), elapsed, pixels))

    def cycle(self):
        if self.enabled:
            with self.lock:
                self.cycles.append(self.clock())

    def snapshot(self):
        if not self.enabled:
            return {"enabled": False}
        now = self.clock()
        span = max(0.001, min(self.window, now - self.started))
        with self.lock:
            reads = [r for r in self.reads if r[0] > now - span]
            cycles = [t for t in self.cycles if t > now - span]
            total = self.total
        return {
            "enabled": True,
            "sample_seconds": span,
            "capture_reads": total,
            "capture_fps": round(len(reads) / span, 2),
            "capture_cycles_fps": round(len(cycles) / span, 2),
            "capture_ms": round(sum(r[1] for r in reads) * 1000 / len(reads), 3)
            if reads
            else 0,
            "capture_mpix_s": round(sum(r[2] for r in reads) / span / 1_000_000, 2),
            "target_hz": self.settings.get("refresh_rate", 30),
            "settings": self.settings,
            **self.cpu(now),
        }

    def cpu(self, now):
        """Separate game CPU from Xpra/Xvfb CPU; 100% means one logical core."""
        processes = {}
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                raw = path.read_text()
                name = raw[raw.index("(") + 1 : raw.rindex(")")]
                fields = raw[raw.rindex(")") + 2 :].split()
                processes[int(path.parent.name)] = (
                    int(fields[1]),
                    name,
                    int(fields[11]) + int(fields[12]),
                    int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                )
            except (OSError, ValueError, IndexError):
                continue
        xpra_pid = os.getpid()
        root = os.getppid()

        def descendant(pid, ancestor):
            visited = set()
            while pid in processes and pid not in visited:
                if pid == ancestor:
                    return True
                visited.add(pid)
                pid = processes[pid][0]
            return False

        totals = {"game": 0, "stream": 0}
        memory = {"game": 0, "stream": 0}
        for pid, (_, name, ticks, rss) in processes.items():
            if not descendant(pid, root) or pid == root:
                continue
            kind = (
                "stream"
                if descendant(pid, xpra_pid) or name in ("Xvfb", "openbox")
                else "game"
            )
            totals[kind] += ticks
            memory[kind] += rss
        previous = self.cpu_previous
        self.cpu_previous = (now, totals)
        result = {
            kind + "_rss_mb": round(rss / 1024**2, 1) for kind, rss in memory.items()
        }
        for kind in totals:
            result[kind + "_cpu_percent"] = (
                None
                if previous is None
                else round(
                    max(0, totals[kind] - previous[1][kind])
                    / os.sysconf("SC_CLK_TCK")
                    / max(0.001, now - previous[0])
                    * 100,
                    1,
                )
            )
        return result


def instrument(server_class):
    """Install once at Xpra server import; no extra process, port, or polling CLI."""
    if getattr(server_class, "_gamedock_metrics_installed", False):
        return
    server_class._gamedock_metrics_installed = True
    settings = json.loads(os.environ.get("GAMEDOCK_STREAMING", "{}"))
    metrics = CaptureMetrics(settings)
    if metrics.enabled:
        from xpra.x11.shadow.ximage_capture import XImageCapture
        from xpra.gtk.capture import GTKImageCapture

        for cls in (XImageCapture, GTKImageCapture):
            original = cls.get_image

            def wrap(method):
                @functools.wraps(method)
                def measured(self, x, y, width, height):
                    started = time.monotonic()
                    result = method(self, x, y, width, height)
                    if result is not None:
                        metrics.read(time.monotonic() - started, width * height)
                    return result

                return measured

            cls.get_image = wrap(original)
        original_refresh = server_class.refresh_windows

        def refresh(self):
            metrics.cycle()
            return original_refresh(self)

        server_class.refresh_windows = refresh
    original_info = server_class.get_threaded_info

    def info(self, *args, **kwargs):
        result = original_info(self, *args, **kwargs)

        # HTML5 rencodeplus cannot decode float64 (typecode 44).
        # Keep decimal precision as strings; omit unavailable initial CPU values.
        def compatible(value):
            if isinstance(value, dict):
                return {
                    key: compatible(item)
                    for key, item in value.items()
                    if item is not None
                }
            if isinstance(value, float):
                return str(value)
            return value

        result["gamedock"] = compatible(metrics.snapshot())
        return result

    server_class.get_threaded_info = info
