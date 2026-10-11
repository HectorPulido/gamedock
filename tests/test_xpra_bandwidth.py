"""Run inside the runtime to verify the installed Xpra budget patch."""

from types import SimpleNamespace as N
import unittest

try:
    from xpra.server.source.bandwidth import BandwidthConnection
    from xpra.util.objects import typedict
except ImportError:
    BandwidthConnection = None


@unittest.skipUnless(BandwidthConnection, "Requires the runtime's patched Xpra")
class Bandwidth(unittest.TestCase):
    def connection(self, server=6000000, client=0, detection=True, congestion=0):
        c = BandwidthConnection()
        c.init_from(None, N(bandwidth_limit=server, bandwidth_detection=detection))
        c.init_state()
        c.protocol = None
        c.window_sources = {
            1: N(
                suspended=False,
                window_dimensions=(1280, 720),
                statistics=N(get_damage_pixels=lambda: 0),
                bandwidth_limit=0,
            )
        }
        c.statistics = N(avg_congestion_send_speed=congestion)
        c.parse_client_caps(
            typedict({"bandwidth-limit": client, "bandwidth-detection": detection})
        )
        c.update_bandwidth_limits()
        return c

    def test_html5_budget_enables_the_connection(self):
        self.assertTrue(BandwidthConnection.is_needed(typedict({"bandwidth-limit": 0})))

    def test_fixed_budget_survives_missing_unlimited_or_fast_estimates(self):
        for client in (0, 6000000, 12000000):
            for congestion in (0, 100000000):
                for detection in (True, False):
                    c = self.connection(
                        client=client, congestion=congestion, detection=detection
                    )
                    self.assertEqual(c.bandwidth_limit, 6000000)
                    self.assertEqual(c.window_sources[1].bandwidth_limit, 6000000)

    def test_lower_client_and_small_server_budgets_are_not_raised(self):
        c = self.connection(client=1000000)
        self.assertEqual(c.window_sources[1].bandwidth_limit, 1000000)
        c = self.connection(server=500000, client=0)
        self.assertEqual(c.window_sources[1].bandwidth_limit, 500000)
        c = self.connection(server=0, client=1000000)
        self.assertEqual(c.window_sources[1].bandwidth_limit, 1000000)
        c = self.connection(server=0, client=0)
        self.assertEqual(c.window_sources[1].bandwidth_limit, 0)


if __name__ == "__main__":
    unittest.main()
