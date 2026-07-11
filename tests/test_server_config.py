import os
import unittest
from unittest import mock

from core.server_config import (
    AccessConfigError,
    access_profile,
    bind_host,
    cors_origins,
    forwarded_allow_ips,
    public_origin,
    trusted_hosts,
)


class ServerBindConfigTest(unittest.TestCase):
    def test_fresh_install_binds_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bind_host(), "127.0.0.1")
            self.assertEqual(access_profile(), "device")

    def test_device_profile_accepts_only_loopback(self):
        for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
            with self.subTest(host=host), mock.patch.dict(
                os.environ,
                {"ALLES_ACCESS_PROFILE": "device", "ALLES_HOST": host},
                clear=True,
            ):
                self.assertEqual(bind_host(), host)

        with mock.patch.dict(
            os.environ,
            {"ALLES_ACCESS_PROFILE": "device", "ALLES_HOST": "0.0.0.0"},
            clear=True,
        ):
            with self.assertRaisesRegex(AccessConfigError, "device.*loopback"):
                bind_host()

    def test_wide_host_needs_an_explicit_profile(self):
        with mock.patch.dict(os.environ, {"ALLES_HOST": "0.0.0.0"}, clear=True):
            with self.assertRaisesRegex(AccessConfigError, "ALLES_ACCESS_PROFILE"):
                bind_host()

    def test_lan_profile_requires_enabled_owner_password(self):
        base = {"ALLES_ACCESS_PROFILE": "lan"}
        with mock.patch.dict(os.environ, base, clear=True):
            with self.assertRaisesRegex(AccessConfigError, "owner password"):
                bind_host()

        with mock.patch.dict(
            os.environ,
            {**base, "AUTH_ENABLED": "true", "AUTH_PASSWORD": "secret1"},
            clear=True,
        ):
            self.assertEqual(bind_host(), "0.0.0.0")

    def test_lan_profile_honors_an_explicit_host(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_ACCESS_PROFILE": "lan",
                "ALLES_HOST": "192.168.1.20",
                "AUTH_ENABLED": "true",
                "AUTH_PASSWORD": "secret1",
            },
            clear=True,
        ):
            self.assertEqual(bind_host(), "192.168.1.20")

    def test_lan_profile_accepts_an_enabled_saved_password(self):
        with (
            mock.patch.dict(
                os.environ, {"ALLES_ACCESS_PROFILE": "lan"}, clear=True
            ),
            mock.patch(
                "core.server_config.load_settings",
                return_value={"auth_enabled": True, "auth_password_hash": "saved-hash"},
            ),
            mock.patch("core.server_config.auth_enabled", return_value=True),
        ):
            self.assertEqual(bind_host(), "0.0.0.0")

    def test_disabled_auth_env_overrides_a_saved_password(self):
        with (
            mock.patch.dict(
                os.environ,
                {"ALLES_ACCESS_PROFILE": "lan", "AUTH_ENABLED": "false"},
                clear=True,
            ),
            mock.patch(
                "core.server_config.load_settings",
                return_value={"auth_enabled": True, "auth_password_hash": "saved-hash"},
            ),
        ):
            with self.assertRaisesRegex(AccessConfigError, "owner password"):
                bind_host()

    def test_public_profile_requires_every_public_safety_setting(self):
        complete = {
            "ALLES_ACCESS_PROFILE": "public",
            "AUTH_ENABLED": "true",
            "AUTH_PASSWORD": "secret1",
            "BASE_DOMAIN": "alles.example",
            "ALLES_PUBLIC_URL": "https://alles.example",
            "ALLES_TRUSTED_HOSTS": "alles.example,*.alles.example",
            "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1,10.0.0.0/8",
        }
        for missing in (
            "ALLES_PUBLIC_URL",
            "ALLES_TRUSTED_HOSTS",
            "ALLES_FORWARDED_ALLOW_IPS",
        ):
            env = {key: value for key, value in complete.items() if key != missing}
            with self.subTest(missing=missing), mock.patch.dict(
                os.environ, env, clear=True
            ):
                with self.assertRaisesRegex(AccessConfigError, missing):
                    bind_host()

    def test_public_profile_accepts_complete_safe_configuration(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_ACCESS_PROFILE": "public",
                "AUTH_ENABLED": "true",
                "AUTH_PASSWORD": "secret1",
                "BASE_DOMAIN": "alles.example",
                "ALLES_PUBLIC_URL": "https://ALLES.example",
                "ALLES_TRUSTED_HOSTS": "alles.example,*.alles.example",
                "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1,10.0.0.0/8",
            },
            clear=True,
        ):
            self.assertEqual(bind_host(), "0.0.0.0")
            self.assertEqual(public_origin(), "https://alles.example")
            self.assertEqual(trusted_hosts(), ("alles.example", "*.alles.example"))
            self.assertEqual(forwarded_allow_ips(), ("127.0.0.1", "10.0.0.0/8"))

    def test_public_profile_rejects_http_url(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_ACCESS_PROFILE": "public",
                "AUTH_ENABLED": "true",
                "AUTH_PASSWORD": "secret1",
                "BASE_DOMAIN": "alles.example",
                "ALLES_PUBLIC_URL": "http://alles.example",
                "ALLES_TRUSTED_HOSTS": "alles.example",
                "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(AccessConfigError, "HTTPS"):
                bind_host()

    def test_public_url_host_must_be_trusted(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_ACCESS_PROFILE": "public",
                "AUTH_ENABLED": "true",
                "AUTH_PASSWORD": "secret1",
                "BASE_DOMAIN": "alles.example",
                "ALLES_PUBLIC_URL": "https://alles.example",
                "ALLES_TRUSTED_HOSTS": "other.example",
                "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(AccessConfigError, "public URL host"):
                bind_host()

    def test_public_profile_requires_matching_base_domain_and_subdomains(self):
        base = {
            "ALLES_ACCESS_PROFILE": "public",
            "AUTH_ENABLED": "true",
            "AUTH_PASSWORD": "secret1",
            "ALLES_PUBLIC_URL": "https://alles.example",
            "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1",
        }
        cases = (
            ({**base, "ALLES_TRUSTED_HOSTS": "alles.example"}, "BASE_DOMAIN"),
            (
                {
                    **base,
                    "BASE_DOMAIN": "other.example",
                    "ALLES_TRUSTED_HOSTS": "alles.example,*.alles.example",
                },
                "must match",
            ),
            (
                {
                    **base,
                    "BASE_DOMAIN": "alles.example",
                    "ALLES_TRUSTED_HOSTS": "alles.example",
                },
                "subdomain",
            ),
        )
        for env, message in cases:
            with self.subTest(message=message), mock.patch.dict(
                os.environ, env, clear=True
            ):
                with self.assertRaisesRegex(AccessConfigError, message):
                    bind_host()

    def test_trusted_hosts_rejects_broad_or_malformed_entries(self):
        for value in ("*", "https://alles.example", "alles.example:443", "bad/host"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"ALLES_TRUSTED_HOSTS": value}, clear=True
            ):
                with self.assertRaisesRegex(AccessConfigError, "trusted host"):
                    trusted_hosts()

    def test_forwarded_proxy_addresses_reject_wildcards_and_everywhere_cidrs(self):
        for value in ("*", "0.0.0.0/0", "::/0", "not-an-ip"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"ALLES_FORWARDED_ALLOW_IPS": value}, clear=True
            ):
                with self.assertRaisesRegex(AccessConfigError, "forwarded proxy"):
                    forwarded_allow_ips()

    def test_device_profile_has_narrow_default_trusted_hosts(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            hosts = trusted_hosts()
            self.assertIn("localhost", hosts)
            self.assertIn("*.localhost", hosts)
            self.assertIn("testserver", hosts)
            self.assertNotIn("*", hosts)

    def test_unknown_profile_is_rejected(self):
        with mock.patch.dict(
            os.environ, {"ALLES_ACCESS_PROFILE": "internet"}, clear=True
        ):
            with self.assertRaisesRegex(AccessConfigError, "unknown access profile"):
                bind_host()

    def test_container_runtime_allows_its_internal_bind(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_RUNTIME": "container",
                "ALLES_ACCESS_PROFILE": "device",
                "ALLES_HOST": "0.0.0.0",
            },
            clear=True,
        ):
            self.assertEqual(bind_host(), "0.0.0.0")

    def test_container_runtime_does_not_bypass_public_guard(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_RUNTIME": "container",
                "ALLES_ACCESS_PROFILE": "public",
                "ALLES_HOST": "0.0.0.0",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(AccessConfigError, "owner password"):
                bind_host()

    def test_blank_host_falls_back_to_loopback(self):
        with mock.patch.dict(os.environ, {"ALLES_HOST": "   "}, clear=True):
            self.assertEqual(bind_host(), "127.0.0.1")


class CorsConfigTest(unittest.TestCase):
    def test_cross_origin_access_is_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cors_origins(), ())

    def test_configured_origins_are_normalized_and_deduplicated(self):
        with mock.patch.dict(
            os.environ,
            {
                "ALLES_CORS_ORIGINS": (
                    "https://ALLES.example, http://localhost:8000,"
                    "https://alles.example"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                cors_origins(),
                ("https://alles.example", "http://localhost:8000"),
            )

    def test_wildcard_origin_is_rejected(self):
        with mock.patch.dict(
            os.environ, {"ALLES_CORS_ORIGINS": "*"}, clear=True
        ):
            with self.assertRaisesRegex(AccessConfigError, "wildcard"):
                cors_origins()

    def test_origins_cannot_include_credentials_paths_or_queries(self):
        invalid = (
            "https://user:pass@alles.example",
            "https://alles.example/api",
            "https://alles.example?token=x",
            "file:///tmp/alles",
        )
        for origin in invalid:
            with self.subTest(origin=origin), mock.patch.dict(
                os.environ, {"ALLES_CORS_ORIGINS": origin}, clear=True
            ):
                with self.assertRaisesRegex(AccessConfigError, "origin"):
                    cors_origins()

    def test_blank_origin_entry_is_rejected(self):
        with mock.patch.dict(
            os.environ,
            {"ALLES_CORS_ORIGINS": "https://alles.example, ,http://localhost:8000"},
            clear=True,
        ):
            with self.assertRaisesRegex(AccessConfigError, "blank"):
                cors_origins()


if __name__ == "__main__":
    unittest.main()
