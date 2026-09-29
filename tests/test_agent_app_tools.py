"""aide agent tools that drive the personal apps (books/health/habits/read/watch).
each tool is exercised through services.agent_tools.execute() against the in-memory
db, then verified via the real api so we know it actually persisted."""

import asyncio
from datetime import date
from unittest import mock

import services.agent_tools as at
from tests._client import ApiTest


class AgentAppToolsTests(ApiTest):
    def setUp(self):
        super().setUp()
        at.set_agent_ctx({"agent_environment": "general"})

    def tearDown(self):
        at.set_agent_ctx({})
        super().tearDown()

    def ex(self, name, args=None):
        return asyncio.run(at.execute(name, args or {}))

    def grant_health(self):
        at.set_agent_ctx({"agent_environment": "general", "agent_health_access_granted": True})

    # ── books ──────────────────────────────────────────────────────────────
    def test_book_add_persists(self):
        r = self.ex("book_add", {"title": "Dune", "author": "Herbert", "status": "reading"})
        self.assertFalse(r.get("error"), r)
        ov = self.client.get("/api/books/overview").json()
        self.assertEqual(ov["total"], 1)
        self.assertEqual(ov["shelves"]["reading"][0]["title"], "Dune")

    def test_book_add_rejects_bad_status(self):
        r = self.ex("book_add", {"title": "X", "status": "nonsense"})
        self.assertEqual(r, {"output": "status must be want, reading or done", "error": True})

    def test_book_add_rejects_blank_title_without_saving(self):
        r = self.ex("book_add", {"title": " \t "})
        self.assertEqual(r, {"output": "title required", "error": True})
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 0)

    def test_book_add_is_available_to_aide_recall(self):
        with mock.patch("services.textindex._embed", return_value=None):
            added = self.ex("book_add", {"title": "Quartzferret Handbook"})
            recall = self.ex("recall", {"query": "Quartzferret"})
        self.assertFalse(added.get("error"), added)
        self.assertIn("Quartzferret Handbook", recall["output"])
        self.assertIn("/?app=books#", recall["output"])

    def test_imported_book_is_available_to_aide_recall(self):
        csv = (
            "Title,Author,My Rating,Exclusive Shelf,Date Read,ISBN13,Year Published\n"
            "Quartzferret Field Guide,Author,4,read,2020/01/02,,2020\n"
        )
        with mock.patch("services.textindex._embed", return_value=None):
            imported = self.client.post("/api/books/import", json={"text": csv})
            recall = self.ex("recall", {"query": "Quartzferret"})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["imported"], 1)
        self.assertIn("Quartzferret Field Guide", recall["output"])
        self.assertIn("/?app=books#", recall["output"])

    def test_books_import_keeps_shelf_and_indexes_later_rows_after_index_error(self):
        from services import personal_index

        csv = (
            "Title,Author,My Rating,Exclusive Shelf,Date Read,ISBN13,Year Published\n"
            "Index Missing,Author,0,to-read,,,2020\n"
            "Index Surviving,Author,0,to-read,,,2020\n"
        )
        index_record = personal_index.index_record

        def fail_first(db, kind, book):
            if book.title == "Index Missing":
                raise RuntimeError("index unavailable")
            return index_record(db, kind, book)

        with (
            mock.patch("services.personal_index.index_record", side_effect=fail_first),
            mock.patch("services.textindex._embed", return_value=None),
        ):
            imported = self.client.post("/api/books/import", json={"text": csv})
            recall = self.ex("recall", {"query": "Surviving"})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["imported"], 2)
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 2)
        self.assertIn("Index Surviving", recall["output"])

    def test_books_import_respects_disabled_personal_index_source(self):
        from core.database import IndexChunk

        csv = (
            "Title,Author,My Rating,Exclusive Shelf,Date Read,ISBN13,Year Published\n"
            "Private Shelf Book,Author,0,to-read,,,2020\n"
        )
        with mock.patch(
            "services.personal_index.load_settings",
            return_value={"pidx_enabled": True, "pidx_book": False},
        ):
            imported = self.client.post("/api/books/import", json={"text": csv})
        self.assertEqual(imported.json()["imported"], 1)
        with self.db() as db:
            self.assertEqual(db.query(IndexChunk).filter_by(kind="book").count(), 0)

    def test_book_add_survives_an_index_outage(self):
        with mock.patch(
            "services.personal_index.index_record", side_effect=RuntimeError("offline")
        ):
            result = self.ex("book_add", {"title": "Dune", "status": "done"})
        self.assertFalse(result.get("error"), result)
        book = self.client.get("/api/books/overview").json()["shelves"]["done"][0]
        self.assertEqual(book["title"], "Dune")
        self.assertTrue(book["finished"])

    def test_books_list_shows_added(self):
        self.ex("book_add", {"title": "Dune"})
        r = self.ex("books_list", {})
        self.assertIn("Dune", r["output"])

    # ── health ─────────────────────────────────────────────────────────────
    def test_health_tools_need_an_explicit_general_aide_grant(self):
        names = {d["function"]["name"] for d in at.build_tool_defs({})}
        self.assertFalse({"health_log", "health_summary"} & names)
        denied = self.ex("health_summary", {})
        self.assertTrue(denied["error"])
        self.assertIn("explicit sensitive-data grant", denied["output"])
        denied_write = self.ex("health_log", {"kind": "weight", "value": 72.5})
        self.assertTrue(denied_write["error"])
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])

        granted = {
            "agent_environment": "general",
            "agent_health_access_granted": True,
        }
        names = {d["function"]["name"] for d in at.build_tool_defs(granted)}
        self.assertTrue({"health_log", "health_summary"}.issubset(names))

        project = {**granted, "agent_environment": "project"}
        names = {d["function"]["name"] for d in at.build_tool_defs(project)}
        self.assertFalse({"health_log", "health_summary"} & names)

    def test_health_log_persists(self):
        self.grant_health()
        r = self.ex("health_log", {"kind": "weight", "value": 72.5, "unit": "kg"})
        self.assertFalse(r.get("error"), r)
        entries = self.client.get("/api/health").json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], 72.5)

    def test_health_log_keeps_freeform_kind(self):
        self.grant_health()
        result = self.ex("health_log", {"kind": "steps", "value": 5000})
        self.assertFalse(result.get("error"), result)
        entries = self.client.get("/api/health").json()["entries"]
        self.assertEqual(entries[0]["kind"], "steps")

    def test_health_log_rejects_nonnumeric(self):
        self.grant_health()
        r = self.ex("health_log", {"kind": "weight", "value": "heavy"})
        self.assertTrue(r.get("error"))

    def test_health_log_rejects_nonfinite_without_saving(self):
        self.grant_health()
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                result = self.ex("health_log", {"kind": "weight", "value": value})
                self.assertEqual(result, {"output": "value must be a finite number", "error": True})
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])

    def test_health_summary_lists_metric(self):
        self.grant_health()
        self.ex("health_log", {"kind": "weight", "value": 72.5, "unit": "kg"})
        r = self.ex("health_summary", {})
        self.assertIn("weight", r["output"])

    # ── habits ─────────────────────────────────────────────────────────────
    def test_habit_add_and_log_today(self):
        self.ex("habit_add", {"name": "Read"})
        r = self.ex("habit_log", {"name": "Read"})
        self.assertFalse(r.get("error"), r)
        lst = self.ex("habits_list", {})
        self.assertIn("Read", lst["output"])

    def test_habit_log_recognizes_api_log_in_compact_date_form(self):
        from core.database import HabitLog

        habit = self.client.post("/api/habits", json={"name": "Read"}).json()
        compact = date.today().strftime("%Y%m%d")
        self.client.post(f"/api/habits/{habit['id']}/toggle", json={"date": compact})
        result = self.ex("habit_log", {"name": "Read"})
        self.assertIn("already marked done today", result["output"])
        with self.db() as db:
            self.assertEqual(db.query(HabitLog).filter_by(habit_id=habit["id"]).count(), 1)

    def test_habit_log_does_not_duplicate_existing_compact_row(self):
        from core.database import HabitLog

        habit = self.client.post("/api/habits", json={"name": "Read"}).json()
        with self.db() as db:
            db.add(HabitLog(habit_id=habit["id"], date=date.today().strftime("%Y%m%d")))
            db.commit()
        result = self.ex("habit_log", {"name": "Read"})
        self.assertIn("already marked done today", result["output"])
        with self.db() as db:
            self.assertEqual(db.query(HabitLog).filter_by(habit_id=habit["id"]).count(), 1)

    def test_habits_list_shows_existing_compact_log_as_done(self):
        from core.database import HabitLog

        habit = self.client.post("/api/habits", json={"name": "Read"}).json()
        with self.db() as db:
            db.add(HabitLog(habit_id=habit["id"], date=date.today().strftime("%Y%m%d")))
            db.commit()
        self.assertIn("[x] Read", self.ex("habits_list")["output"])

    def test_habit_log_unknown_name_errors(self):
        r = self.ex("habit_log", {"name": "does-not-exist"})
        self.assertTrue(r.get("error"))

    # ── read-later ─────────────────────────────────────────────────────────
    def test_read_save_persists(self):
        fake = {"content": "hello world body", "title": "Example", "og_image": ""}
        with mock.patch("services.read_items.fetch_webpage_content", return_value=fake):
            r = self.ex("read_save", {"url": "example.com"})
        self.assertFalse(r.get("error"), r)
        items = self.client.get("/api/read").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Example")

    def test_read_save_uses_read_preview_rules(self):
        fake = {"content": "quartzweasel\n\n  field notes", "title": "Example", "og_image": ""}
        with mock.patch("services.read_items.fetch_webpage_content", return_value=fake):
            result = self.ex("read_save", {"url": "www.example.com/story"})
        self.assertFalse(result.get("error"), result)
        item = self.client.get("/api/read").json()["items"][0]
        self.assertEqual(item["url"], "https://www.example.com/story")
        self.assertEqual(item["site"], "example.com")
        self.assertEqual(item["excerpt"], "quartzweasel field notes")

    def test_read_save_is_available_to_aide_recall(self):
        fake = {"content": "quartzweasel field notes", "title": "Example", "og_image": ""}
        with (
            mock.patch("services.read_items.fetch_webpage_content", return_value=fake),
            mock.patch("services.textindex._embed", return_value=None),
        ):
            result = self.ex("read_save", {"url": "example.com/story"})
            recall = self.ex("recall", {"query": "quartzweasel"})
        self.assertFalse(result.get("error"), result)
        self.assertIn("Example", recall["output"])
        self.assertIn("/?app=read#", recall["output"])

    def test_read_save_rejects_blank_url_without_saving(self):
        result = self.ex("read_save", {"url": " \t "})
        self.assertEqual(result, {"output": "url required", "error": True})
        self.assertEqual(self.client.get("/api/read").json()["items"], [])

    def test_read_save_survives_an_index_outage(self):
        fake = {"content": "saved text", "title": "Example", "og_image": ""}
        with (
            mock.patch("services.read_items.fetch_webpage_content", return_value=fake),
            mock.patch("services.personal_index.index_record", side_effect=RuntimeError("offline")),
        ):
            result = self.ex("read_save", {"url": "example.com/story"})
        self.assertFalse(result.get("error"), result)
        self.assertEqual(len(self.client.get("/api/read").json()["items"]), 1)

    # ── watch ──────────────────────────────────────────────────────────────
    def test_watch_add_and_status(self):
        r = self.ex("watch_add", {"name": "mysite", "url": "https://example.com"})
        self.assertFalse(r.get("error"), r)
        s = self.ex("watch_status", {})
        self.assertIn("mysite", s["output"])

    # ── registration / wiring ──────────────────────────────────────────────
    def test_new_tools_are_registered_and_mutating_flagged(self):
        names = {d["function"]["name"] for d in at.APP_TOOL_DEFS}
        for t in (
            "book_add",
            "books_list",
            "health_log",
            "health_summary",
            "habit_add",
            "habit_log",
            "habits_list",
            "read_save",
            "watch_add",
            "watch_status",
        ):
            self.assertIn(t, names, f"{t} missing from APP_TOOL_DEFS")
        for t in ("book_add", "health_log", "habit_add", "habit_log", "read_save", "watch_add"):
            self.assertIn(t, at.MUTATING_TOOLS, f"{t} should be in MUTATING_TOOLS")
