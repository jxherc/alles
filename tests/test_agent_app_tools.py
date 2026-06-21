"""aide agent tools that drive the personal apps (books/health/habits/read/watch).
each tool is exercised through services.agent_tools.execute() against the in-memory
db, then verified via the real api so we know it actually persisted."""

import asyncio
from unittest import mock

import services.agent_tools as at
from tests._client import ApiTest


class AgentAppToolsTests(ApiTest):
    def ex(self, name, args=None):
        return asyncio.run(at.execute(name, args or {}))

    # ── books ──────────────────────────────────────────────────────────────
    def test_book_add_persists(self):
        r = self.ex("book_add", {"title": "Dune", "author": "Herbert", "status": "reading"})
        self.assertFalse(r.get("error"), r)
        ov = self.client.get("/api/books/overview").json()
        self.assertEqual(ov["total"], 1)
        self.assertEqual(ov["shelves"]["reading"][0]["title"], "Dune")

    def test_book_add_rejects_bad_status(self):
        r = self.ex("book_add", {"title": "X", "status": "nonsense"})
        self.assertTrue(r.get("error"))

    def test_books_list_shows_added(self):
        self.ex("book_add", {"title": "Dune"})
        r = self.ex("books_list", {})
        self.assertIn("Dune", r["output"])

    # ── health ─────────────────────────────────────────────────────────────
    def test_health_log_persists(self):
        r = self.ex("health_log", {"kind": "weight", "value": 72.5, "unit": "kg"})
        self.assertFalse(r.get("error"), r)
        entries = self.client.get("/api/health").json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["value"], 72.5)

    def test_health_log_rejects_nonnumeric(self):
        r = self.ex("health_log", {"kind": "weight", "value": "heavy"})
        self.assertTrue(r.get("error"))

    def test_health_summary_lists_metric(self):
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

    def test_habit_log_unknown_name_errors(self):
        r = self.ex("habit_log", {"name": "does-not-exist"})
        self.assertTrue(r.get("error"))

    # ── read-later ─────────────────────────────────────────────────────────
    def test_read_save_persists(self):
        fake = {"content": "hello world body", "title": "Example", "og_image": ""}
        with mock.patch("services.research.search.fetch_webpage_content", return_value=fake):
            r = self.ex("read_save", {"url": "example.com"})
        self.assertFalse(r.get("error"), r)
        items = self.client.get("/api/read").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Example")

    # ── watch ──────────────────────────────────────────────────────────────
    def test_watch_add_and_status(self):
        r = self.ex("watch_add", {"name": "mysite", "url": "https://example.com"})
        self.assertFalse(r.get("error"), r)
        s = self.ex("watch_status", {})
        self.assertIn("mysite", s["output"])

    # ── registration / wiring ──────────────────────────────────────────────
    def test_new_tools_are_registered_and_mutating_flagged(self):
        names = {d["function"]["name"] for d in at.APP_TOOL_DEFS}
        for t in ("book_add", "books_list", "health_log", "health_summary",
                  "habit_add", "habit_log", "habits_list", "read_save",
                  "watch_add", "watch_status"):
            self.assertIn(t, names, f"{t} missing from APP_TOOL_DEFS")
        for t in ("book_add", "health_log", "habit_add", "habit_log", "read_save", "watch_add"):
            self.assertIn(t, at.MUTATING_TOOLS, f"{t} should be in MUTATING_TOOLS")
