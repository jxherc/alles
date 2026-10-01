import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import obsidian_setup


class ObsidianSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-obsidian-setup-")
        self.root = Path(self.tmp.name)
        self.vault = self.root / "Vault"
        self.vault.mkdir()
        self.source = self.root / "plugin-source"
        self.source.mkdir()
        (self.source / "manifest.json").write_text('{"id":"obsidian-alles"}', "utf-8")
        (self.source / "main.js").write_text("old source", "utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_install_writes_owned_companion_only(self):
        result = obsidian_setup.install_companion(self.vault, source=self.source)
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        self.assertTrue(result["installed"])
        self.assertEqual((target / "main.js").read_text("utf-8"), "old source")
        marker = json.loads((target / ".alles-owned-plugin.json").read_text("utf-8"))
        self.assertEqual(marker["version"], 1)
        self.assertEqual(set(marker["files"]), {"main.js", "manifest.json"})

    def test_connecting_vault_alone_never_creates_obsidian_files(self):
        status = obsidian_setup.status(self.vault, detector=lambda: None)
        self.assertFalse(status["obsidian_detected"])
        self.assertFalse(status["companion_installed"])
        self.assertFalse((self.vault / ".obsidian").exists())

    def test_unowned_existing_plugin_is_refused_without_changes(self):
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        target.mkdir(parents=True)
        custom = target / "main.js"
        custom.write_text("owner plugin", "utf-8")
        with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "not owned"):
            obsidian_setup.install_companion(self.vault, source=self.source)
        self.assertEqual(custom.read_text("utf-8"), "owner plugin")

    def test_non_object_ownership_marker_is_reported_as_invalid(self):
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        target.mkdir(parents=True)
        (target / ".alles-owned-plugin.json").write_text("null", "utf-8")

        state = obsidian_setup.status(self.vault, detector=lambda: None)
        self.assertEqual(state["companion_integrity"], "unowned-or-changed")
        with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "ownership is invalid"):
            obsidian_setup.install_companion(self.vault, source=self.source)

    def test_owned_companion_updates_only_after_integrity_check(self):
        obsidian_setup.install_companion(self.vault, source=self.source)
        (self.source / "main.js").write_text("new source", "utf-8")
        obsidian_setup.install_companion(self.vault, source=self.source)
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        self.assertEqual((target / "main.js").read_text("utf-8"), "new source")

        (target / "main.js").write_text("owner edit", "utf-8")
        with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "changed"):
            obsidian_setup.install_companion(self.vault, source=self.source)
        self.assertEqual((target / "main.js").read_text("utf-8"), "owner edit")

    def test_nested_marker_named_file_is_treated_as_unowned_content(self):
        obsidian_setup.install_companion(self.vault, source=self.source)
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        nested = target / "notes" / ".alles-owned-plugin.json"
        nested.parent.mkdir()
        nested.write_text("owner content", "utf-8")

        with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "changed"):
            obsidian_setup.install_companion(self.vault, source=self.source)

        self.assertEqual(nested.read_text("utf-8"), "owner content")

    def test_failed_update_preserves_the_verified_previous_copy(self):
        obsidian_setup.install_companion(self.vault, source=self.source)
        (self.source / "main.js").write_text("new source", "utf-8")
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        original_replace = os.replace

        def race(source, destination):
            if Path(source).name.endswith(".staging"):
                Path(destination).mkdir()
                (Path(destination) / "intruder.txt").write_text("race", "utf-8")
                raise OSError("simulated competing install")
            return original_replace(source, destination)

        with mock.patch.object(obsidian_setup.os, "replace", side_effect=race):
            with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "safely"):
                obsidian_setup.install_companion(self.vault, source=self.source)

        backups = list(target.parent.glob(".obsidian-alles.*.previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "main.js").read_text("utf-8"), "old source")

    def test_post_swap_verification_failure_restores_previous_companion(self):
        obsidian_setup.install_companion(self.vault, source=self.source)
        (self.source / "main.js").write_text("new source", "utf-8")
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        original_read_marker = obsidian_setup._read_marker
        checked = 0

        def fail_post_swap(path):
            nonlocal checked
            checked += 1
            if checked == 2:
                raise obsidian_setup.ObsidianSetupError("simulated verification failure")
            return original_read_marker(path)

        with mock.patch.object(obsidian_setup, "_read_marker", side_effect=fail_post_swap):
            with self.assertRaisesRegex(
                obsidian_setup.ObsidianSetupError, "simulated verification failure"
            ):
                obsidian_setup.install_companion(self.vault, source=self.source)

        self.assertEqual((target / "main.js").read_text("utf-8"), "old source")
        self.assertFalse(list(target.parent.glob(".obsidian-alles.*.previous")))
        failed = list(target.parent.glob(".obsidian-alles.*.failed"))
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0] / "main.js").read_text("utf-8"), "new source")

    def test_failed_first_install_is_removed_from_the_active_plugin_path(self):
        target = self.vault / ".obsidian" / "plugins" / "obsidian-alles"
        with mock.patch.object(
            obsidian_setup,
            "_read_marker",
            side_effect=obsidian_setup.ObsidianSetupError("simulated verification failure"),
        ):
            with self.assertRaisesRegex(
                obsidian_setup.ObsidianSetupError, "simulated verification failure"
            ):
                obsidian_setup.install_companion(self.vault, source=self.source)

        self.assertFalse(target.exists())
        self.assertEqual(len(list(target.parent.glob(".obsidian-alles.*.failed"))), 1)

    def test_install_rejects_symlinked_obsidian_metadata_ancestor(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / ".obsidian").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(obsidian_setup.ObsidianSetupError, "unsafe"):
            obsidian_setup.install_companion(self.vault, source=self.source)

        self.assertFalse((outside / "plugins").exists())


if __name__ == "__main__":
    unittest.main()
