import os
import unittest
from unittest.mock import patch
from server.tls import server_tls


class TLS(unittest.TestCase):
    def test_disabled_and_incomplete_configuration(self):
        with patch.dict(os.environ, {"TLS_CERTFILE": "", "TLS_KEYFILE": ""}):
            self.assertIsNone(server_tls())
        with patch.dict(os.environ, {"TLS_CERTFILE": "cert.pem", "TLS_KEYFILE": ""}):
            with self.assertRaises(ValueError):
                server_tls()
