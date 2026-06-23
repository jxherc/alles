"""rss/atom feed parsing for the read-later auto-save (services/read_feeds.py)."""

import asyncio
import unittest
from unittest import mock

from core.database import ReadFeed
from services.read_feeds import new_items, parse_feed
from tests._client import ApiTest

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>My Blog</title>
  <item><title>First Post</title><link>https://blog.example.com/1</link></item>
  <item><title>Second Post</title><link>https://blog.example.com/2</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Blog</title>
  <entry><title>Atom One</title>
    <link rel="self" href="https://atom.example.com/self"/>
    <link rel="alternate" href="https://atom.example.com/a"/>
  </entry>
  <entry><title>Atom Two</title><link href="https://atom.example.com/b"/></entry>
</feed>"""


class ParseFeedTests(unittest.TestCase):
    def test_rss_items_and_title(self):
        f = parse_feed(RSS)
        self.assertEqual(f["title"], "My Blog")
        self.assertEqual([i["link"] for i in f["items"]],
                         ["https://blog.example.com/1", "https://blog.example.com/2"])
        self.assertEqual(f["items"][0]["title"], "First Post")

    def test_atom_prefers_alternate_link(self):
        f = parse_feed(ATOM)
        self.assertEqual(f["title"], "Atom Blog")
        # rel=alternate wins over rel=self
        self.assertEqual([i["link"] for i in f["items"]],
                         ["https://atom.example.com/a", "https://atom.example.com/b"])

    def test_garbage_is_empty(self):
        self.assertEqual(parse_feed("not xml at all"), {"title": "", "items": []})
        self.assertEqual(parse_feed(""), {"title": "", "items": []})

    def test_new_items_filters_already_seen(self):
        items = [{"title": "a", "link": "u1"}, {"title": "b", "link": "u2"}]
        self.assertEqual(new_items(items, {"u1"}), [{"title": "b", "link": "u2"}])
        self.assertEqual(new_items(items, set()), items)
        self.assertEqual(new_items(items, {"u1", "u2"}), [])


class FeedApiTests(ApiTest):
    def test_add_list_delete_feed(self):
        r = self.client.post("/api/read/feeds", json={"url": "blog.example.com/rss"})
        self.assertEqual(r.status_code, 200)
        fid = r.json()["id"]
        # url got normalised to https
        feeds = self.client.get("/api/read/feeds").json()["feeds"]
        self.assertEqual(feeds[0]["url"], "https://blog.example.com/rss")
        # duplicate rejected
        self.assertEqual(
            self.client.post("/api/read/feeds", json={"url": "https://blog.example.com/rss"}).status_code,
            400,
        )
        self.assertEqual(self.client.delete(f"/api/read/feeds/{fid}").status_code, 200)
        self.assertEqual(self.client.get("/api/read/feeds").json()["feeds"], [])

    def test_refresh_auto_saves_new_entries(self):
        d = self.db()
        d.add(ReadFeed(url="https://blog.example.com/rss"))
        d.commit()
        d.close()

        class FakeResp:
            text = RSS

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return FakeResp()

        import services.net_guard as ng

        with (
            mock.patch("httpx.AsyncClient", FakeClient),
            mock.patch.object(ng, "is_safe_url", lambda u: True),  # fake host won't resolve; bypass guard
        ):
            from services.read_feeds import refresh_feeds

            asyncio.run(refresh_feeds())

        items = self.client.get("/api/read").json()["items"]
        urls = {i["url"] for i in items}
        self.assertIn("https://blog.example.com/1", urls)
        self.assertIn("https://blog.example.com/2", urls)
