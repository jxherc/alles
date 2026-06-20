import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import core.settings
from core.database import JournalEntry
from tests._client import ApiTest


class JournalMoodTests(ApiTest):
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

    def _seed(self, days_ago, mood, content="entry"):
        d = self.db()
        day = (date.today() - timedelta(days=days_ago)).isoformat()
        d.add(JournalEntry(date=day, content=content, mood=mood))
        d.commit()
        d.close()

    def _moods(self, days=30):
        return self.client.get("/api/journal/moods", params={"days": days}).json()

    def test_empty_distribution(self):
        r = self._moods()
        self.assertEqual(r["distribution"], [])
        self.assertEqual(r["with_mood"], 0)

    def test_counts_per_mood(self):
        self._seed(0, "🙂")
        self._seed(1, "🙂")
        self._seed(2, "😢")
        r = self._moods()
        d = {x["mood"]: x["count"] for x in r["distribution"]}
        self.assertEqual(d["🙂"], 2)
        self.assertEqual(d["😢"], 1)

    def test_distribution_sorted_desc(self):
        self._seed(0, "😢")
        self._seed(1, "🙂")
        self._seed(2, "🙂")
        self._seed(3, "🙂")
        counts = [x["count"] for x in self._moods()["distribution"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_most_common(self):
        self._seed(0, "😄")
        self._seed(1, "😄")
        self._seed(2, "😴")
        self.assertEqual(self._moods()["most_common"], "😄")

    def test_most_common_none_when_empty(self):
        self.assertIsNone(self._moods()["most_common"])

    def test_window_excludes_old(self):
        self._seed(2, "🙂")
        self._seed(60, "😢")  # outside a 30-day window
        moods = {x["mood"] for x in self._moods(30)["distribution"]}
        self.assertIn("🙂", moods)
        self.assertNotIn("😢", moods)

    def test_window_boundary_inclusive(self):
        self._seed(30, "🤔")
        moods = {x["mood"] for x in self._moods(30)["distribution"]}
        self.assertIn("🤔", moods)

    def test_with_mood_counts_only_moods(self):
        self._seed(0, "🙂")
        self._seed(1, "")  # no mood
        r = self._moods()
        self.assertEqual(r["with_mood"], 1)

    def test_total_entries_in_window(self):
        self._seed(0, "🙂")
        self._seed(1, "")
        self.assertEqual(self._moods()["total"], 2)

    def test_default_days(self):
        self._seed(0, "🙂")
        r = self.client.get("/api/journal/moods").json()
        self.assertIn("days", r)
        self.assertGreater(r["days"], 0)

    def test_blank_mood_not_in_distribution(self):
        self._seed(0, "")
        self.assertEqual(self._moods()["distribution"], [])
