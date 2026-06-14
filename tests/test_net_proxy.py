import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings as cs
from services import net


class NetProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self._p.start()
        self._saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY")}

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_proxy_is_noop(self):
        os.environ.pop("HTTPS_PROXY", None)
        self.assertEqual(net.apply_proxy(), "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))

    def test_proxy_applied_to_env(self):
        cs.save_settings({"outbound_proxy": "http://127.0.0.1:7890"})
        self.assertEqual(net.apply_proxy(), "http://127.0.0.1:7890")
        self.assertEqual(os.environ.get("HTTPS_PROXY"), "http://127.0.0.1:7890")
        self.assertEqual(os.environ.get("HTTP_PROXY"), "http://127.0.0.1:7890")


if __name__ == "__main__":
    unittest.main()
