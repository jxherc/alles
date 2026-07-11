import os
import unittest
from unittest import mock

from core.server_config import bind_host


class ServerBindConfigTest(unittest.TestCase):
    def test_fresh_install_binds_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLES_HOST", None)
            self.assertEqual(bind_host(), "127.0.0.1")

    def test_explicit_host_is_preserved(self):
        with mock.patch.dict(os.environ, {"ALLES_HOST": "0.0.0.0"}):
            self.assertEqual(bind_host(), "0.0.0.0")

    def test_blank_host_falls_back_to_loopback(self):
        with mock.patch.dict(os.environ, {"ALLES_HOST": "   "}):
            self.assertEqual(bind_host(), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
