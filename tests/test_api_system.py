from tests._client import ApiTest
from services import sysmon


class SystemStatsTest(ApiTest):
    def test_stats_shape(self):
        r = self.client.get("/api/system/stats")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for k in ("live", "cpu", "memory", "disks", "gpu", "host"):
            self.assertIn(k, d)
        self.assertIn("percent", d["memory"])
        self.assertIsInstance(d["disks"], list)
        self.assertIn("cores", d["cpu"])

    def test_snapshot_memory_sane(self):
        s = sysmon.snapshot()
        m = s["memory"]
        # used never exceeds total; percent in [0,100]
        self.assertLessEqual(m["used_gb"], m["total_gb"] + 0.1)
        self.assertGreaterEqual(m["percent"], 0)
        self.assertLessEqual(m["percent"], 100)

    def test_disks_deduped_and_capped(self):
        s = sysmon.snapshot()
        mounts = [d["mount"] for d in s["disks"]]
        self.assertEqual(len(mounts), len(set(mounts)))   # no dup mounts
        self.assertLessEqual(len(s["disks"]), 6)
