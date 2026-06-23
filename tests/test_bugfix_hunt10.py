"""regression tests for the 12th bug-hunt iteration (SSRF + apply_patch guard):
- the shared net_guard blocks internal/metadata addresses
- the URL-fetching code paths refuse internal urls
- _patch_targets now sees deletion + rename targets so the permission guard isn't bypassed
"""

import asyncio
import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import net_guard


class NetGuardTests(unittest.TestCase):
    def test_blocks_internal_ip_literals(self):
        for u in (
            "http://127.0.0.1/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/",
            "http://192.168.1.5/admin",
            "http://172.16.0.1/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ):
            self.assertFalse(net_guard.is_safe_url(u), u)

    def test_blocks_localhost_name(self):
        self.assertFalse(net_guard.is_safe_url("http://localhost:8077/api/settings"))

    def test_blocks_bad_scheme(self):
        self.assertFalse(net_guard.is_safe_url("file:///etc/passwd"))
        self.assertFalse(net_guard.is_safe_url("ftp://x/"))

    def test_allows_public_ip_literal(self):
        # 8.8.8.8 is public; checked as a literal so no DNS is needed offline
        self.assertTrue(net_guard.is_safe_url("http://8.8.8.8/"))

    def test_assert_raises_on_internal(self):
        with self.assertRaises(ValueError):
            net_guard.assert_safe_url("http://127.0.0.1/")


class FetchGuardTests(unittest.TestCase):
    def test_fetch_webpage_content_blocks_internal(self):
        from services.research.search import fetch_webpage_content

        out = fetch_webpage_content("http://127.0.0.1:8077/api/calendar/export.ics")
        self.assertFalse(out["success"])

    def test_web_fetch_blocks_internal(self):
        from services.agent_tools import _web_fetch

        out = asyncio.run(_web_fetch("http://169.254.169.254/latest/meta-data/"))
        self.assertTrue(out["error"])

    def test_fetch_ics_blocks_internal(self):
        from routes.calendar import fetch_ics

        with self.assertRaises(ValueError):
            fetch_ics("http://127.0.0.1:8077/api/calendar/export.ics")


class PatchTargetsTests(unittest.TestCase):
    def test_deletion_target_seen(self):
        from services.agent_tools import _patch_targets

        diff = "diff --git a/.env b/.env\ndeleted file mode 100644\n--- a/.env\n+++ /dev/null\n@@ -1 +0,0 @@\n-SECRET=1\n"
        targets = _patch_targets(diff)
        self.assertIn(".env", targets)  # the deletion target is now guarded

    def test_rename_target_seen(self):
        from services.agent_tools import _patch_targets

        diff = "diff --git a/a.txt b/.ssh/authorized_keys\nrename from a.txt\nrename to .ssh/authorized_keys\n"
        targets = _patch_targets(diff)
        self.assertTrue(any("authorized_keys" in t for t in targets))

    def test_normal_add_still_seen(self):
        from services.agent_tools import _patch_targets

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertIn("foo.py", _patch_targets(diff))


if __name__ == "__main__":
    unittest.main()
