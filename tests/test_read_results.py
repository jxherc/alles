"""Explicit search-result saves keep local excerpts without fetching publishers."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import ReadItem
from routes.read import NewsSaveBody, save_news, save_result
from tests._client import ApiTest


class ReadResultTests(ApiTest):
    def test_concurrent_web_and_news_saves_share_one_record(self):
        with tempfile.TemporaryDirectory(prefix="alles-result-save-") as folder:
            engine = create_engine("sqlite:///" + str(Path(folder) / "synthetic.db"))
            self.addCleanup(engine.dispose)
            ReadItem.__table__.create(engine)
            sessions = sessionmaker(bind=engine)
            barrier = threading.Barrier(2)
            body = NewsSaveBody(url="http://localhost:8765/concurrent", excerpt="owned excerpt")

            def save(owner):
                with sessions() as db:
                    barrier.wait(timeout=5)
                    result = owner(body, db)
                    return result["item"]["id"]

            with (
                mock.patch("services.personal_index.index_record"),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                futures = [pool.submit(save, owner) for owner in (save_result, save_news)]
                ids = [future.result(timeout=10) for future in futures]
            self.assertEqual(ids[0], ids[1])
            with sessions() as db:
                self.assertEqual(db.query(ReadItem).count(), 1)
                self.assertEqual(
                    set(db.query(ReadItem).one().tags.split(", ")), {"source:search", "source:news"}
                )

    def test_web_result_is_saved_once_without_becoming_news(self):
        payload = {
            "url": "HTTP://localhost:8765/result#section",
            "title": "owned result",
            "excerpt": "a synthetic local excerpt",
            "publisher": "owned local source",
        }
        with mock.patch("services.read_items.fetch_webpage_content") as fetch:
            first = self.client.post("/api/read/save-result", json=payload)
            second = self.client.post("/api/read/save-result", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        item = first.json()["item"]
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(item["id"], second.json()["item"]["id"])
        self.assertEqual(item["url"], "http://localhost:8765/result")
        self.assertEqual(item["source_kind"], "saved_search")
        self.assertEqual(item["tags"], "source:search")
        self.assertEqual(item["text_state"], "excerpt")
        self.assertEqual(
            self.client.get("/api/read/" + item["id"]).json()["text"], payload["excerpt"]
        )
        fetch.assert_not_called()

    def test_existing_article_keeps_text_metadata_and_completion(self):
        with self.db() as db:
            article = ReadItem(
                url="http://localhost:8765/existing",
                title="owner title",
                text="full saved text",
                text_state="extracted",
                excerpt="owner excerpt",
                site="owner site",
                image="",
                tags="personal",
                read_at="2026-10-01T12:00:00",
                read_position=0.6,
                archived=True,
                fav=True,
            )
            db.add(article)
            db.commit()
            identity = article.id
        before = self.client.get("/api/read/" + identity).json()
        with mock.patch("services.read_items.fetch_webpage_content") as fetch:
            for path in ("save-result", "save-news", "save-result"):
                response = self.client.post(
                    "/api/read/" + path,
                    json={
                        "url": before["url"],
                        "title": "replacement",
                        "excerpt": "shorter",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["duplicate"])
                self.assertEqual(response.json()["item"]["id"], identity)
        after = self.client.get("/api/read/" + identity).json()
        for field in before.keys() - {"tags", "source_kind"}:
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(after["source_kind"], "saved_news")
        self.assertEqual(after["tags"], "personal, source:search, source:news")
        fetch.assert_not_called()

    def test_query_identity_and_empty_excerpt(self):
        ids = []
        for query in ("a=1", "a=2"):
            response = self.client.post(
                "/api/read/save-result",
                json={
                    "url": "http://localhost:8765/?" + query,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()["item"]
            ids.append(item["id"])
            self.assertEqual(item["text_state"], "empty")
            self.assertEqual(item["excerpt"], "")
        self.assertEqual(len(set(ids)), 2)

    def test_invalid_or_credentialed_urls_create_nothing(self):
        for url in ("", "file:///local", "http://synthetic-user@localhost:8765/", "http://[bad"):
            with self.subTest(url=url):
                response = self.client.post("/api/read/save-result", json={"url": url})
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/read").json()["items"], [])
