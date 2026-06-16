from unittest import mock

from tests._client import ApiTest
from services import sysmon


class OsArchTest(ApiTest):
    def test_windows_11_detected_by_build(self):
        with mock.patch.object(sysmon.platform, "system", lambda: "Windows"), \
             mock.patch.object(sysmon.platform, "version", lambda: "10.0.26100"), \
             mock.patch.object(sysmon.platform, "release", lambda: "10"):
            self.assertEqual(sysmon._os_name(), "Windows 11")   # build >= 22000

    def test_windows_10_stays_10(self):
        with mock.patch.object(sysmon.platform, "system", lambda: "Windows"), \
             mock.patch.object(sysmon.platform, "version", lambda: "10.0.19045"), \
             mock.patch.object(sysmon.platform, "release", lambda: "10"):
            self.assertEqual(sysmon._os_name(), "Windows 10")

    def test_arch_normalizes_amd64(self):
        with mock.patch.object(sysmon.platform, "machine", lambda: "AMD64"):
            self.assertEqual(sysmon._arch(), "x86_64")
        with mock.patch.object(sysmon.platform, "machine", lambda: "ARM64"):
            self.assertEqual(sysmon._arch(), "arm64")


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
