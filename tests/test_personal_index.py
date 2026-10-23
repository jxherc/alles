import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import services.personal_index as pixmod
from core.database import (
    Base,
    Book,
    CachedMessage,
    Contact,
    ContactField,
    IndexChunk,
    JournalEntry,
    ReadItem,
)
from services import personal_index as pix


class PersonalIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault_root = Path(self.tmp.name)
        self.vault_patch = mock.patch("services.vault_md.vault_dir", return_value=self.vault_root)
        self.vault_patch.start()
        self.eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.eng)
        self.db = sessionmaker(bind=self.eng)()

    def tearDown(self):
        self.db.close()
        self.eng.dispose()
        self.vault_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def _vault():
        from services import notes_vault

        return notes_vault

    def test_note_indexed_and_searchable(self):
        note = self._vault().create(
            title="apartment hunt",
            content="viewed a 2br near the park",
            tags=["home"],
        )
        self.assertGreater(pix.index_record(self.db, "note", note["id"]), 0)
        hits = pix.search(self.db, "apartment park", k=5)
        self.assertTrue(any(hit["ref"] == note["id"] and hit["kind"] == "note" for hit in hits))
        self.assertEqual(hits[0]["label"], "apartment hunt")
        self.assertEqual(hits[0]["link"], "/?app=notes#apartment hunt")

    def test_remove_record(self):
        note = self._vault().create(title="temp", content="throwaway")
        pix.index_record(self.db, "note", note["id"])
        self.assertGreaterEqual(pix.remove_record(self.db, "note", note["id"]), 1)
        self.assertFalse(pix.search(self.db, "throwaway", k=5))

    def test_journal_contact_read_book(self):
        self.db.add(
            JournalEntry(
                id="j1",
                date="2026-03-04",
                content="felt good about the move",
                mood="happy",
            )
        )
        self.db.add(Contact(id="c1", name="Sam Rivera", company="Acme", notes="met at the trip"))
        self.db.add(
            ContactField(
                id="cf1",
                contact_id="c1",
                kind="email",
                label="work",
                value="sam@acme.com",
            )
        )
        self.db.add(
            ReadItem(
                id="r1",
                url="http://x",
                title="rust tips",
                text="ownership and borrowing",
            )
        )
        self.db.add(Book(id="b1", title="Dune", author="Herbert", notes="reread the desert parts"))
        self.db.commit()
        with mock.patch.object(pixmod, "_journal_locked", return_value=False):
            for kind, ref, model, query, expected in [
                ("journal", "2026-03-04", JournalEntry, "felt good move", "journal 2026-03-04"),
                ("contact", "c1", Contact, "sam acme trip", "Sam Rivera"),
                ("read", "r1", ReadItem, "ownership borrowing", "rust tips"),
                ("book", "b1", Book, "desert reread", "Dune"),
            ]:
                obj = (
                    self.db.query(model).filter_by(id=ref).first()
                    if kind != "journal"
                    else self.db.query(JournalEntry).filter_by(date=ref).first()
                )
                self.assertGreater(pix.index_record(self.db, kind, obj), 0)
                hits = pix.search(self.db, query, kinds=[kind], k=5)
                self.assertTrue(hits)
                self.assertEqual(hits[0]["label"], expected)
        self.assertTrue(
            any(
                hit["ref"] == "c1"
                for hit in pix.search(self.db, "sam@acme.com", kinds=["contact"], k=5)
            )
        )

    def test_journal_lock_blocks_and_drops(self):
        entry = JournalEntry(id="j9", date="2026-01-01", content="secret thoughts")
        self.db.add(entry)
        self.db.commit()
        with mock.patch.object(pixmod, "_journal_locked", return_value=False):
            pix.index_record(self.db, "journal", entry)
        self.assertTrue(pix.search(self.db, "secret thoughts", kinds=["journal"], k=5))
        with mock.patch.object(pixmod, "_journal_locked", return_value=True):
            pix.index_record(self.db, "journal", entry)
        self.assertFalse(pix.search(self.db, "secret thoughts", kinds=["journal"], k=5))

    def test_disabled_source_not_indexed(self):
        note = self._vault().create(title="hidden", content="should not index")
        with mock.patch.object(pixmod, "_source_enabled", side_effect=lambda kind: kind != "note"):
            self.assertEqual(pix.index_record(self.db, "note", note["id"]), 0)
        self.assertFalse(pix.search(self.db, "hidden", kinds=["note"], k=5))

    def test_no_vault_adapter(self):
        self.assertNotIn("vault", pix._ADAPTERS)
        self.assertNotIn("vault", pix.PERSONAL_KINDS)
        self.assertEqual(pix.index_record(self.db, "vault", object()), 0)

    def test_mail_subject_indexed_and_body_batch(self):
        message = CachedMessage(
            id="m1",
            account_id="acc",
            uid="42",
            sender="sam@acme.com",
            subject="trip plans",
        )
        self.db.add(message)
        self.db.commit()
        pix.index_record(self.db, "mail", message)
        self.assertTrue(pix.search(self.db, "trip plans sam", kinds=["mail"], k=5))
        with mock.patch.object(
            pix,
            "_fetch_mail_body",
            return_value="we leave friday from the north station",
        ):
            self.assertEqual(pix._index_mail_batch(self.db, limit=10), 1)
        self.assertTrue(self.db.query(CachedMessage).filter_by(id="m1").first().body_indexed)
        self.assertTrue(pix.search(self.db, "north station friday", kinds=["mail"], k=5))

    def test_backfill_and_reconcile_orphans(self):
        vault = self._vault()
        vault.create(title="alpha note", content="keep me")
        removed = vault.create(title="beta note", content="delete me")
        self.assertGreater(pix.reindex_source(self.db, "note"), 0)
        vault.delete(removed["id"])
        result = pix.reconcile(self.db)
        self.assertGreaterEqual(result["orphans"], 1)
        refs = {chunk.ref for chunk in self.db.query(IndexChunk).filter_by(kind="note").all()}
        self.assertNotIn("beta note", refs)
        self.assertIn("alpha note", refs)

    def test_mail_failed_fetch_retryable(self):
        message = CachedMessage(
            id="m2",
            account_id="acc",
            uid="99",
            sender="x@y.com",
            subject="retryable subject",
        )
        self.db.add(message)
        self.db.commit()
        with mock.patch.object(pix, "_fetch_mail_body", return_value=""):
            self.assertEqual(pix._index_mail_batch(self.db, limit=10), 0)
        self.assertFalse(self.db.query(CachedMessage).filter_by(id="m2").first().body_indexed)
        self.assertTrue(pix.search(self.db, "retryable", kinds=["mail"], k=5))

    def test_stats_and_clear(self):
        self._vault().create(title="x", content="hello world")
        pix.reindex_source(self.db, "note")
        self.assertGreaterEqual(pix.stats(self.db)["by_kind"].get("note", 0), 1)
        self.assertGreaterEqual(pix.clear(self.db), 1)
        self.assertEqual(pix.stats(self.db)["by_kind"].get("note", 0), 0)


if __name__ == "__main__":
    unittest.main()
