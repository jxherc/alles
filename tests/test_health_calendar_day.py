"""Health accepts an explicit calendar day without changing legacy date defaults."""

import hashlib
import json
import uuid
from datetime import date, timedelta

from core.database import HealthImportReceipt
from tests._client import ApiTest


class HealthCalendarDayTests(ApiTest):
    def test_overview_range_uses_the_requested_calendar_day(self):
        day = date.today() + timedelta(days=400)
        for kind, offset in [("weight", 8), ("sleep", 1)]:
            response = self.client.post(
                "/api/health",
                json={"kind": kind, "value": 8, "date": (day - timedelta(days=offset)).isoformat()},
            )
            self.assertEqual(response.status_code, 200)
        result = self.client.get(
            "/api/health/overview", params={"days": 7, "date_q": day.isoformat()}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([kind["kind"] for kind in result.json()["kinds"]], ["sleep"])

    def test_invalid_overview_day_is_rejected(self):
        for day in ["2026-02-30", "2026-10-01garbage"]:
            with self.subTest(day=day):
                self.assertEqual(
                    self.client.get("/api/health/overview", params={"date_q": day}).status_code, 400
                )

    def test_overview_rejects_a_range_outside_the_supported_calendar(self):
        response = self.client.get(
            "/api/health/overview", params={"date_q": "0001-01-01", "days": 7}
        )
        self.assertEqual(response.status_code, 400)

    def test_import_default_day_only_fills_blank_dates(self):
        body = {
            "text": "date,kind,value\n,weight,74.25\n2026-10-01,sleep,8\n",
            "request_id": str(uuid.uuid4()),
            "strict": True,
            "default_date": "2026-10-03",
        }
        first = self.client.post("/api/health/import", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            self.client.post("/api/health/import", json=body).json(),
            {"imported": 2, "skipped": 0, "replayed": True},
        )
        rows = self.client.get("/api/health").json()["entries"]
        self.assertEqual(
            {row["kind"]: row["date"] for row in rows},
            {"weight": "2026-10-03", "sleep": "2026-10-01"},
        )
        changed = self.client.post("/api/health/import", json=body | {"default_date": "2026-10-04"})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(self.client.get("/api/health").json()["entries"], rows)

    def test_legacy_import_still_defaults_to_server_day(self):
        response = self.client.post(
            "/api/health/import", json={"text": "kind,value\nweight,74.25\n", "strict": True}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.get("/api/health").json()["entries"][0]["date"], date.today().isoformat()
        )

    def test_invalid_import_default_day_saves_nothing(self):
        body = {
            "text": "kind,value\nweight,74.25\n",
            "strict": True,
            "request_id": str(uuid.uuid4()),
            "default_date": "2026-10-01junk",
        }
        response = self.client.post("/api/health/import", json=body)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])
        with self.db() as db:
            self.assertEqual(db.query(HealthImportReceipt).count(), 0)

    def test_preexisting_receipt_without_default_day_still_replays(self):
        body = {
            "text": "kind,value\nweight,74.25\n",
            "strict": True,
            "request_id": str(uuid.uuid4()),
        }
        # The previous receipt format hashed exactly these two fields.
        old_payload = {"text": body["text"], "strict": True}
        digest = hashlib.sha256(json.dumps(old_payload, ensure_ascii=False).encode()).hexdigest()
        with self.db() as db:
            db.add(
                HealthImportReceipt(
                    id=body["request_id"], payload_hash=digest, imported=1, skipped=0
                )
            )
            db.commit()
        response = self.client.post("/api/health/import", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"imported": 1, "skipped": 0, "replayed": True})
        self.assertEqual(self.client.get("/api/health").json()["entries"], [])
