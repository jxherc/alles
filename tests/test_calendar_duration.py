import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.settings import save_settings
from tests._client import ApiTest


class CalendarDurationTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        super().tearDown()

    def _create(self, **body):
        return self.client.post("/api/calendar", json=body).json()

    def test_create_no_end_applies_default(self):
        d = self._create(title="Sync", start_dt="2026-06-20T09:00:00")
        self.assertEqual(d["end_dt"], "2026-06-20T10:00:00")

    def test_create_explicit_end_kept(self):
        d = self._create(title="Sync", start_dt="2026-06-20T09:00:00", end_dt="2026-06-20T09:15:00")
        self.assertEqual(d["end_dt"], "2026-06-20T09:15:00")

    def test_create_all_day_no_end(self):
        d = self._create(title="Holiday", start_dt="2026-06-20", all_day=True)
        self.assertIn(d["end_dt"], (None, ""))

    def test_custom_default_30(self):
        save_settings({"cal_default_duration_min": 30})
        d = self._create(title="Quick", start_dt="2026-06-20T09:00:00")
        self.assertEqual(d["end_dt"], "2026-06-20T09:30:00")

    def test_quick_no_duration_default(self):
        d = self.client.post("/api/calendar/quick", json={"text": "lunch tomorrow 1pm"}).json()
        self.assertTrue(d["end_dt"])
        from datetime import datetime

        s = datetime.fromisoformat(d["start_dt"])
        e = datetime.fromisoformat(d["end_dt"])
        self.assertEqual((e - s).total_seconds(), 3600)

    def test_quick_for_2h_kept(self):
        d = self.client.post(
            "/api/calendar/quick", json={"text": "deep work tomorrow 9am for 2h"}
        ).json()
        from datetime import datetime

        s = datetime.fromisoformat(d["start_dt"])
        e = datetime.fromisoformat(d["end_dt"])
        self.assertEqual((e - s).total_seconds(), 2 * 3600)

    def test_invalid_default_falls_back_60(self):
        save_settings({"cal_default_duration_min": 0})
        d = self._create(title="X", start_dt="2026-06-20T09:00:00")
        self.assertEqual(d["end_dt"], "2026-06-20T10:00:00")

    def test_duration_math_correct(self):
        save_settings({"cal_default_duration_min": 45})
        d = self._create(title="X", start_dt="2026-06-20T14:15:00")
        self.assertEqual(d["end_dt"], "2026-06-20T15:00:00")

    def test_end_after_start(self):
        d = self._create(title="X", start_dt="2026-06-20T23:30:00")
        from datetime import datetime

        self.assertGreater(
            datetime.fromisoformat(d["end_dt"]), datetime.fromisoformat(d["start_dt"])
        )
