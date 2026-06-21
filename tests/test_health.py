from datetime import date, timedelta

from core.database import HealthEntry
from routes.health import latest_per_kind, series_for
from tests._client import ApiTest


class HealthLogicTests(ApiTest):
    def _e(self, kind, d, v):
        return HealthEntry(kind=kind, date=d, value=v, unit="")

    def test_latest_per_kind(self):
        entries = [
            self._e("weight", "2026-06-18", 80),
            self._e("weight", "2026-06-20", 79),
            self._e("sleep", "2026-06-19", 7),
        ]
        latest = latest_per_kind(entries)
        self.assertEqual(latest["weight"].value, 79)  # most recent date wins
        self.assertEqual(latest["sleep"].value, 7)

    def test_latest_per_kind_empty(self):
        self.assertEqual(latest_per_kind([]), {})

    def test_series_for_sorted_asc(self):
        entries = [
            self._e("weight", "2026-06-20", 79),
            self._e("weight", "2026-06-18", 80),
            self._e("sleep", "2026-06-19", 7),
        ]
        s = series_for(entries, "weight")
        self.assertEqual([p["date"] for p in s], ["2026-06-18", "2026-06-20"])
        self.assertEqual([p["value"] for p in s], [80, 79])

    def test_series_for_filters_kind(self):
        entries = [self._e("weight", "2026-06-20", 79), self._e("sleep", "2026-06-19", 7)]
        self.assertEqual(len(series_for(entries, "sleep")), 1)


class HealthApiTests(ApiTest):
    def _create(self, **kw):
        body = {"kind": "weight", "value": 80.5, "unit": "kg", "date": "2026-06-20"}
        body.update(kw)
        return self.client.post("/api/health", json=body)

    def test_create_returns_id(self):
        r = self._create()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["id"])
        self.assertEqual(r.json()["value"], 80.5)

    def test_create_rejects_bad_kind(self):
        self.assertEqual(self._create(kind="vibes").status_code, 400)

    def test_create_requires_value(self):
        self.assertEqual(self.client.post("/api/health", json={"kind": "weight"}).status_code, 422)

    def test_create_defaults_date_to_today(self):
        r = self.client.post("/api/health", json={"kind": "sleep", "value": 7})
        self.assertEqual(r.json()["date"], date.today().isoformat())

    def test_list_contains_created(self):
        self._create()
        kinds = [e["kind"] for e in self.client.get("/api/health").json()["entries"]]
        self.assertIn("weight", kinds)

    def test_overview_latest_and_series(self):
        self._create(value=80, date="2026-06-18")
        self._create(value=79, date="2026-06-20")
        ov = self.client.get("/api/health/overview").json()
        w = next(k for k in ov["kinds"] if k["kind"] == "weight")
        self.assertEqual(w["latest"]["value"], 79)
        self.assertEqual(len(w["series"]), 2)
        self.assertEqual(w["series"][0]["value"], 80)  # oldest first

    def test_overview_range_excludes_old(self):
        old = (date.today() - timedelta(days=400)).isoformat()
        self._create(value=99, date=old)
        self._create(value=70, date=date.today().isoformat())
        ov = self.client.get("/api/health/overview", params={"days": 30}).json()
        w = next(k for k in ov["kinds"] if k["kind"] == "weight")
        vals = [p["value"] for p in w["series"]]
        self.assertIn(70, vals)
        self.assertNotIn(99, vals)

    def test_delete_removes(self):
        eid = self._create().json()["id"]
        self.assertEqual(self.client.delete(f"/api/health/{eid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/health/{eid}").status_code, 404)

    def test_patch_updates_value(self):
        eid = self._create().json()["id"]
        r = self.client.patch(f"/api/health/{eid}", json={"value": 81.0, "note": "post lunch"})
        self.assertEqual(r.json()["value"], 81.0)
        self.assertEqual(r.json()["note"], "post lunch")


class HealthTargetTests(ApiTest):
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

    def _kind(self, kind):
        ov = self.client.get("/api/health/overview").json()
        return next((k for k in ov["kinds"] if k["kind"] == kind), None)

    def test_target_absent_is_none(self):
        self.client.post("/api/health", json={"kind": "sleep", "value": 7})
        self.assertIsNone(self._kind("sleep").get("target"))

    def test_set_target_appears_in_overview(self):
        self.client.post("/api/health", json={"kind": "weight", "value": 72, "unit": "kg"})
        self.assertEqual(
            self.client.put("/api/health/target", json={"kind": "weight", "value": 68}).status_code,
            200,
        )
        self.assertEqual(self._kind("weight")["target"], 68)

    def test_zero_clears_target(self):
        self.client.post("/api/health", json={"kind": "weight", "value": 72})
        self.client.put("/api/health/target", json={"kind": "weight", "value": 68})
        self.client.put("/api/health/target", json={"kind": "weight", "value": 0})
        self.assertIsNone(self._kind("weight").get("target"))
