import unittest
from unittest.mock import AsyncMock
from network.policy import validate_policy, output_rules, BLOCKED
from server.app import Docker


class Policy(unittest.TestCase):
    def test_legacy_migration(self):
        self.assertEqual(validate_policy(internet=True)["mode"], "internet")
        self.assertEqual(validate_policy()["mode"], "offline")

    def test_reject_invalid_exceptions(self):
        for value in (
            {"mode": "bad"},
            {
                "mode": "internet",
                "allow": [{"cidr": "::/0", "port": 80, "protocol": "tcp"}],
            },
            {
                "mode": "internet",
                "allow": [{"cidr": "0.0.0.0/0", "port": 80, "protocol": "tcp"}],
            },
            {"allow": [{"cidr": "1.1.1.1", "port": True, "protocol": "tcp"}]},
            {"deny": [";echo unsafe"]},
        ):
            with self.assertRaises(ValueError):
                validate_policy(value)

    def test_rule_order_and_offline(self):
        policy = validate_policy(
            {
                "mode": "internet",
                "allow": [{"cidr": "192.168.0.7/32", "port": 5555, "protocol": "tcp"}],
                "deny": ["192.168.0.8/32"],
            }
        )
        rules = output_rules(policy)
        self.assertLess(
            next(i for i, r in enumerate(rules) if "192.168.0.8/32" in r),
            next(i for i, r in enumerate(rules) if "192.168.0.7/32" in r),
        )
        self.assertLess(
            next(i for i, r in enumerate(rules) if "192.168.0.7/32" in r),
            next(i for i, r in enumerate(rules) if "192.168.0.0/16" in r),
        )
        self.assertEqual(rules[-1], ["-j", "ACCEPT"])
        self.assertEqual(len(output_rules(validate_policy())), 3)
        self.assertFalse(
            any(
                r == ["-j", "ACCEPT"]
                for r in output_rules(validate_policy({"mode": "allowlist"}))
            )
        )


class Launch(unittest.IsolatedAsyncioTestCase):
    async def test_failure_never_starts_game(self):
        docker = Docker()

        async def response(method, path, *args, **kwargs):
            if path.endswith("/json"):
                return {"State": {"Running": False}}
            return {}

        docker.request = AsyncMock(side_effect=response)
        with self.assertRaisesRegex(RuntimeError, "firewall failed"):
            await docker.start(
                "blocked",
                1,
                {
                    "id": "desktop",
                    "image": "test",
                    "command": [],
                    "env": {},
                    "memory_mb": 128,
                    "cpus": 1,
                },
                "1280x720",
            )
        self.assertFalse(
            any(
                c.args[1] == "/containers/gamedock-blocked/start"
                for c in docker.request.call_args_list
            )
        )
        self.assertTrue(
            any(
                c.args[0] == "DELETE" and "gamedock-gateway-blocked" in c.args[1]
                for c in docker.request.call_args_list
            )
        )
