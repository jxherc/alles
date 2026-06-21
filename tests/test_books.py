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
        self.assertEqual(self._create(status="someday").status_code, 400)

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

    def test_patch_notes(self):
        bid = self._create().json()["id"]
        r = self.client.patch(f"/api/books/{bid}", json={"notes": "great worldbuilding"})
        self.assertEqual(r.json()["notes"], "great worldbuilding")

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
