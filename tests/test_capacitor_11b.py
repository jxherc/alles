"""11b-4 — optional Capacitor wrapper. No native toolchain runs in this no-build repo, so
the wrapper is a real, documented scaffold under mobile/: a Capacitor config whose server.url
points at the alles host (the native shell just loads the live PWA), a package.json with the
capacitor deps + add-platform scripts, a README with the build steps, and a www/ splash. These
tests validate the scaffold's shape — same "honest seam" approach as the macOS bridge (11a).
"""

import json
import unittest
from pathlib import Path

MOBILE = Path(__file__).resolve().parent.parent / "mobile"


class CapacitorTests(unittest.TestCase):
    def test_mobile_dir_exists(self):
        self.assertTrue(MOBILE.is_dir())

    def test_config_valid_json(self):
        cfg = json.loads((MOBILE / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertIsInstance(cfg, dict)

    def test_config_app_id_and_name(self):
        cfg = json.loads((MOBILE / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg.get("appId"))
        self.assertTrue(cfg.get("appName"))
        self.assertIn(".", cfg["appId"])  # reverse-dns style

    def test_config_server_url_configurable(self):
        # the shell loads the live alles PWA — server.url must be present so the deployer points it home
        cfg = json.loads((MOBILE / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertIn("server", cfg)
        self.assertTrue(cfg["server"].get("url"))

    def test_config_webdir(self):
        cfg = json.loads((MOBILE / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg.get("webDir"))

    def test_package_json_valid(self):
        pkg = json.loads((MOBILE / "package.json").read_text(encoding="utf-8"))
        self.assertTrue(pkg.get("name"))

    def test_package_has_capacitor_deps(self):
        pkg = json.loads((MOBILE / "package.json").read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        self.assertTrue(any("@capacitor/core" == k for k in deps), "missing @capacitor/core")
        self.assertTrue(any(k.startswith("@capacitor/cli") for k in deps), "missing @capacitor/cli")

    def test_package_has_platform_scripts(self):
        pkg = json.loads((MOBILE / "package.json").read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {})
        joined = " ".join(scripts.values()).lower()
        self.assertIn("ios", joined)
        self.assertIn("android", joined)

    def test_readme_mentions_build(self):
        readme = (MOBILE / "README.md").read_text(encoding="utf-8").lower()
        self.assertIn("capacitor", readme)
        self.assertTrue("npx cap add" in readme or "cap add" in readme)

    def test_www_index_present(self):
        idx = MOBILE / "www" / "index.html"
        self.assertTrue(idx.exists())
        self.assertTrue(idx.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
