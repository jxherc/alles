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

    def test_whitespace_only_proxy_is_noop(self):
        cs.save_settings({"outbound_proxy": "   "})
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("HTTP_PROXY", None)
        result = net.apply_proxy()
        self.assertEqual(result, "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))
        self.assertIsNone(os.environ.get("HTTP_PROXY"))

    def test_empty_string_proxy_is_noop(self):
        cs.save_settings({"outbound_proxy": ""})
        os.environ.pop("HTTPS_PROXY", None)
        result = net.apply_proxy()
        self.assertEqual(result, "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))

    def test_idempotent_double_call(self):
        cs.save_settings({"outbound_proxy": "http://proxy.local:3128"})
        r1 = net.apply_proxy()
        r2 = net.apply_proxy()
        self.assertEqual(r1, r2)
        self.assertEqual(os.environ.get("HTTPS_PROXY"), "http://proxy.local:3128")

    def test_changing_proxy_updates_env(self):
        cs.save_settings({"outbound_proxy": "http://first.proxy:1111"})
        net.apply_proxy()
        cs.save_settings({"outbound_proxy": "http://second.proxy:2222"})
        net.apply_proxy()
        self.assertEqual(os.environ.get("HTTPS_PROXY"), "http://second.proxy:2222")
        self.assertEqual(os.environ.get("HTTP_PROXY"), "http://second.proxy:2222")

    def test_return_type_is_str(self):
        result = net.apply_proxy()
        self.assertIsInstance(result, str)

    def test_proxy_none_in_settings_is_noop(self):
        cs.save_settings({"outbound_proxy": None})
        os.environ.pop("HTTPS_PROXY", None)
        result = net.apply_proxy()
        self.assertEqual(result, "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))

    def test_no_settings_file_is_noop(self):
        # settings file never written → fresh state → no proxy
        os.environ.pop("HTTPS_PROXY", None)
        result = net.apply_proxy()
        self.assertEqual(result, "")
        self.assertIsNone(os.environ.get("HTTPS_PROXY"))

    def test_both_env_vars_set_together(self):
        cs.save_settings({"outbound_proxy": "http://corp.proxy:8080"})
        net.apply_proxy()
        self.assertEqual(os.environ.get("HTTP_PROXY"), os.environ.get("HTTPS_PROXY"))


if __name__ == "__main__":
    unittest.main()
