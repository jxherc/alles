from datetime import date

from core.database import Book
from routes.books import clamp_rating, parse_ol_doc, year_count
from tests._client import ApiTest


class BookLogicTests(ApiTest):
    def test_clamp_rating(self):
        self.assertEqual(clamp_rating(9), 5)
        self.assertEqual(clamp_rating(-3), 0)
        self.assertEqual(clamp_rating(3), 3)

    def test_year_count(self):
        books = [
            Book(title="a", status="done", finished="2026-01-02"),
            Book(title="b", status="done", finished="2026-11-30"),
            Book(title="c", status="done", finished="2025-06-01"),
            Book(title="d", status="reading", finished=""),
        ]
        self.assertEqual(year_count(books, 2026), 2)
        self.assertEqual(year_count(books, 2025), 1)

    def test_parse_ol_doc(self):
        doc = {
            "title": "Dune",
            "author_name": ["Frank Herbert", "x"],
            "cover_i": 12345,
            "isbn": ["9780441013593", "0441013597"],
            "first_publish_year": 1965,
        }
        out = parse_ol_doc(doc)
        self.assertEqual(out["title"], "Dune")
        self.assertEqual(out["author"], "Frank Herbert")
        self.assertIn("12345", out["cover"])
        self.assertEqual(out["isbn"], "9780441013593")
        self.assertEqual(out["year"], 1965)

    def test_parse_ol_doc_missing_fields(self):
        out = parse_ol_doc({"title": "No Cover"})
        self.assertEqual(out["title"], "No Cover")
        self.assertEqual(out["author"], "")
        self.assertEqual(out["cover"], "")


