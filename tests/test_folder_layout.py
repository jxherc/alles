import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import folder_layout, native_install


class Crash(BaseException):
    """A process killed between two steps: nothing after it runs, not even except blocks."""


def _snapshot(base: Path) -> dict:
    out = {}
    for current, _dirs, files in os.walk(base):
        for name in files:
            path = Path(current) / name
            out[path.relative_to(base).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class FolderMoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-folders-")
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        self.layout = native_install.platform_layout("Linux", home=home.resolve())
        self.home = self.layout.home
        self.alles = self.home / "Alles"
        self.vault, self.files = self.alles / "Vault", self.alles / "Files"
        self.backups = self.alles / "Backups"
        for folder in (self.vault / "Daily", self.files / "School" / "cs", self.backups):
            folder.mkdir(parents=True)
        (self.alles / "Aide").mkdir()
        (self.vault / "Daily" / "2026-10-27.md").write_text("what i wrote", "utf-8")
        (self.vault / "todo.md").write_text("- [ ] cs worksheet", "utf-8")
        (self.files / "School" / "cs" / "module 5.pdf").write_bytes(os.urandom(4096))
        (self.files / "photo.jpg").write_bytes(os.urandom(2048))
        (self.files / ".alles-op.partial").write_bytes(b"half")
        (self.backups / "alles-auto-1.alles-backup").write_bytes(os.urandom(512))
        self.layout.data_root.mkdir(parents=True)
        self.settings_path = self.layout.data_root / "settings.json"
        self.settings_path.write_text(
            json.dumps(
                {
                    "vault_dir": str(self.vault),
                    "files_dir": str(self.files),
                    "automatic_backup_dir": str(self.backups),
                    "agent_allowed_roots": [str(self.files / "School"), "/srv/code"],
                    "username": "eric",
                }
            ),
            "utf-8",
        )
        with sqlite3.connect(self.layout.data_root / "aide.db") as db:
            db.execute("create table storage_locations (id text primary key, root_path text)")
            db.execute(
                "insert into storage_locations values ('default-local', ?)", (str(self.files),)
            )
            db.execute("insert into storage_locations values ('usb', '/media/usb')")
        self.before = {
            "files": _snapshot(self.files),
            "docs": _snapshot(self.vault),
            "backups": _snapshot(self.backups),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _settings(self) -> dict:
        return json.loads(self.settings_path.read_text("utf-8"))

    def _root_path(self) -> str:
        with sqlite3.connect(self.layout.data_root / "aide.db") as db:
            return db.execute(
                "select root_path from storage_locations where id='default-local'"
            ).fetchone()[0]

    def assert_one_folder(self):
        docs, hidden = self.alles / "Docs", self.layout.support_root / "backups"
        self.assertFalse(self.vault.exists())
        self.assertFalse(self.files.exists())
        self.assertFalse(self.backups.exists())
        self.assertEqual(_snapshot(docs), self.before["docs"])
        self.assertEqual(_snapshot(hidden), self.before["backups"])
        moved = {k: v for k, v in _snapshot(self.alles).items() if k.split("/")[0] not in {"Docs"}}
        self.assertEqual(moved, self.before["files"])
        self.assertTrue((self.alles / "Aide").is_dir())
        settings = self._settings()
        self.assertEqual(settings["files_dir"], str(self.alles))
        self.assertEqual(settings["vault_dir"], str(docs))
        self.assertEqual(settings["automatic_backup_dir"], str(hidden))
        self.assertEqual(settings["agent_allowed_roots"], [str(self.alles / "School"), "/srv/code"])
        self.assertEqual(settings["username"], "eric")
        self.assertEqual(self._root_path(), str(self.alles))
        self.assertEqual(folder_layout.plan(self.layout)["state"], "one-folder")

    def assert_as_before(self):
        self.assertFalse((self.alles / "Docs").exists())
        self.assertFalse((self.layout.support_root / "backups").exists())
        self.assertEqual(_snapshot(self.files), self.before["files"])
        self.assertEqual(_snapshot(self.vault), self.before["docs"])
        self.assertEqual(_snapshot(self.backups), self.before["backups"])
        settings = self._settings()
        self.assertEqual(settings["files_dir"], str(self.files))
        self.assertEqual(settings["vault_dir"], str(self.vault))
        self.assertEqual(settings["automatic_backup_dir"], str(self.backups))
        self.assertEqual(settings["agent_allowed_roots"], [str(self.files / "School"), "/srv/code"])
        self.assertEqual(self._root_path(), str(self.files))
        self.assertEqual(sorted(os.listdir(self.alles)), ["Aide", "Backups", "Files", "Vault"])

    def test_plan_is_read_only(self):
        found = folder_layout.plan(self.layout)
        self.assertEqual(found["state"], "move")
        self.assertEqual(found["renames"][0]["src"], str(self.backups))
        self.assertEqual(found["renames"][1]["dst"], str(self.alles / "Docs"))
        self.assert_as_before()
        ok, text = folder_layout.describe(self.layout)
        self.assertIsNone(ok)
        self.assertIn("alles folders move", text)

    def test_move_puts_everything_in_one_folder_and_keeps_every_byte(self):
        result = folder_layout.move(self.layout)
        self.assertEqual(result["state"], "done")
        self.assert_one_folder()
        self.assertEqual(folder_layout.describe(self.layout), (True, "one folder: ~/Alles"))
        # running it again changes nothing
        self.assertEqual(folder_layout.move(self.layout)["state"], "one-folder")
        self.assert_one_folder()

    def test_a_kill_after_any_step_is_finished_by_the_next_run(self):
        steps = []
        folder_layout.move(self.layout, step=steps.append)
        self.assertGreater(len(steps), 8)
        self.assertIn("rename 0", steps)
        self.assertEqual(steps[-1], "done")
        for stop in steps:
            with self.subTest(stop=stop):
                self.tearDown()
                self.setUp()

                def die(name, stop=stop):
                    if name == stop:
                        raise Crash(name)

                with self.assertRaises(Crash):
                    folder_layout.move(self.layout, step=die)
                if stop != "done":
                    self.assertEqual(folder_layout.describe(self.layout)[0], False)
                folder_layout.finish(self.layout)
                self.assert_one_folder()
                self.assertIsNone(folder_layout.finish(self.layout))

    def test_the_server_finishes_a_move_a_reboot_cut_short(self):
        def die(name):
            if name == "rename 3":
                raise Crash(name)

        with self.assertRaises(Crash):
            folder_layout.move(self.layout, step=die)
        env = {"ALLES_NATIVE_ROOT": str(self.layout.runtime_root)}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(native_install, "platform_layout", return_value=self.layout),
        ):
            # a recovery copy or another data folder never touches the owner's folders
            self.assertIsNone(folder_layout.resume_on_start(self.home / "elsewhere"))
            self.assertEqual(folder_layout.resume_on_start(self.layout.data_root), "done")
        self.assert_one_folder()

    def test_a_failed_step_puts_everything_back(self):
        real = os.rename
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 4:
                raise OSError(5, "input/output error")
            return real(src, dst)

        with mock.patch.object(folder_layout.os, "rename", side_effect=flaky):
            result = folder_layout.move(self.layout)
        self.assertEqual(result["state"], "rolled_back")
        self.assertIn("input/output error", result["why"])
        self.assert_as_before()

    def test_a_kill_while_putting_back_is_finished_too(self):
        real = os.rename
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 4:
                raise OSError(5, "input/output error")
            return real(src, dst)

        def die(name):
            if name == "back 1":
                raise Crash(name)

        with (
            mock.patch.object(folder_layout.os, "rename", side_effect=flaky),
            self.assertRaises(Crash),
        ):
            folder_layout.move(self.layout, step=die)
        self.assertEqual(folder_layout.finish(self.layout), "rolled_back")
        self.assert_as_before()
        # once put back, a later move starts over cleanly
        self.assertEqual(folder_layout.move(self.layout)["state"], "done")
        self.assert_one_folder()

    def test_a_bad_check_after_the_renames_puts_everything_back(self):
        real = folder_layout._inventory
        calls = []

        def wrong(base, names):
            calls.append(base)
            value = real(base, names)
            return {**value, "count": value["count"] + 1} if base == self.alles else value

        with mock.patch.object(folder_layout, "_inventory", side_effect=wrong):
            result = folder_layout.move(self.layout)
        self.assertEqual(result["state"], "rolled_back")
        self.assertIn("don't match", result["why"])
        self.assert_as_before()

    def test_clashes_custom_folders_and_other_disks_stay_as_they_are(self):
        (self.files / "Docs").mkdir()
        self.assertIn("already has Docs", folder_layout.plan(self.layout)["why"])
        (self.files / "Docs").rmdir()
        (self.alles / "Docs").mkdir()
        self.assertIn("already exists", folder_layout.plan(self.layout)["why"])
        (self.alles / "Docs").rmdir()
        with mock.patch.object(folder_layout, "_same_disk", return_value=False):
            found = folder_layout.plan(self.layout)
            self.assertEqual(
                found, {"state": "kept", "why": "the folders sit on more than one disk"}
            )
            self.assertEqual(folder_layout.move(self.layout)["state"], "kept")
        self.assertEqual(folder_layout.describe(self.layout)[0], None)
        settings = self._settings()
        settings["files_dir"] = str(self.home / "Dropbox")
        self.settings_path.write_text(json.dumps(settings), "utf-8")
        self.assertEqual(folder_layout.plan(self.layout)["state"], "kept")
        self.settings_path.write_text("{}", "utf-8")
        self.assertEqual(folder_layout.plan(self.layout)["state"], "inside-data")

    def test_finder_metadata_twice_is_dropped_not_a_clash(self):
        (self.alles / ".DS_Store").write_bytes(b"top")
        (self.files / ".DS_Store").write_bytes(b"inner")
        self.before["files"].pop(".DS_Store", None)
        self.assertEqual(folder_layout.move(self.layout)["state"], "done")
        self.assertEqual((self.alles / ".DS_Store").read_bytes(), b"top")
        self.assertFalse(self.files.exists())

    def test_backups_set_elsewhere_stay_there(self):
        settings = self._settings()
        settings["automatic_backup_dir"] = "/mnt/nas/alles"
        self.settings_path.write_text(json.dumps(settings), "utf-8")
        self.assertEqual(folder_layout.move(self.layout)["state"], "done")
        self.assertEqual(self._settings()["automatic_backup_dir"], "/mnt/nas/alles")
        self.assertTrue(self.backups.is_dir())  # not ours to move: it shows in files now

    def test_the_cli_stops_the_service_moves_and_starts_it_again(self):
        import cli

        calls = []
        with (
            mock.patch.object(cli, "_native_service_running", return_value=True),
            mock.patch.object(
                cli, "_native_stop_service", side_effect=lambda _l: calls.append("stop")
            ),
            mock.patch.object(
                cli,
                "_native_start_service_healthy",
                side_effect=lambda _l: calls.append("start") or True,
            ),
            mock.patch("sys.stdout"),
        ):
            self.assertTrue(cli._folders_move(self.layout))
            self.assertEqual(calls, ["stop", "start"])
            self.assert_one_folder()
            # nothing to do the second time: the service isn't touched
            self.assertTrue(cli._folders_move(self.layout, quiet_when_nothing=True))
            self.assertEqual(calls, ["stop", "start"])


if __name__ == "__main__":
    unittest.main()
