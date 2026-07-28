import json
import os
from unittest import mock

from core import auth
from core.build_info import (
    AFTERLIFE_FEATURE_DEFAULTS,
    afterlife_feature_flags,
    build_info,
    migration_head,
)
from core.migrations.runner import migration_catalog
from services import sysmon
from tests._client import ApiTest


class OsArchTest(ApiTest):
    def test_windows_11_detected_by_build(self):
        with (
            mock.patch.object(sysmon.platform, "system", lambda: "Windows"),
            mock.patch.object(sysmon.platform, "version", lambda: "10.0.26100"),
            mock.patch.object(sysmon.platform, "release", lambda: "10"),
        ):
            self.assertEqual(sysmon._os_name(), "Windows 11")  # build >= 22000

    def test_windows_10_stays_10(self):
        with (
            mock.patch.object(sysmon.platform, "system", lambda: "Windows"),
            mock.patch.object(sysmon.platform, "version", lambda: "10.0.19045"),
            mock.patch.object(sysmon.platform, "release", lambda: "10"),
        ):
            self.assertEqual(sysmon._os_name(), "Windows 10")

    def test_arch_normalizes_amd64(self):
        with mock.patch.object(sysmon.platform, "machine", lambda: "AMD64"):
            self.assertEqual(sysmon._arch(), "x86_64")
        with mock.patch.object(sysmon.platform, "machine", lambda: "ARM64"):
            self.assertEqual(sysmon._arch(), "arm64")

    def test_arch_i386_maps_to_x86(self):
        with mock.patch.object(sysmon.platform, "machine", lambda: "i386"):
            self.assertEqual(sysmon._arch(), "x86")
        with mock.patch.object(sysmon.platform, "machine", lambda: "i686"):
            self.assertEqual(sysmon._arch(), "x86")

    def test_arch_unknown_falls_back_to_raw(self):
        with mock.patch.object(sysmon.platform, "machine", lambda: "mips64"):
            self.assertEqual(sysmon._arch(), "mips64")
        with mock.patch.object(sysmon.platform, "machine", lambda: ""):
            self.assertEqual(sysmon._arch(), "?")

    def test_darwin_os_name(self):
        with (
            mock.patch.object(sysmon.platform, "system", lambda: "Darwin"),
            mock.patch("platform.mac_ver", return_value=("14.5", ("", "", ""), "")),
        ):
            result = sysmon._os_name()
            self.assertTrue(result.startswith("macOS"))

    def test_gb_helper(self):
        self.assertEqual(sysmon._gb(1_000_000_000), 1.0)
        self.assertEqual(sysmon._gb(None), 0.0)
        self.assertEqual(sysmon._gb(0), 0.0)
        self.assertEqual(sysmon._gb(1_500_000_000), 1.5)


class SystemStatsTest(ApiTest):
    def test_process_names_are_safe_for_utf8_json(self):
        process = mock.MagicMock()
        process.info = {"pid": 42, "name": "TT语音娱乐\udce7\udc89"}
        process.cpu_percent.return_value = 1.0
        process.memory_percent.return_value = 2.0
        process.memory_info.return_value.rss = 3
        process.num_threads.return_value = 4
        process.username.return_value = "owner"

        psutil = mock.MagicMock()
        psutil.process_iter.return_value = [process]

        processes, total = sysmon._processes(psutil)

        self.assertEqual(total, 1)
        self.assertEqual(processes[0]["name"], "TT语音娱乐��")
        json.dumps(processes, ensure_ascii=False).encode("utf-8")

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
        self.assertEqual(len(mounts), len(set(mounts)))  # no dup mounts
        self.assertLessEqual(len(s["disks"]), 6)

    def test_server_host_never_follows_the_browser_user_agent(self):
        browsers = {
            "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "macos": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)",
            "linux": "Mozilla/5.0 (X11; Linux x86_64)",
        }
        hosts = {
            "Darwin": ("darwin", "macOS"),
            "Linux": ("linux", "Linux"),
        }
        info = {
            "cpu_name": "test cpu",
            "cpu_cores": 4,
            "total_ram_gb": 8,
            "available_ram_gb": 4,
            "backend": "test",
        }
        for host_name, (expected_platform, expected_os) in hosts.items():
            for browser_name, user_agent in browsers.items():
                with (
                    self.subTest(host=host_name, browser=browser_name),
                    mock.patch.object(sysmon.platform, "system", return_value=host_name),
                    mock.patch.object(sysmon.platform, "release", return_value="test-release"),
                    mock.patch.object(sysmon.platform, "machine", return_value="arm64"),
                    mock.patch.object(sysmon, "_psutil", return_value=None),
                    mock.patch(
                        "services.local_models.detect_system_info",
                        return_value=info,
                    ),
                    mock.patch("platform.mac_ver", return_value=("14.5", ("", "", ""), "")),
                ):
                    body = self.client.get(
                        "/api/system/stats",
                        headers={"User-Agent": user_agent},
                    ).json()
                self.assertEqual(body["host"]["platform"], expected_platform)
                self.assertTrue(body["host"]["os"].startswith(expected_os))
                self.assertNotIn("browser", body["host"])


