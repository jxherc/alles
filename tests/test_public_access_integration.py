import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


class PublicAccessIntegrationTest(unittest.TestCase):
    def test_public_app_enforces_https_host_and_origin_policy(self):
        script = textwrap.dedent(
            """
            from fastapi.testclient import TestClient
            from app import app

            secure = TestClient(app, base_url="https://alles.example")
            assert secure.get("/health").status_code == 200

            bad_host = secure.get("/health", headers={"Host": "evil.example"})
            assert bad_host.status_code == 400

            unknown = secure.get("/health", headers={"Origin": "https://evil.example"})
            assert "access-control-allow-origin" not in unknown.headers

            allowed = secure.get("/health", headers={"Origin": "https://console.example"})
            assert allowed.headers["access-control-allow-origin"] == "https://console.example"

            cleartext = TestClient(app, base_url="http://alles.example").get("/api/auth/me")
            assert cleartext.status_code == 400
            assert cleartext.json()["detail"] == "HTTPS required for public access"
            """
        )
        with tempfile.TemporaryDirectory() as data_dir:
            env = {
                **os.environ,
                "ALLES_DATA": data_dir,
                "ALLES_ACCESS_PROFILE": "public",
                "ALLES_HOST": "0.0.0.0",
                "AUTH_ENABLED": "true",
                "AUTH_PASSWORD": "secret1",
                "BASE_DOMAIN": "alles.example",
                "ALLES_PUBLIC_URL": "https://alles.example",
                "ALLES_TRUSTED_HOSTS": "alles.example,*.alles.example",
                "ALLES_FORWARDED_ALLOW_IPS": "127.0.0.1",
                "ALLES_CORS_ORIGINS": "https://console.example",
            }
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
