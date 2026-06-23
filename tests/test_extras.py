"""stage 5e - gated native/local-ML extras registry. tests first (RED)."""

import os
import unittest
from unittest import mock

os.environ["AUTH_ENABLED"] = "false"
from services import extras


class ExtrasTests(unittest.TestCase):
    def test_status_lists_all(self):
        st = extras.status({})
        keys = {e["key"] for e in st}
        # the declared extras are all present
        self.assertTrue({"clip_search", "ocr", "photokit", "eventkit", "keychain"} <= keys)

    def test_available_false_on_wrong_platform(self):
        # photokit is darwin-only; force a non-mac platform
        with mock.patch.object(extras, "_platform", return_value="win32"):
            self.assertFalse(extras.available("photokit"))

    def test_available_true_on_right_platform_and_deps(self):
        with (
            mock.patch.object(extras, "_platform", return_value="darwin"),
            mock.patch.object(extras, "_has_module", return_value=True),
        ):
            self.assertTrue(extras.available("photokit"))

    def test_available_false_missing_dep(self):
        # clip_search is cross-platform but needs a module; pretend it's absent
        with mock.patch.object(extras, "_has_module", return_value=False):
            self.assertFalse(extras.available("clip_search"))

    def test_enabled_requires_available_and_setting(self):
        with mock.patch.object(extras, "available", return_value=True):
            self.assertTrue(extras.enabled("ocr", {"extra_ocr": True}))
            self.assertFalse(extras.enabled("ocr", {"extra_ocr": False}))
        with mock.patch.object(extras, "available", return_value=False):
            self.assertFalse(extras.enabled("ocr", {"extra_ocr": True}))

    def test_unknown_key_safe(self):
        self.assertFalse(extras.available("nope"))
        self.assertFalse(extras.enabled("nope", {}))

    def test_status_carries_available_and_enabled(self):
        with mock.patch.object(extras, "available", side_effect=lambda k: k == "ocr"):
            st = {e["key"]: e for e in extras.status({"extra_ocr": True})}
            self.assertTrue(st["ocr"]["available"])
            self.assertTrue(st["ocr"]["enabled"])
            self.assertFalse(st["clip_search"]["available"])


if __name__ == "__main__":
    unittest.main()
