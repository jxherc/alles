"""opt-in journal → Obsidian daily-note mirror (services/journal_vault + routes wiring)."""

import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from services import journal_vault, vault_md
from tests._client import VaultApiTest


class JournalVaultTests(VaultApiTest):
    def setUp(self):
        super().setUp()
        # isolate settings.json so the mirror toggle / passcode don't touch the real one
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self.sp.start()
        import routes.journal as j

        j._unlock_tokens.clear()

    def tearDown(self):
        self.sp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mirror_on(self):
        self.client.patch("/api/settings", json={"journal_mirror_vault": True})

    def _file(self, day):
        return vault_md.vault_dir() / "Journal" / f"{day}.md"

    # ── off by default ────────────────────────────────────────────────────────
    def test_off_by_default_writes_no_file(self):
        self.client.put("/api/journal/2026-06-29", json={"content": "hi", "mood": "🙂"})
        self.assertFalse(self._file("2026-06-29").exists())

    # ── on → mirror written with frontmatter ───────────────────────────────────
    def test_upsert_mirrors_with_frontmatter(self):
        self._mirror_on()
        self.client.put(
            "/api/journal/2026-06-29",
            json={"content": "today was good", "mood": "🙂", "tags": "work, calm"},
        )
        f = self._file("2026-06-29")
        self.assertTrue(f.exists())
        txt = f.read_text("utf-8")
        self.assertIn("mood: 🙂", txt)
        self.assertIn("tags: work, calm", txt)
        self.assertIn("today was good", txt)

    def test_toggle_on_backfills_existing(self):
        # entry written while off, then the mirror is turned on → it gets backfilled
        self.client.put("/api/journal/2026-06-01", json={"content": "earlier"})
        self.assertFalse(self._file("2026-06-01").exists())
        self._mirror_on()
        self.assertTrue(self._file("2026-06-01").exists())

    def test_delete_removes_mirror(self):
        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "x"})
        self.assertTrue(self._file("2026-06-29").exists())
        self.client.delete("/api/journal/2026-06-29")
        self.assertFalse(self._file("2026-06-29").exists())

    # ── two-way: an Obsidian edit folds back into the DB ───────────────────────
    def test_sync_from_vault_updates_db(self):
        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "orig", "mood": "🙂"})
        # simulate an external edit in Obsidian
        self._file("2026-06-29").write_text("---\nmood: 😴\ntags: tired\n---\n\nedited in obsidian\n", "utf-8")
        db = self.db()
        try:
            journal_vault.sync_from_vault(db, "2026-06-29")
        finally:
            db.close()
        got = self.client.get("/api/journal/2026-06-29").json()
        self.assertEqual(got["content"], "edited in obsidian")
        self.assertEqual(got["mood"], "😴")
        self.assertEqual(got["tags"], "tired")

    def test_sync_creates_new_entry_from_new_file(self):
        self._mirror_on()
        (vault_md.vault_dir() / "Journal").mkdir(parents=True, exist_ok=True)
        self._file("2026-05-15").write_text("a brand new day\n", "utf-8")
        db = self.db()
        try:
            journal_vault.sync_from_vault(db, "2026-05-15")
        finally:
            db.close()
        got = self.client.get("/api/journal/2026-05-15").json()
        self.assertTrue(got["exists"])
        self.assertEqual(got["content"], "a brand new day")

    # ── lock interplay ─────────────────────────────────────────────────────────
    def test_passcode_pauses_and_purges(self):
        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "secret"})
        self.assertTrue(self._file("2026-06-29").exists())
        self.client.post("/api/journal/lock/set", json={"passcode": "1234"})
        self.assertFalse(journal_vault.enabled())  # paused while locked
        self.assertFalse(self._file("2026-06-29").exists())  # plaintext mirror removed

    def test_toggle_off_purges(self):
        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "x"})
        self.assertTrue(self._file("2026-06-29").exists())
        self.client.patch("/api/settings", json={"journal_mirror_vault": False})
        self.assertFalse(self._file("2026-06-29").exists())

    def test_is_daily_only_matches_dated_md(self):
        self.assertEqual(journal_vault.is_daily("Journal/2026-06-29.md"), "2026-06-29")
        self.assertIsNone(journal_vault.is_daily("Journal/notes.md"))
        self.assertIsNone(journal_vault.is_daily("Notes/2026-06-29.md"))
        self.assertIsNone(journal_vault.is_daily("Journal/sub/2026-06-29.md"))

    # ── regressions (found in QA) ───────────────────────────────────────────────
    def test_journal_not_collected_as_doc(self):
        # privacy: diary daily notes must never enter the ungated "doc" index
        from routes.textindex import _collect_docs

        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "DIARYSECRET here"})
        rels = [r for r, _ in _collect_docs()]
        self.assertNotIn("Journal/2026-06-29.md", rels)

    def test_journal_secret_not_in_doc_search(self):
        from services import textindex

        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "DIARYSECRET here"})
        self.client.post("/api/index/reindex")  # full doc reindex
        db = self.db()
        try:
            hits = textindex.search(db, "DIARYSECRET", kind="doc", k=5)
        finally:
            db.close()
        self.assertEqual(hits, [])

    def test_purge_clears_stale_doc_chunks(self):
        # if a diary ever leaked into "doc", locking must clear it too
        from services import textindex

        self._mirror_on()
        db = self.db()
        try:
            textindex.index(db, "doc", "Journal/2026-06-29.md", "LEAKEDSECRET")
        finally:
            db.close()
        self.client.put("/api/journal/2026-06-29", json={"content": "x"})
        self.client.post("/api/journal/lock/set", json={"passcode": "1234"})  # purges
        db = self.db()
        try:
            hits = textindex.search(db, "LEAKEDSECRET", kind="doc", k=5)
        finally:
            db.close()
        self.assertEqual(hits, [])

    def test_content_with_leading_frontmatter_roundtrips(self):
        self._mirror_on()
        body = "---\nfoo: bar\n---\n\nthe real body"
        self.client.put("/api/journal/2026-06-29", json={"content": body})
        got = journal_vault.read_entry("2026-06-29")
        self.assertEqual(got["content"], body)  # leading --- block survives, not eaten as FM

    def test_whitespace_content_does_not_churn(self):
        from core.database import JournalEntry

        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "hello\n\n"})
        db = self.db()
        try:
            journal_vault.sync_from_vault(db, "2026-06-29")  # the watcher echo
            e = db.query(JournalEntry).filter_by(date="2026-06-29").first()
            self.assertEqual(e.content, "hello\n\n")  # not silently stripped on echo
        finally:
            db.close()

    def test_lock_disable_rebuilds_mirror(self):
        self._mirror_on()
        self.client.put("/api/journal/2026-06-29", json={"content": "x"})
        self.client.post("/api/journal/lock/set", json={"passcode": "1234"})
        self.assertFalse(self._file("2026-06-29").exists())
        self.client.post("/api/journal/lock/disable", json={"passcode": "1234"})
        self.assertTrue(self._file("2026-06-29").exists())
