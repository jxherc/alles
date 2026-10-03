"""Synthetic feed outcomes, committed items, and overlapping refresh recovery."""

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.database import ReadFeed, ReadItem
from services.read_feeds import refresh_feeds
from tests._client import ApiTest

RSS = "<rss><channel><title>Local feed</title><item><title>Local post</title><link>https://example.invalid/post</link></item></channel></rss>"
EMPTY = "<rss><channel><title>Empty local feed</title></channel></rss>"


class FeedRefreshContract(ApiTest):
    def add(self, suffix):
        response = self.client.post(
            "/api/read/feeds", json={"url": "https://example.invalid/" + suffix}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def response(self, text, status=200):
        return httpx.Response(
            status, text=text, request=httpx.Request("GET", "https://example.invalid/fixture")
        )

    def refresh(self, side_effect):
        with mock.patch(
            "services.net_guard.safe_get_async", new=mock.AsyncMock(side_effect=side_effect)
        ):
            response = self.client.post("/api/read/feeds/refresh")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_failure_is_reported_without_updating_last_success(self):
        fid = self.add("failed")
        result = self.refresh(RuntimeError("synthetic outage"))
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("failed"), 1)
        with self.db() as db:
            self.assertIsNone(db.get(ReadFeed, fid).last_checked)

    def test_partial_refresh_saves_good_links_and_identifies_failed_feed(self):
        good = self.add("good")
        bad = self.add("bad")
        result = self.refresh([self.response(RSS), RuntimeError("synthetic outage")])
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(
            (result.get("checked"), result.get("failed"), result.get("added")), (1, 1, 1)
        )
        self.assertEqual({row["id"] for row in result["feeds"] if not row["ok"]}, {bad})
        with self.db() as db:
            self.assertIsNotNone(db.get(ReadFeed, good).last_checked)
            self.assertIsNone(db.get(ReadFeed, bad).last_checked)
        self.assertEqual(len(self.client.get("/api/read").json()["items"]), 1)

    def test_invalid_xml_does_not_become_an_empty_success(self):
        fid = self.add("invalid")
        result = self.refresh([self.response("not xml")])
        self.assertFalse(result.get("ok"), result)
        with self.db() as db:
            self.assertIsNone(db.get(ReadFeed, fid).last_checked)

    def test_http_failure_with_parseable_body_is_still_failure(self):
        fid = self.add("unavailable")
        result = self.refresh([self.response(RSS, 503)])
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(self.client.get("/api/read").json()["items"], [])
        with self.db() as db:
            self.assertIsNone(db.get(ReadFeed, fid).last_checked)

    def test_empty_valid_feed_and_repeat_are_successful_without_duplicates(self):
        self.add("empty")
        result = self.refresh([self.response(EMPTY)])
        self.assertTrue(result.get("ok"))
        self.assertEqual(
            (result.get("checked"), result.get("failed"), result.get("added")), (1, 0, 0)
        )
        self.refresh([self.response(RSS)])
        result = self.refresh([self.response(RSS)])
        self.assertEqual(result.get("added"), 0)
        self.assertEqual(len(self.client.get("/api/read").json()["items"]), 1)

    def test_no_feeds_reports_no_work(self):
        result = self.refresh([])
        self.assertTrue(result.get("ok"))
        self.assertEqual(
            (result.get("checked"), result.get("failed"), result.get("added")), (0, 0, 0)
        )

    def test_save_failure_rolls_back_only_its_feed_and_continues(self):
        first = self.add("first")
        second = self.add("second")
        original = Session.commit
        calls = []

        def commit(db):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("synthetic save failure")
            return original(db)

        with mock.patch.object(Session, "commit", autospec=True, side_effect=commit):
            result = self.refresh(
                [self.response(RSS), self.response(RSS.replace("/post", "/second"))]
            )
        self.assertEqual((result["checked"], result["failed"], result["added"]), (1, 1, 1))
        with self.db() as db:
            self.assertIsNone(db.get(ReadFeed, first).last_checked)
            self.assertIsNotNone(db.get(ReadFeed, second).last_checked)
            self.assertEqual(
                [row.url for row in db.query(ReadItem).all()], ["https://example.invalid/second"]
            )

    def test_removed_during_fetch_is_skipped(self):
        fid = self.add("removed")

        async def fetch(*args, **kwargs):
            with self.db() as db:
                db.delete(db.get(ReadFeed, fid))
                db.commit()
            return self.response(RSS)

        result = self.refresh(fetch)
        self.assertEqual(
            (result["checked"], result["failed"], result["added"], result["skipped"]), (0, 0, 0, 1)
        )
        self.assertEqual(self.client.get("/api/read").json()["items"], [])

    def test_duplicate_entries_and_limit_make_progress_without_duplicates(self):
        self.add("many")
        entry = "<item><link>https://example.invalid/{}</link></item>"
        rss = (
            "<rss><channel>" + "".join(entry.format(i) * 2 for i in range(40)) + "</channel></rss>"
        )
        self.assertEqual(
            [self.refresh([self.response(rss)])["added"] for _ in range(3)], [25, 15, 0]
        )
        with self.db() as db:
            self.assertEqual(db.query(ReadItem).count(), 40)


class ConcurrentFeedRefresh(unittest.TestCase):
    def test_overlapping_refreshes_do_not_duplicate_links(self):
        with tempfile.TemporaryDirectory(prefix="alles-feed-race-") as folder:
            engine = create_engine("sqlite:///" + str(Path(folder) / "fixture.db"))
            session = sessionmaker(bind=engine)
            try:
                ReadFeed.__table__.create(engine)
                ReadItem.__table__.create(engine)
                with session() as db:
                    db.add(ReadFeed(url="https://example.invalid/feed"))
                    db.commit()
                barrier = threading.Barrier(2)

                async def fetch(url, **kwargs):
                    barrier.wait(timeout=10)
                    return httpx.Response(200, text=RSS, request=httpx.Request("GET", url))

                with (
                    mock.patch("core.database.SessionLocal", session),
                    mock.patch("services.net_guard.safe_get_async", side_effect=fetch),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    futures = [pool.submit(lambda: asyncio.run(refresh_feeds())) for _ in range(2)]
                    for future in futures:
                        future.result(timeout=20)
                with session() as db:
                    self.assertEqual(db.query(ReadItem).count(), 1)
            finally:
                engine.dispose()


class FeedCreateRace(ApiTest):
    def test_concurrent_subscriptions_keep_one_copy(self):
        with tempfile.TemporaryDirectory(prefix="alles-feed-create-") as root:
            engine = create_engine("sqlite:///" + str(Path(root) / "fixture.db"))
            sessions = sessionmaker(bind=engine)
            ReadFeed.__table__.create(engine)
            try:
                with (
                    mock.patch("core.database.SessionLocal", sessions),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    for number in range(20):
                        barrier = threading.Barrier(2)
                        url = f"https://example.invalid/feed-{number}"

                        def add():
                            barrier.wait(timeout=5)
                            return self.client.post("/api/read/feeds", json={"url": url})

                        results = list(pool.map(lambda _: add(), range(2)))
                        self.assertTrue(
                            all(r.status_code in (200, 400) for r in results),
                            [r.status_code for r in results],
                        )
                        with sessions() as db:
                            self.assertEqual(
                                db.query(ReadFeed).filter_by(url=url).count(), 1, f"pair {number}"
                            )
            finally:
                engine.dispose()
