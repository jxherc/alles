"""ui-5a — /api/files/quota reports the underlying disk's free space (Docker-aware:
disk_usage on the data dir's volume), not just used/total."""

from tests._client import ApiTest


class QuotaTests(ApiTest):
    def test_quota_has_free_total_used(self):
        q = self.client.get("/api/files/quota").json()
        for k in ("used", "total", "free"):
            self.assertIn(k, q)

    def test_free_is_a_real_positive_disk_figure(self):
        q = self.client.get("/api/files/quota").json()
        self.assertGreater(q["total"], 0)
        self.assertGreater(q["free"], 0)
        self.assertLessEqual(q["free"], q["total"])

    def test_free_plus_used_within_total(self):
        q = self.client.get("/api/files/quota").json()
        # used is the vault's own bytes; it can't exceed the disk
        self.assertLessEqual(q["used"], q["total"])