class BookApiTests(ApiTest):
    def _create(self, **kw):
        body = {"title": "Dune", "author": "Frank Herbert"}
        body.update(kw)
        return self.client.post("/api/books", json=body)

    def test_create_returns_id(self):
        r = self._create()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["id"])
        self.assertEqual(r.json()["status"], "want")

    def test_create_requires_title(self):
        self.assertEqual(self.client.post("/api/books", json={"title": " "}).status_code, 400)

    def test_create_rejects_bad_status(self):
        r = self._create(status="someday")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "status must be one of want, reading, done")

    def test_create_keeps_metadata_and_shelf_dates(self):
        r = self._create(
            title="  Dune  ",
            author="  Frank Herbert  ",
            status="reading",
            rating=9,
            cover="  https://example.com/cover.jpg  ",
            isbn="  123  ",
            notes="keep spacing",
            year=1965,
        )
        self.assertEqual(r.status_code, 200)
        book = r.json()
        self.assertEqual(book["title"], "Dune")
        self.assertEqual(book["author"], "Frank Herbert")
        self.assertEqual(book["rating"], 5)
        self.assertEqual(book["cover"], "https://example.com/cover.jpg")
        self.assertEqual(book["isbn"], "123")
        self.assertEqual(book["notes"], "keep spacing")
        self.assertEqual(book["year"], 1965)
        self.assertEqual(book["started"], date.today().isoformat())
        self.assertEqual(book["finished"], "")

    def test_overview_shelves(self):
        self._create(title="Want1", status="want")
        self._create(title="Reading1", status="reading")
        self._create(title="Done1", status="done", finished=date.today().isoformat())
        ov = self.client.get("/api/books/overview").json()
        self.assertIn("want", ov["shelves"])
        self.assertIn("reading", ov["shelves"])
        self.assertIn("done", ov["shelves"])
        titles = [b["title"] for b in ov["shelves"]["want"]]
        self.assertIn("Want1", titles)

    def test_overview_this_year_count(self):
        self._create(title="D", status="done", finished=date.today().isoformat())
        ov = self.client.get("/api/books/overview").json()
        self.assertGreaterEqual(ov["this_year"], 1)

    def test_patch_status_to_done_sets_finished(self):
        bid = self._create().json()["id"]
        r = self.client.patch(f"/api/books/{bid}", json={"status": "done"})
        self.assertEqual(r.json()["status"], "done")
        self.assertTrue(r.json()["finished"])  # auto-stamped

    def test_patch_rating_clamped(self):
        bid = self._create().json()["id"]
        r = self.client.patch(f"/api/books/{bid}", json={"rating": 99})
        self.assertEqual(r.json()["rating"], 5)

    def test_reread_clears_finished(self):
        # move a finished book back to "reading" — it shouldn't keep a finished date
        bid = self._create().json()["id"]
        self.client.patch(f"/api/books/{bid}", json={"status": "done"})
        r = self.client.patch(f"/api/books/{bid}", json={"status": "reading"})
        self.assertEqual(r.json()["status"], "reading")
        self.assertFalse(r.json()["finished"])  # cleared on the re-read

    def test_back_to_want_clears_dates(self):
        # "want to read" means not started — clear any started/finished
        bid = self._create().json()["id"]
        self.client.patch(f"/api/books/{bid}", json={"status": "done"})
        r = self.client.patch(f"/api/books/{bid}", json={"status": "want"})
        self.assertFalse(r.json()["finished"])
        self.assertFalse(r.json()["started"])

    def test_patch_notes(self):
        bid = self._create().json()["id"]
        r = self.client.patch(f"/api/books/{bid}", json={"notes": "great worldbuilding"})
        self.assertEqual(r.json()["notes"], "great worldbuilding")

    def test_restore_note_preserves_exact_text_and_unrelated_fields(self):
        bid = self._create(notes="new note", rating=4).json()["id"]
        previous = "  original 中文\nsecond line  "
        r = self.client.patch(
            f"/api/books/{bid}", json={"notes": previous, "expected_notes": "new note"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notes"], previous)
        self.assertEqual(r.json()["rating"], 4)

    def test_restore_refuses_newer_note_without_changing_other_fields(self):
        bid = self._create(notes="newer edit", rating=3).json()["id"]
        r = self.client.patch(
            f"/api/books/{bid}", json={"notes": "original", "expected_notes": "old edit"}
        )
        self.assertEqual(r.status_code, 409)
        book = self.client.get("/api/books/overview").json()["shelves"]["want"][0]
        self.assertEqual(book["notes"], "newer edit")
        self.assertEqual(book["rating"], 3)

    def test_restore_rating_accepts_zero_and_refuses_a_newer_rating(self):
        bid = self._create(rating=4, notes="keep note").json()["id"]
        body = {"rating": 0, "expected_rating": 4}
        r = self.client.patch(f"/api/books/{bid}", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rating"], 0)
        self.assertEqual(r.json()["notes"], "keep note")
        self.client.patch(f"/api/books/{bid}", json={"rating": 2})
        self.assertEqual(self.client.patch(f"/api/books/{bid}", json=body).status_code, 409)

    def test_restore_retry_after_lost_acknowledgment_is_idempotent(self):
        bid = self._create(notes="after", rating=5).json()["id"]
        for body in [
            {"notes": "", "expected_notes": "after"},
            {"rating": 0, "expected_rating": 5},
        ]:
            first = self.client.patch(f"/api/books/{bid}", json=body)
            second = self.client.patch(f"/api/books/{bid}", json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json(), second.json())

    def test_conditional_restore_cannot_change_unrelated_fields(self):
        bid = self._create(notes="after").json()["id"]
        for body in [
            {"notes": "before", "expected_notes": "after", "title": "unrelated"},
            {"expected_notes": "after"},
        ]:
            r = self.client.patch(f"/api/books/{bid}", json=body)
            self.assertEqual(r.status_code, 422)
        book = self.client.get("/api/books/overview").json()["shelves"]["want"][0]
        self.assertEqual(book["notes"], "after")
        self.assertEqual(book["title"], "Dune")

    def test_restore_checks_the_value_at_update_time(self):
        from sqlalchemy import event

        bid = self._create(notes="after").json()["id"]
        injected = False

        def newer_edit(connection, cursor, statement, parameters, context, executemany):
            nonlocal injected
            if not injected and statement.startswith("UPDATE books SET"):
                injected = True
                connection.exec_driver_sql(
                    "UPDATE books SET notes = ? WHERE id = ?", ("concurrent note", bid)
                )

        event.listen(self.eng, "before_cursor_execute", newer_edit)
        try:
            r = self.client.patch(
                f"/api/books/{bid}", json={"notes": "before", "expected_notes": "after"}
            )
        finally:
            event.remove(self.eng, "before_cursor_execute", newer_edit)
        self.assertTrue(injected)
        self.assertEqual(r.status_code, 409)

    def test_restore_rejects_changed_storage_and_accepts_current_scope(self):
        bid = self._create(notes="after").json()["id"]
        body = {"notes": "before", "expected_notes": "after", "recovery_scope": "not-current"}
        self.assertEqual(self.client.patch(f"/api/books/{bid}", json=body).status_code, 409)
        body["recovery_scope"] = self.client.get("/api/books/overview").json()["recovery_scopes"][0]
        r = self.client.patch(f"/api/books/{bid}", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notes"], "before")

    def test_delete_removes(self):
        bid = self._create().json()["id"]
        self.assertEqual(self.client.delete(f"/api/books/{bid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/books/{bid}").status_code, 404)


class BookGoalTests(ApiTest):
    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path
        from unittest import mock

        import core.settings

        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._patcher = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._tmp.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        super().tearDown()

    def test_goal_defaults_to_zero_in_overview(self):
        self.assertEqual(self.client.get("/api/books/overview").json().get("goal"), 0)

    def test_set_goal_shows_in_overview(self):
        self.assertEqual(self.client.put("/api/books/goal", json={"goal": 24}).status_code, 200)
        self.assertEqual(self.client.get("/api/books/overview").json()["goal"], 24)

    def test_goal_clamped_nonnegative(self):
        self.client.put("/api/books/goal", json={"goal": -5})
        self.assertEqual(self.client.get("/api/books/overview").json()["goal"], 0)