class BuildInfoTest(ApiTest):
    def test_build_response_is_complete_and_secret_free(self):
        env = {
            "ALLES_VERSION": "1.2.3",
            "ALLES_BUILD_ID": "release-abc123",
            "ALLES_AFTERLIFE_FEATURES": "afterlife_today,afterlife_andromeda",
            "SECRET_KEY": "must-not-leak",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            body = self.client.get("/api/system/build").json()

        self.assertEqual(
            set(body),
            {
                "name",
                "version",
                "build_id",
                "recovery_compatibility",
                "migration_head",
                "feature_flags",
            },
        )
        self.assertEqual(body["name"], "alles")
        self.assertEqual(body["version"], "1.2.3")
        self.assertEqual(body["build_id"], "release-abc123")
        self.assertEqual(body["migration_head"], max(migration_catalog()))
        self.assertEqual(set(body["feature_flags"]), set(AFTERLIFE_FEATURE_DEFAULTS))
        self.assertTrue(body["feature_flags"]["afterlife_today"])
        self.assertTrue(body["feature_flags"]["afterlife_andromeda"])
        self.assertNotIn("must-not-leak", str(body))
        self.assertEqual(self.client.patch("/api/system/build", json={}).status_code, 405)

    def test_build_endpoint_requires_auth_when_login_is_enabled(self):
        with mock.patch.dict(
            os.environ,
            {"AUTH_ENABLED": "true", "ALLES_AFTERLIFE_FEATURES": ""},
            clear=False,
        ):
            self.assertEqual(self.client.get("/api/system/build").status_code, 401)

            token = auth.create_session_token()
            auth.store_token(token)
            self.client.cookies.set("aide_session", token)
            try:
                response = self.client.get("/api/system/build")
            finally:
                self.client.cookies.delete("aide_session")
                auth.revoke_token(token)
        self.assertEqual(response.status_code, 200)

    def test_delivered_afterlife_features_default_on(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLES_AFTERLIFE_FEATURES", None)
            flags = afterlife_feature_flags()
            self.assertEqual(flags, AFTERLIFE_FEATURE_DEFAULTS)
            self.assertTrue(flags["afterlife_shell"])
            self.assertTrue(flags["afterlife_today"])
            self.assertTrue(flags["afterlife_aide_projects"])
            self.assertTrue(flags["afterlife_andromeda"])
            self.assertFalse(flags["afterlife_jarvis"])
            self.assertFalse(flags["afterlife_storage_locations"])

    def test_feature_override_is_strict(self):
        flags = afterlife_feature_flags("afterlife_shell, afterlife_storage_locations")
        self.assertTrue(flags["afterlife_shell"])
        self.assertTrue(flags["afterlife_storage_locations"])
        self.assertFalse(flags["afterlife_today"])
        self.assertFalse(flags["afterlife_aide_projects"])
        self.assertFalse(flags["afterlife_andromeda"])
        self.assertFalse(flags["afterlife_jarvis"])

        for invalid in (
            "future_surface",
            "afterlife_shell,",
            "afterlife_shell,afterlife_shell",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                afterlife_feature_flags(invalid)

    def test_shared_build_info_stays_recovery_compatible(self):
        with mock.patch.dict(
            os.environ,
            {"ALLES_VERSION": "2.0.0", "ALLES_BUILD_ID": "build-2"},
            clear=False,
        ):
            info = build_info()
        self.assertEqual(info["version"], "2.0.0")
        self.assertEqual(info["build_id"], "build-2")
        self.assertIsInstance(info["recovery_compatibility"], int)
        self.assertEqual(migration_head(), max(migration_catalog()))
