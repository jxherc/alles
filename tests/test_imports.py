"""csv importers — goodreads → books, generic csv → health entries."""

import unittest

from services.imports import parse_goodreads_csv, parse_health_csv
from tests._client import ApiTest

GOODREADS = (
    'Title,Author,My Rating,Exclusive Shelf,Date Read,ISBN13,Year Published\n'
    'Dune,Frank Herbert,5,read,2026/01/15,"=""9780441172719""",1965\n'
    'The Hobbit,J.R.R. Tolkien,4,read,2025/12/01,,1937\n'
    'Some Book,Author X,0,to-read,,,2020\n'
    'In Progress,Author Y,0,currently-reading,,,2021\n'
    ',No Title,3,read,,,2000\n'   # blank title → skipped
)

HEALTH = (
    'date,kind,value,unit\n'
    '2026-01-01,weight,72.5,kg\n'
    '2026-01-02,sleep,7.5,h\n'
    '2026-01-03,weight,not-a-number,kg\n'   # bad value → skipped
)


class GoodreadsImportTests(unittest.TestCase):
    def test_maps_shelves_to_status(self):
        rows = parse_goodreads_csv(GOODREADS)
        by_title = {r["title"]: r for r in rows}
        self.assertEqual(by_title["Dune"]["status"], "done")
        self.assertEqual(by_title["Some Book"]["status"], "want")
        self.assertEqual(by_title["In Progress"]["status"], "reading")

    def test_fields_and_skips_blank_title(self):
        rows = parse_goodreads_csv(GOODREADS)
        self.assertEqual(len(rows), 4)  # the blank-title row is dropped
        dune = next(r for r in rows if r["title"] == "Dune")
        self.assertEqual(dune["author"], "Frank Herbert")
        self.assertEqual(dune["rating"], 5)
        self.assertEqual(dune["year"], 1965)
        self.assertEqual(dune["finished"], "2026-01-15")  # slashes → dashes, only when done
        self.assertEqual(dune["isbn"], "9780441172719")   # unwrapped from ="..."

    def test_garbage_is_empty(self):
        self.assertEqual(parse_goodreads_csv("nonsense without headers"), [])


class HealthImportTests(unittest.TestCase):
    def test_parses_rows_and_skips_bad_value(self):
        rows = parse_health_csv(HEALTH)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"kind": "weight", "value": 72.5, "unit": "kg", "date": "2026-01-01"})
        self.assertEqual(rows[1]["kind"], "sleep")

    def test_headers_case_insensitive(self):
        rows = parse_health_csv("Date,Metric,Value\n2026-02-02,steps,8000\n")
        self.assertEqual(rows[0]["kind"], "steps")
        self.assertEqual(rows[0]["value"], 8000.0)


class ImportRouteTests(ApiTest):
    def test_books_import_creates_rows(self):
        r = self.client.post("/api/books/import", json={"text": GOODREADS})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 4)
        ov = self.client.get("/api/books/overview").json()
        self.assertEqual(ov["total"], 4)
        titles = [b["title"] for s in ov["shelves"].values() for b in s]
        self.assertIn("Dune", titles)

    def test_books_reimport_is_idempotent(self):
        # re-running the same export shouldn't double the shelf
        self.assertEqual(self.client.post("/api/books/import", json={"text": GOODREADS}).json()["imported"], 4)
        r2 = self.client.post("/api/books/import", json={"text": GOODREADS})
        self.assertEqual(r2.json()["imported"], 0)
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 4)

    def test_health_import_creates_entries(self):
        r = self.client.post("/api/health/import", json={"text": HEALTH})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 2)
        entries = self.client.get("/api/health").json()["entries"]
        self.assertEqual(len(entries), 2)
