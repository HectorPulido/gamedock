"""Session process/cgroup telemetry, with optional transport capture counters."""

from collections import deque
import json
import os
from pathlib import Path
from threading import Lock
import time


class CaptureMetrics:
    def __init__(
        self,
        settings,
        clock=time.monotonic,
        proc_root="/proc",
        cgroup_root="/sys/fs/cgroup",
    ):
        self.proc_root = Path(proc_root)
        self.cgroup_root = Path(cgroup_root)
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
        try:
            self.graphics = json.loads(
                (
                    Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/gamedock-runtime"))
                    / "gpu.json"
                ).read_text()
            )
        except (OSError, ValueError):
            self.graphics = {"enabled": False, "vendor": "none"}

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
            "gpu_vendor": self.graphics.get("vendor", "none"),
            "software_threads": self.graphics.get("software_threads", 0),
            "gpu_renderer": self.graphics.get("renderer", "GPU acceleration disabled"),
            **self.cpu(now),
        }

    def cpu(self, now):
        """Account for reparented game processes in the dedicated PID namespace.

        Docker exec trees (PPID 0), the runtime and PID 1 are infrastructure.
        Wine orphans adopted by PID 1 remain game processes. RSS sums may count
        shared pages repeatedly; PSS and cgroup usage are reported separately.
        """
        processes = {}
        for path in self.proc_root.glob("[0-9]*/stat"):
            try:
                raw = path.read_text()
                name = raw[raw.index("(") + 1 : raw.rindex(")")]
                fields = raw[raw.rindex(")") + 2 :].split()
                processes[int(path.parent.name)] = (
                    int(fields[1]),
                    name,
                    int(fields[11]) + int(fields[12]),
                    int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                    int(fields[19]),
                )
            except (OSError, ValueError, IndexError):
                continue
        stream_pid, root = os.getpid(), os.getppid()

        def descendant(pid, ancestor):
            visited = set()
            while pid in processes and pid not in visited:
                if pid == ancestor:
                    return True
                visited.add(pid)
                pid = processes[pid][0]
            return False

        # Selkies runs capture/audio/HTTP as sibling processes. The supervisor
        # publishes their roots; keep Wine/game orphans accounted separately.
        try:
            stream_roots = json.loads((Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/gamedock-runtime")) / "stream-processes.json").read_text())
        except (OSError, ValueError):
            stream_roots = [stream_pid]
        ticks_by_pid = {}
        memory = {"game": 0, "stream": 0}
        pss = {"game": 0, "stream": 0}
        counts = {"game": 0, "stream": 0}
        pss_complete = {"game": True, "stream": True}
        for pid, (_, name, ticks, rss, started) in processes.items():
            if pid in (1, root) or not (descendant(pid, root) or descendant(pid, 1)):
                continue
            kind = (
                "stream"
                if any(descendant(pid, p) for p in stream_roots) or name in ("Xvfb", "openbox")
                else "game"
            )
            ticks_by_pid[(pid, started)] = (kind, ticks)
            memory[kind] += rss
            counts[kind] += 1
            try:
                lines = (
                    (self.proc_root / str(pid) / "smaps_rollup")
                    .read_text()
                    .splitlines()
                )
                pss[kind] += next(
                    int(line.split()[1]) * 1024
                    for line in lines
                    if line.startswith("Pss:")
                )
            except (OSError, ValueError, StopIteration):
                pss_complete[kind] = False
        previous = self.cpu_previous
        self.cpu_previous = (now, ticks_by_pid)
        result = {
            kind + "_rss_mb": round(rss / 1024**2, 1) for kind, rss in memory.items()
        }
        for kind in memory:
            result[kind + "_processes"] = counts[kind]
            result[kind + "_pss_mb"] = (
                round(pss[kind] / 1024**2, 1) if pss_complete[kind] else None
            )
            delta = sum(
                max(0, ticks - previous[1][key][1])
                for key, (group, ticks) in ticks_by_pid.items()
                if previous and group == kind and key in previous[1]
            )
            result[kind + "_cpu_percent"] = (
                None
                if previous is None
                else round(
                    delta
                    / os.sysconf("SC_CLK_TCK")
                    / max(0.001, now - previous[0])
                    * 100,
                    1,
                )
            )
        try:
            result["container_memory_mb"] = round(
                int((self.cgroup_root / "memory.current").read_text()) / 1024**2, 1
            )
        except (OSError, ValueError):
            result["container_memory_mb"] = None
        try:
            stats = dict(
                line.split()
                for line in (self.cgroup_root / "cpu.stat").read_text().splitlines()
            )
            usage = int(stats["usage_usec"])
            old = getattr(self, "container_previous", None)
            self.container_previous = (now, usage)
            result["container_cpu_percent"] = (
                None
                if old is None
                else round(
                    max(0, usage - old[1]) / 1_000_000 / max(0.001, now - old[0]) * 100,
                    1,
                )
            )
        except (OSError, ValueError, KeyError):
            result["container_cpu_percent"] = None
        return result
