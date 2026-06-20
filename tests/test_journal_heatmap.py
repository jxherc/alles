import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

import core.settings
from core.database import JournalEntry
from tests._client import ApiTest


class JournalHeatmapTests(ApiTest):
    def setUp(self):
        super().setUp()
        # hermetic settings so the dev's real journal passcode can't lock these out
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        super().tearDown()

    def _seed(self, day, words, mood=""):
        d = self.db()
        d.add(JournalEntry(date=day, content=" ".join(["w"] * words), mood=mood))
        d.commit()
        d.close()

    def _cal(self, year=None):
        params = {} if year is None else {"year": year}
        return self.client.get("/api/journal/calendar", params=params).json()

    def test_empty_year(self):
        r = self._cal(2099)
        self.assertEqual(r["days"], {})

    def test_day_has_words_mood_level(self):
        self._seed("2026-03-04", 20, "🙂")
        d = self._cal(2026)["days"]["2026-03-04"]
        self.assertEqual(d["words"], 20)
        self.assertEqual(d["mood"], "🙂")
        self.assertIn("level", d)

    def test_level_zero_for_empty_entry(self):
        self._seed("2026-03-05", 0)
        self.assertEqual(self._cal(2026)["days"]["2026-03-05"]["level"], 0)

    def test_level_increases_with_words(self):
        self._seed("2026-03-01", 5)
        self._seed("2026-03-02", 600)
        days = self._cal(2026)["days"]
        self.assertLess(days["2026-03-01"]["level"], days["2026-03-02"]["level"])

    def test_level_capped_at_four(self):
        self._seed("2026-03-03", 5000)
        self.assertLessEqual(self._cal(2026)["days"]["2026-03-03"]["level"], 4)

    def test_level_min_one_when_written(self):
        self._seed("2026-03-06", 3)
        self.assertGreaterEqual(self._cal(2026)["days"]["2026-03-06"]["level"], 1)

    def test_year_filter_excludes_other_years(self):
        self._seed("2025-12-31", 10)
        self._seed("2026-01-01", 10)
        days = self._cal(2026)["days"]
        self.assertIn("2026-01-01", days)
        self.assertNotIn("2025-12-31", days)

    def test_years_list_present(self):
        self._seed("2024-05-05", 10)
        self._seed("2026-05-05", 10)
        years = self._cal(2026)["years"]
        self.assertIn(2024, years)
        self.assertIn(2026, years)

    def test_years_sorted_desc(self):
        self._seed("2022-01-01", 5)
        self._seed("2026-01-01", 5)
        self._seed("2024-01-01", 5)
        years = self._cal(2026)["years"]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_default_year_is_current(self):
        r = self._cal()
        self.assertEqual(r["year"], date.today().year)

    def test_mood_empty_when_none(self):
        self._seed("2026-03-07", 10)
        self.assertEqual(self._cal(2026)["days"]["2026-03-07"]["mood"], "")
