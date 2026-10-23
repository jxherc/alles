import hashlib
import uuid

from core.database import Task
from tests._client import ApiTest


class HomeCapturePreviewTests(ApiTest):
    def test_possessive_title_survives_preview_acceptance_and_readback(self):
        for apostrophe in ("'", "’"):
            with self.subTest(apostrophe=apostrophe):
                text = f"prepare tomorrow{apostrophe}s reading"
                response = self.client.post(
                    "/api/tasks/quick",
                    json={"text": text, "preview": True, "today": "2032-12-31"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                proposal = response.json()
                self.assertEqual(proposal["candidate"]["title"], text)
                self.assertEqual(proposal["candidate"]["due_date"], "2033-01-01")
                self.assertEqual(proposal["source"]["excerpt"], text)
                with self.db() as db:
                    self.assertEqual(db.query(Task).count(), 0)
                saved = self.client.post(
                    "/api/tasks",
                    json={
                        **proposal["candidate"],
                        "source": proposal["source"],
                        "request_id": str(uuid.uuid4()),
                    },
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                records = self.client.get("/api/tasks")
                self.assertEqual(records.status_code, 200, records.text)
                record = next(row for row in records.json() if row["id"] == saved.json()["id"])
                self.assertEqual(record["title"], text)
                self.assertEqual(record["due_date"], "2033-01-01")
                self.assertEqual(record["source"]["excerpt"], text)
                self.assertEqual(
                    self.client.delete("/api/tasks/" + saved.json()["id"]).status_code, 200
                )

    def test_preview_resolves_relative_dates_against_the_displayed_home_day(self):
        response = self.client.post(
            "/api/tasks/quick",
            json={"text": "call tomorrow", "preview": True, "today": "2032-12-31"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["candidate"]["due_date"], "2033-01-01")

    def test_preview_parses_without_writing_and_preserves_literal_input(self):
        text = "  call mom tomorrow #home !  "
        response = self.client.post("/api/tasks/quick", json={"text": text, "preview": True})
        self.assertEqual(response.status_code, 200, response.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)
        proposal = response.json()
        self.assertEqual(proposal["kind"], "task")
        self.assertEqual(proposal["candidate"]["title"], "call mom")
        self.assertEqual(proposal["candidate"]["tags"], "home")
        self.assertTrue(proposal["candidate"]["due_date"])
        self.assertEqual(proposal["source"]["kind"], "capture")
        self.assertEqual(proposal["source"]["excerpt"], text)
        self.assertEqual(
            proposal["source"]["fingerprint"], hashlib.sha256(text.encode()).hexdigest()
        )

    def test_literal_source_survives_accepted_edit_completion_and_replay(self):
        text = "original  capture\n  exact second line"
        source = {
            "kind": "capture",
            "label": "original capture",
            "excerpt": text,
            "fingerprint": hashlib.sha256(text.encode()).hexdigest(),
        }
        body = {"title": "accepted title", "source": source, "request_id": str(uuid.uuid4())}
        saved = self.client.post("/api/tasks", json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        rid = saved.json()["id"]
        changed = self.client.patch(
            "/api/tasks/" + rid, json={"title": "changed later", "done": True}
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        done = self.client.get("/api/tasks/done").json()
        self.assertEqual(next(row for row in done if row["id"] == rid)["source"], source)
        retry = self.client.post("/api/tasks", json=body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["id"], rid)
        self.assertEqual(retry.json()["source"], source)
        self.assertTrue(retry.json()["done"])
        wrong_reader = self.client.get("/api/mail/source/task/" + rid)
        self.assertEqual(wrong_reader.status_code, 400, wrong_reader.text)

    def test_preview_rejects_empty_or_oversize_text_without_writing(self):
        for text in ["  ", "a" * 6001]:
            with self.subTest(length=len(text)):
                response = self.client.post(
                    "/api/tasks/quick", json={"text": text, "preview": True}
                )
                self.assertEqual(response.status_code, 400, response.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)

    def test_preview_accepts_supplementary_unicode_at_the_source_limit(self):
        original = "🙂" * 6000
        response = self.client.post("/api/tasks/quick", json={"text": original, "preview": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source"]["excerpt"], original)
        rejected = self.client.post(
            "/api/tasks/quick", json={"text": original + "🙂", "preview": True}
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)

    def test_legacy_quick_add_keeps_direct_creation(self):
        response = self.client.post("/api/tasks/quick", json={"text": "call tomorrow #home"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["id"])
        self.assertEqual(response.json()["title"], "call")
        self.assertEqual(response.json()["tags"], ["home"])
        self.assertIsNone(response.json()["source"])

    def test_source_hash_mismatch_is_rejected_without_creating(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "title": "capture",
                "source": {"kind": "capture", "excerpt": "changed", "fingerprint": "a" * 64},
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)

    def test_literal_source_survives_recurring_task_and_event_edits(self):
        proposal = self.client.post(
            "/api/tasks/quick",
            json={"text": "water plants every day", "preview": True, "today": "2032-06-20"},
        ).json()
        source = proposal["source"]
        task = self.client.post(
            "/api/tasks",
            json={
                "title": "water plants",
                "due_date": "2032-06-20",
                "repeat": "daily",
                "source": source,
            },
        )
        self.assertEqual(task.status_code, 200, task.text)
        self.assertEqual(
            self.client.patch("/api/tasks/" + task.json()["id"], json={"done": True}).status_code,
            200,
        )
        upcoming = self.client.get("/api/tasks").json()
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["source"], source)
        event = self.client.post(
            "/api/calendar",
            json={"title": "watering time", "start_dt": "2032-06-21T10:00", "source": source},
        )
        self.assertEqual(event.status_code, 200, event.text)
        edited = self.client.patch(
            "/api/calendar/" + event.json()["id"], json={"title": "updated time"}
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["source"], source)
