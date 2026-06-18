import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db_mod
from core.database import DocRevision
from services import vault_md
from routes import vault_md as vroute


class DocRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._vd = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._vd.start()
        eng = create_engine("sqlite:///:memory:")
        DocRevision.__table__.create(eng)
        # route handlers do `from core.database import SessionLocal` at call time,
        # so patching the attribute on the module is enough
        self._sl = mock.patch.object(db_mod, "SessionLocal", sessionmaker(bind=eng))
        self._sl.start()

    def tearDown(self):
        self._vd.stop()
        self._sl.stop()
        self.tmp.cleanup()

    def test_norm_path(self):
        self.assertEqual(vroute._norm_path("a"), "a.md")
        self.assertEqual(vroute._norm_path("a.md"), "a.md")
        self.assertEqual(vroute._norm_path("dir\\b"), "dir/b.md")

    def test_snapshot_dedup(self):
        vault_md.write("n.md", "same")
        vroute._snapshot("n.md", force=True)
        vroute._snapshot("n.md", force=True)  # identical on-disk content → skipped
        self.assertEqual(len(vroute.list_revisions("n.md")), 1)

    def test_snapshot_and_restore(self):
        vault_md.write("note.md", "v1")
        vroute._snapshot("note.md", force=True)  # captures v1
        vault_md.write("note.md", "v2")
        revs = vroute.list_revisions("note.md")
        self.assertEqual(len(revs), 1)
        self.assertEqual(revs[0]["size"], 2)  # "v1"
        out = vroute.restore_revision(revs[0]["id"])
        self.assertEqual(out["ok"], True)
        self.assertEqual(vault_md.read("note.md")["content"], "v1")
        # restoring force-snapshots the state being replaced (v2)
        self.assertEqual(len(vroute.list_revisions("note.md")), 2)

    def test_diff_against_current(self):
        vault_md.write("d.md", "line one\nline two\n")
        vroute._snapshot("d.md", force=True)
        rid = vroute.list_revisions("d.md")[0]["id"]
        vault_md.write("d.md", "line one\nline TWO\n")
        d = vroute.diff_revision("d.md", a=rid)["diff"]
        self.assertIn("-line two", d)
        self.assertIn("+line TWO", d)

    def test_diff_no_change_is_empty(self):
        vault_md.write("e.md", "unchanged\n")
        vroute._snapshot("e.md", force=True)
        rid = vroute.list_revisions("e.md")[0]["id"]
        self.assertEqual(vroute.diff_revision("e.md", a=rid)["diff"], "")


if __name__ == "__main__":
    unittest.main()
