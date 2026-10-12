"""Configuration inheritance and runtime flags for real streaming behavior."""

import unittest
from runtime.streaming import (
    STREAMING_DEFAULTS,
    STREAMING_PRESETS,
    validate_streaming,
    runtime_options,
)


class Streaming(unittest.TestCase):
    def test_profiles_are_consistent_and_preserve_resolution(self):
        for name, preset in STREAMING_PRESETS.items():
            with self.subTest(name=name):
                args, env = runtime_options(preset)
                self.assertIn("--resize-display=no", args)
                self.assertEqual(env["XPRA_BATCH_MAX_DELAY"], "40")
                self.assertEqual(env["GAMEDOCK_IDLE_FIX"], "1")
        args, env = runtime_options(
            {
                "xshm": False,
                "idle_fix": False,
                "socket_nodelay": False,
                "socket_cork": True,
                "bandwidth_mbps": 6,
                "quality": 95,
            }
        )
        self.assertIn("--bandwidth-limit=6000000", args)
        self.assertIn("--quality=95", args)
        self.assertEqual(env["XPRA_SHADOW_XSHM"], "0")
        self.assertEqual(env["GAMEDOCK_IDLE_FIX"], "0")
        self.assertEqual(env["XPRA_SOCKET_CORK"], "1")

    def test_fsr_is_client_only_and_preserves_legacy_filters(self):
        self.assertEqual(STREAMING_DEFAULTS["canvas_filter"], "fsr")
        baseline = runtime_options({"canvas_filter": "smooth"})
        for mode in ("fsr", "crisp", "smooth"):
            self.assertEqual(runtime_options({"canvas_filter": mode}), baseline)
            self.assertEqual(
                validate_streaming({"canvas_filter": mode})["canvas_filter"], mode
            )

    def test_independent_batching_keeps_capture_target(self):
        args, env = runtime_options({"batch_match_refresh": False, "refresh_rate": 30})
        self.assertIn("--refresh-rate=30", args)
        self.assertEqual(env["GAMEDOCK_BATCH_MATCH_REFRESH"], "0")
        self.assertEqual(env["GAMEDOCK_CAPTURE_HZ"], "30")
        self.assertEqual(env["XPRA_BATCH_MIN_DELAY"], "5")
        self.assertEqual(runtime_options({})[1]["GAMEDOCK_BATCH_MATCH_REFRESH"], "1")

    def test_invalid_values_and_conflicting_options(self):
        for value in (
            None,
            [],
            {"quality": True},
            {"quality": 101},
            {"refresh_rate": 1.5},
            {"bandwidth_mbps": float("nan")},
            {"idle_fix": 1},
            {"encoding": "h264;echo hello"},
            {"unknown": 1},
            {"batch_min_delay": 50},
            {"quality": 20},
            {"encoding": "jpeg", "encodings": "png,rgb"},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_streaming(value, complete=True)
        self.assertEqual(validate_streaming({}), {})
        self.assertEqual(validate_streaming({}, complete=True), STREAMING_DEFAULTS)
