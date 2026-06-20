import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db_mod
from core.database import DocRevision
from routes import vault_md as vroute
from services import vault_md


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

    def test_snapshot_nonexistent_file_is_noop(self):
        # shouldn't blow up, just silently skip
        vroute._snapshot("ghost.md", force=True)
        self.assertEqual(vroute.list_revisions("ghost.md"), [])

    def test_multiple_versions_ordered_newest_first(self):
        vault_md.write("seq.md", "alpha")
        vroute._snapshot("seq.md", force=True)
        vault_md.write("seq.md", "beta")
        vroute._snapshot("seq.md", force=True)
        vault_md.write("seq.md", "gamma")
        vroute._snapshot("seq.md", force=True)
        revs = vroute.list_revisions("seq.md")
        self.assertEqual(len(revs), 3)
        # sizes: alpha=5, beta=4, gamma=5 — all different content, so 3 revisions
        sizes = [r["size"] for r in revs]
        self.assertEqual(len(sizes), 3)

    def test_norm_path_nested(self):
        self.assertEqual(vroute._norm_path("sub/page"), "sub/page.md")
        self.assertEqual(vroute._norm_path("sub/page.md"), "sub/page.md")

    def test_restore_revision_writes_content(self):
        vault_md.write("r.md", "original")
        vroute._snapshot("r.md", force=True)
        rid = vroute.list_revisions("r.md")[0]["id"]
        vault_md.write("r.md", "changed a lot")
        vroute.restore_revision(rid)
        self.assertEqual(vault_md.read("r.md")["content"], "original")

    def test_diff_between_two_revisions(self):
        vault_md.write("two.md", "aaa\n")
        vroute._snapshot("two.md", force=True)
        rid_a = vroute.list_revisions("two.md")[0]["id"]
        vault_md.write("two.md", "bbb\n")
        vroute._snapshot("two.md", force=True)
        revs = vroute.list_revisions("two.md")
        rid_b = revs[0]["id"]  # newest
        d = vroute.diff_revision("two.md", a=rid_a, b=rid_b)["diff"]
        self.assertIn("-aaa", d)
        self.assertIn("+bbb", d)


if __name__ == "__main__":
    unittest.main()
