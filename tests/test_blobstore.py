"""stage 0d - unified blob/attachment store. tests first (RED)."""

import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ["AUTH_ENABLED"] = "false"
import core.database as db


class BlobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_data = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self.tmp  # blobs write under <tmp>/.blobs
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        from services import blobstore

        self.bs = blobstore

    def tearDown(self):
        self.s.close()
        db.SessionLocal.configure(bind=self._orig)
        db.engine = self._orig
        self.eng.dispose()
        if self._orig_data is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._orig_data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_put_stores_and_read_roundtrips(self):
        b = self.bs.put(self.s, b"hello world", mime="text/plain")
        self.assertEqual(b.size, 11)
        self.assertEqual(b.mime, "text/plain")
        self.assertEqual(self.bs.read(b), b"hello world")

    def test_put_dedups_identical_bytes(self):
        b1 = self.bs.put(self.s, b"same")
        b2 = self.bs.put(self.s, b"same")
        self.assertEqual(b1.id, b2.id)  # one Blob row
        self.assertEqual(self.s.query(db.Blob).count(), 1)

    def test_put_distinct_bytes_two_blobs(self):
        self.bs.put(self.s, b"a")
        self.bs.put(self.s, b"b")
        self.assertEqual(self.s.query(db.Blob).count(), 2)

    def test_path_is_sharded(self):
        b = self.bs.put(self.s, b"shardme")
        p = self.bs.path_for(b)
        self.assertTrue(p.exists())
        self.assertEqual(p.name, b.sha256)
        self.assertEqual(p.parent.name, b.sha256[:2])

    def test_attach_increments_refcount(self):
        b = self.bs.put(self.s, b"x")
        a = self.bs.attach(self.s, b, "upload", "u1")
        self.assertEqual(b.refcount, 1)
        self.assertEqual(a.resource_kind, "upload")
        self.assertEqual(a.resource_id, "u1")
        self.assertEqual(a.blob_id, b.id)

    def test_detach_decrements_refcount(self):
        b = self.bs.put(self.s, b"x")
        a = self.bs.attach(self.s, b, "upload", "u1")
        self.bs.detach(self.s, a)
        self.assertEqual(self.s.get(db.Blob, b.id).refcount, 0)
        self.assertIsNone(self.s.get(db.Attachment, a.id))

    def test_dedup_across_kinds_shares_one_blob(self):
        b1 = self.bs.put(self.s, b"receipt-bytes")
        self.bs.attach(self.s, b1, "upload", "u1")
        b2 = self.bs.put(self.s, b"receipt-bytes")  # same bytes, different consumer
        self.bs.attach(self.s, b2, "vault", "v1")
        self.assertEqual(b1.id, b2.id)
        self.assertEqual(self.s.get(db.Blob, b1.id).refcount, 2)
        self.assertEqual(self.s.query(db.Blob).count(), 1)

    def test_gc_purges_orphans_keeps_referenced(self):
        orphan = self.bs.put(self.s, b"orphan")
        kept = self.bs.put(self.s, b"kept")
        self.bs.attach(self.s, kept, "upload", "u1")
        orphan_path = self.bs.path_for(orphan)
        self.assertTrue(orphan_path.exists())
        purged = self.bs.gc(self.s)
        self.assertEqual(purged, 1)
        self.assertIsNone(self.s.get(db.Blob, orphan.id))  # orphan row gone
        self.assertFalse(orphan_path.exists())  # orphan file gone
        self.assertIsNotNone(self.s.get(db.Blob, kept.id))  # referenced kept

    def test_gc_keeps_referenced_blob(self):
        b = self.bs.put(self.s, b"ref")
        self.bs.attach(self.s, b, "upload", "u1")
        self.assertEqual(self.bs.gc(self.s), 0)
        self.assertIsNotNone(self.s.get(db.Blob, b.id))

    def test_put_does_not_auto_attach(self):
        b = self.bs.put(self.s, b"x")
        self.assertEqual(b.refcount, 0)  # put alone never references; attach does


if __name__ == "__main__":
    unittest.main()
