import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest import mock

from core.database import AndromedaSavedSearch, SessionLocal
from services import andromeda_watch
from tests._client import ApiTest

NOW = datetime(2026, 10, 18, 12, 0)


def _found(*urls, status="ready"):
    async def search(query, **_kwargs):
        return {"status": status, "results": [{"url": u, "title": u[-1]} for u in urls]}

    return search


class WatchServiceTest(ApiTest):
    def setUp(self):
        flag = mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"})
        flag.start()
        self.addCleanup(flag.stop)
        super().setUp()
        db = SessionLocal()
        db.query(AndromedaSavedSearch).delete()
        db.commit()
        db.close()

    def make(self, **values):
        db = SessionLocal()
        row = AndromedaSavedSearch(
            query="tailscale serve",
            request_json=json.dumps({"provider": "exa"}),
            results_json=json.dumps([{"url": "https://a.dev"}, {"url": "https://b.dev"}]),
            **values,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        db.close()
        return row.id

    def row(self, row_id):
        db = SessionLocal()
        row = db.get(AndromedaSavedSearch, row_id)
        db.expunge(row)
        db.close()
        return row

    def test_watching_starts_from_the_saved_results(self):
        row = AndromedaSavedSearch(query="q", results_json=json.dumps([{"url": "https://a.dev"}]))
        andromeda_watch.set_watch(row, 24, NOW)
        self.assertEqual(json.loads(row.watch_seen_json), ["https://a.dev"])
        self.assertEqual(row.watch_next_at, NOW + timedelta(hours=24))
        andromeda_watch.set_watch(row, 0, NOW)
        self.assertIsNone(row.watch_next_at)
        with self.assertRaises(ValueError):
            andromeda_watch.set_watch(row, 5, NOW)

    def test_only_links_not_seen_before_count_and_newest_come_first(self):
        row = AndromedaSavedSearch(query="q !ai", request_json='{"provider": "exa"}')
        andromeda_watch.set_watch(row, 6, NOW)
        row.watch_seen_json = json.dumps(["https://a.dev"])
        calls = []

        async def search(query, **kwargs):
            calls.append({**kwargs, "query": query})
            return await _found("https://a.dev", "https://c.dev")(query)

        with mock.patch("services.andromeda.normal_search", side_effect=search):
            self.assertEqual(asyncio.run(andromeda_watch.check(row, NOW)), 1)
        with mock.patch("services.andromeda.normal_search", side_effect=_found("https://d.dev")):
            self.assertEqual(asyncio.run(andromeda_watch.check(row, NOW)), 1)
        with mock.patch("services.andromeda.normal_search", side_effect=_found("https://d.dev")):
            self.assertEqual(asyncio.run(andromeda_watch.check(row, NOW)), 0)
        self.assertEqual((calls[0]["provider"], calls[0]["query"]), ("exa", "q"))
        self.assertEqual(
            [x["url"] for x in andromeda_watch.new_links(row)], ["https://d.dev", "https://c.dev"]
        )
        self.assertEqual(row.watch_next_at, NOW + timedelta(hours=6))
        andromeda_watch.mark_seen(row)
        self.assertEqual(andromeda_watch.summary(row)["new_count"], 0)

    def test_a_failed_run_waits_for_the_next_slot(self):
        row = AndromedaSavedSearch(query="q", request_json="{}")
        andromeda_watch.set_watch(row, 24, NOW)
        with mock.patch("services.andromeda.normal_search", side_effect=_found(status="error")):
            self.assertEqual(asyncio.run(andromeda_watch.check(row, NOW)), 0)
        self.assertEqual(row.watch_error, "error")
        self.assertEqual(row.watch_next_at, NOW + timedelta(hours=24))

    def test_the_job_checks_due_watches_and_tells_the_owner(self):
        due = self.make(
            watch_every_hours=24,
            watch_next_at=NOW - timedelta(minutes=1),
            watch_seen_json='["https://a.dev"]',
        )
        later = self.make(watch_every_hours=24, watch_next_at=NOW + timedelta(hours=1))
        off = self.make(watch_every_hours=0)
        sent = []

        async def push(payload):
            sent.append(payload)
            return {"sent": 1}

        with (
            mock.patch(
                "services.andromeda.normal_search",
                side_effect=_found("https://a.dev", "https://n.dev"),
            ),
            mock.patch("services.push_delivery.broadcast_result", side_effect=push),
            mock.patch("services.notify.configured", return_value=False),
        ):
            self.assertEqual(asyncio.run(andromeda_watch.run_due(NOW)), 1)
        self.assertEqual(andromeda_watch.summary(self.row(due))["new_count"], 1)
        self.assertEqual(self.row(later).watch_checked_at, None)
        self.assertEqual(self.row(off).watch_checked_at, None)
        self.assertEqual(len(sent), 1)
        self.assertIn("1 new link", sent[0]["body"])
        self.assertIn(due, sent[0]["url"])

    def test_the_job_does_nothing_when_andromeda_is_off(self):
        self.make(watch_every_hours=24, watch_next_at=NOW - timedelta(minutes=1))
        with mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_today"}):
            self.assertEqual(asyncio.run(andromeda_watch.run_due(NOW)), 0)

    def test_routes_set_watch_list_it_and_mark_seen(self):
        row_id = self.make(watch_new_json=json.dumps([{"url": "https://n.dev", "title": "n"}]))
        r = self.client.put(f"/api/andromeda/saved/{row_id}/watch", json={"every_hours": 168})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["watch"]["every_hours"], 168)
        self.assertEqual(
            self.client.put(
                f"/api/andromeda/saved/{row_id}/watch", json={"every_hours": 5}
            ).status_code,
            400,
        )
        listed = self.client.get("/api/andromeda/saved").json()["searches"][0]
        self.assertEqual(listed["watch"]["new_count"], 1)
        detail = self.client.get(f"/api/andromeda/saved/{row_id}").json()
        self.assertEqual(detail["watch_new"][0]["url"], "https://n.dev")
        seen = self.client.post(f"/api/andromeda/saved/{row_id}/watch/seen").json()
        self.assertEqual(seen["watch"]["new_count"], 0)
        self.assertEqual(
            self.client.put(
                "/api/andromeda/saved/nope/watch", json={"every_hours": 24}
            ).status_code,
            404,
        )
