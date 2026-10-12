"""Viewer leases are independent of user input and game processes.

All mutations run under the portal launch_lock. Unknown presence never expires.
"""

import math
from dataclasses import dataclass, field


class DesktopStopped(Exception):
    """Docker positively verified the game container is absent or stopped."""


@dataclass
class Presence:
    leases: set = field(default_factory=set)
    known: bool = False
    observed: int = 0
    ever_seen: bool = False
    since: float | None = None
    generation: int = 0

    def connect(self, token):
        self.generation += 1
        self.leases.add(token)
        # Old proxy sockets cannot survive a portal restart. Once a new proxy
        # connects, its leases replace the bootstrap observation from Xpra.
        self.observed = 0
        self.known = True
        self.since = None

    def disconnect(self, token, now):
        self.generation += 1
        self.leases.discard(token)
        if not self.leases:
            self.observed = 0
            self.since = now

    def reconcile(self, data, now, portal_started):
        count = data["viewers"]
        if type(count) is not int or count < 0 or type(data["ever_seen"]) is not bool:
            raise ValueError("Invalid viewer presence")
        self.known = True
        self.observed = count
        self.ever_seen |= data["ever_seen"] or count > 0
        if count or self.leases:
            self.since = None
        elif self.since is None:
            # On portal restart grant a fresh grace period; never backdate expiry.
            self.since = max(portal_started, now)

    def report(self, cfg, now):
        count = max(len(self.leases), self.observed) if self.known else None
        elapsed = (
            max(0, now - self.since) if count == 0 and self.since is not None else None
        )
        grace = (
            cfg["viewer_disconnect_seconds"]
            if self.ever_seen
            else cfg["viewer_first_connect_seconds"]
        )
        pending = cfg["viewer_action"] == "stop" and elapsed is not None
        return {
            "count": count,
            "state": "unknown"
            if count is None
            else "connected"
            if count
            else "disconnected",
            "without_viewer_seconds": int(elapsed) if elapsed is not None else None,
            "waiting_for_first_viewer": not self.ever_seen,
            "stop_pending": pending,
            "stop_in_seconds": max(0, math.ceil(grace - elapsed)) if pending else None,
        }

    def due(self, cfg, now):
        report = self.report(cfg, now)
        return report["stop_pending"] and report["stop_in_seconds"] == 0
