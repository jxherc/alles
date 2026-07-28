import asyncio
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, NewsBrief, NewsConfiguration, NewsEntry, NewsSource, ReadItem
from services import news
from tests._client import ApiTest


def rss(*items):
    body = "".join(
        f"<item><guid>{guid}</guid><title>{title}</title><link>{url}</link>"
        f"<description>{summary}</description><pubDate>Tue, 22 Jul 2026 08:00:00 GMT</pubDate></item>"
        for guid, title, url, summary in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test feed</title>{body}</channel></rss>'


class Response:
    def __init__(self, text="", status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class NewsApiTest(ApiTest):
    def test_recent_clusters_use_fetch_time_only_when_publication_time_is_missing(self):
        now = datetime(2026, 7, 22, 9)
        db = self.db()
        source = NewsSource(name="Enabled", url="https://enabled.example/feed", enabled=True)
        db.add(source)
        db.flush()
        db.add_all(
            [
                NewsEntry(
                    source_id=source.id,
                    guid="recent",
                    canonical_url="https://enabled.example/recent",
                    title="recent published story",
                    published_at=now - timedelta(hours=2),
                    fetched_at=now,
                    content_hash="a" * 64,
                ),
                NewsEntry(
                    source_id=source.id,
                    guid="old",
                    canonical_url="https://enabled.example/old",
                    title="archival published story",
                    published_at=now - timedelta(days=10),
                    fetched_at=now,
                    content_hash="b" * 64,
                ),
                NewsEntry(
                    source_id=source.id,
                    guid="undated",
                    canonical_url="https://enabled.example/undated",
                    title="undated fresh story",
                    published_at=None,
                    fetched_at=now,
                    content_hash="c" * 64,
                ),
                NewsEntry(
                    source_id=source.id,
                    guid="future",
                    canonical_url="https://enabled.example/future",
                    title="far future story",
                    published_at=now + timedelta(days=2),
                    fetched_at=now,
                    content_hash="d" * 64,
                ),
            ]
        )
        db.commit()

        titles = {cluster["title"] for cluster in news.cluster_recent(db, now=now)}

        self.assertEqual(titles, {"recent published story", "undated fresh story"})
        db.close()

    def test_new_briefs_exclude_entries_from_disabled_sources(self):
        now = datetime(2026, 7, 22, 9)
        db = self.db()
        enabled = NewsSource(name="Enabled", url="https://enabled.example/feed", enabled=True)
        disabled = NewsSource(name="Disabled", url="https://disabled.example/feed", enabled=False)
        db.add_all([enabled, disabled])
        db.flush()
        db.add_all(
            [
                NewsEntry(
                    source_id=enabled.id,
                    guid="enabled",
                    canonical_url="https://enabled.example/story",
                    title="enabled story",
                    excerpt="included",
                    published_at=now,
                    fetched_at=now,
                    content_hash="a" * 64,
                ),
                NewsEntry(
                    source_id=disabled.id,
                    guid="disabled",
                    canonical_url="https://disabled.example/story",
                    title="disabled story",
                    excerpt="excluded",
                    published_at=now,
                    fetched_at=now,
                    content_hash="b" * 64,
                ),
            ]
        )
        db.commit()

        clusters = news.cluster_recent(db, now=now)

        self.assertEqual([cluster["title"] for cluster in clusters], ["enabled story"])
        db.close()

    def test_defaults_are_seeded_once_and_news_stays_off(self):
        first = self.client.get("/api/news")
        second = self.client.get("/api/news")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["configuration"]["enabled"])
        self.assertTrue(first.json()["configuration"]["deliver_home"])
        self.assertEqual(len(first.json()["sources"]), 3)
        self.assertEqual(len(second.json()["sources"]), 3)
        self.assertIsNone(first.json()["latest_brief"])

    def test_source_test_precedes_create_and_duplicate_is_rejected(self):
        tested = {
            "url": "https://example.org/feed.xml",
            "title": "Example",
            "items": [{"title": "one", "url": "https://example.org/one", "published": ""}],
        }
        with mock.patch("routes.news.news.test_source", new=mock.AsyncMock(return_value=tested)):
            response = self.client.post("/api/news/sources/test", json={"url": tested["url"]})
        self.assertEqual(response.status_code, 200)
        created = self.client.post(
            "/api/news/sources",
            json={
                "url": tested["url"],
                "name": "Example",
                "category": "world",
                "language": "en",
                "priority": 2,
                "schedule": "six_hours",
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["schedule"], "six_hours")
        self.assertEqual(
            self.client.post(
                "/api/news/sources",
                json={
                    "url": tested["url"],
                    "name": "again",
                },
            ).status_code,
            409,
        )

    def test_configuration_validates_timezone_time_and_jarvis_delivery(self):
        self.assertEqual(
            self.client.patch(
                "/api/news/configuration",
                json={
                    "cadence": "custom",
                    "time_of_day": "25:80",
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                "/api/news/configuration",
                json={
                    "timezone": "Not/AZone",
                },
            ).status_code,
            400,
        )
        unavailable = self.client.patch(
            "/api/news/configuration",
            json={
                "deliver_jarvis": True,
            },
        )
        self.assertEqual(unavailable.status_code, 409)
        enabled = self.client.patch(
            "/api/news/configuration",
            json={
                "enabled": True,
                "cadence": "custom",
                "time_of_day": "07:30",
                "timezone": "Asia/Taipei",
            },
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["enabled"])
        self.assertTrue(enabled.json()["next_run_at"])

    def test_configuration_and_source_writes_reject_invalid_nullable_fields(self):
        self.assertEqual(
            self.client.patch("/api/news/configuration", json={"enabled": None}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/news/sources",
                json={"url": "file:///private/feed.xml", "name": "private"},
            ).status_code,
            400,
        )
        source_id = self.client.get("/api/news").json()["sources"][0]["id"]
        self.assertEqual(
            self.client.patch(
                f"/api/news/sources/{source_id}", json={"priority": None}
            ).status_code,
            400,
        )

    def test_pipeline_dedupes_per_source_survives_partial_failure_and_never_auto_saves(self):
        db = self.db()
        config = news.ensure_defaults(db)
        db.query(NewsSource).delete()
        config.enabled = True
        first = NewsSource(name="Alpha", url="https://alpha.example/feed", priority=2)
        second = NewsSource(name="Beta", url="https://beta.example/feed", priority=1)
        failed = NewsSource(name="Failed", url="https://failed.example/feed")
        db.add_all([first, second, failed])
        db.commit()
        db.close()

        feed_a = rss(
            (
                "a-1",
                "Passkeys reach Taiwan public services",
                "https://alpha.example/passkeys?utm_source=x",
                "A staged rollout begins.",
            ),
            (
                "a-2",
                "Browser storage changes ship",
                "https://alpha.example/storage",
                "Partitioning reaches stable.",
            ),
        )
        feed_b = rss(
            (
                "b-1",
                "Taiwan public services reach passkeys",
                "https://beta.example/passkeys",
                "Recovery is part of the rollout.",
            ),
        )
        calls = []

        async def fetcher(url, **kwargs):
            calls.append((url, kwargs.get("headers") or {}))
            if "failed" in url:
                raise TimeoutError("private detail")
            if len([call for call in calls if call[0] == url]) > 1:
                return Response(status_code=304)
            return Response(feed_a if "alpha" in url else feed_b, headers={"etag": f'"{url}"'})

        async def unsummarized(_db, clusters):
            return clusters, False

        with mock.patch.object(news, "summarize_clusters", side_effect=unsummarized):
            result = asyncio.run(
                news.run_pipeline(force=True, fetcher=fetcher, now=datetime(2026, 7, 22, 9))
            )
            again = asyncio.run(
                news.run_pipeline(force=True, fetcher=fetcher, now=datetime(2026, 7, 22, 10))
            )

        self.assertEqual(result["reason"], "published")
        self.assertEqual(result["brief"]["status"], "summary_pending")
        self.assertIn("rollout", result["brief"]["summary"].lower())
        self.assertTrue(result["brief"]["delivered_home"])
        self.assertEqual(len(result["brief"]["source_failures"]), 1)
        self.assertTrue(any(len(cluster["links"]) == 2 for cluster in result["brief"]["clusters"]))
        self.assertEqual(again["reason"], "published")
        self.assertTrue(any(headers.get("If-None-Match") for _url, headers in calls[3:]))

        db = self.db()
        self.assertEqual(db.query(NewsEntry).count(), 3)
        self.assertEqual(db.query(ReadItem).count(), 0)
        failed_row = db.query(NewsSource).filter_by(name="Failed").one()
        self.assertEqual(failed_row.last_safe_error, "source fetch timed out")
        self.assertGreaterEqual(failed_row.failure_count, 1)
        self.assertIsNotNone(failed_row.next_retry_at)
        db.close()

        cluster = result["brief"]["clusters"][0]
        link = cluster["links"][0]
        saved = self.client.post(
            "/api/read/save-news",
            json={
                "url": link["url"],
                "title": cluster["title"],
                "excerpt": cluster["summary"],
                "publisher": link["source"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            self.client.get("/api/read").json()["items"][0]["source_kind"], "saved_news"
        )

    def test_home_includes_only_briefs_marked_for_home(self):
        db = self.db()
        db.add_all(
            [
                NewsBrief(
                    title="visible news",
                    summary="visible summary",
                    status="ready",
                    delivered_home=True,
                    published_at=datetime(2026, 7, 22, 8),
                ),
                NewsBrief(
                    title="hidden news",
                    summary="hidden summary",
                    status="ready",
                    delivered_home=False,
                    published_at=datetime(2026, 7, 22, 9),
                ),
            ]
        )
        db.commit()
        db.close()
        sections = self.client.get("/api/today").json()["sections"]
        summaries = [item["summary"] for item in sections["briefs"]]
        self.assertIn("visible summary", summaries)
        self.assertNotIn("hidden summary", summaries)

    def test_run_endpoint_requires_enabled_news(self):
        self.client.get("/api/news")
        self.assertEqual(self.client.post("/api/news/run").status_code, 409)


class NewsServiceTest(ApiTest):
    def test_canonical_url_preserves_retained_query_bytes(self):
        self.assertEqual(
            news.canonical_url(
                "https://Feed.Example/story?signature=a%20b&flag&utm_source=x&empty=&raw=%2F"
            ),
            "https://feed.example/story?signature=a%20b&flag&empty=&raw=%2F",
        )
        self.assertEqual(
            news.canonical_url("https://feed.example/story?u%74m_source=x&sig=a+b"),
            "https://feed.example/story?sig=a+b",
        )

    def test_concurrent_first_open_initializes_defaults_once(self):
        with tempfile.TemporaryDirectory(prefix="alles-news-defaults-") as temp:
            engine = create_engine(
                f"sqlite:///{Path(temp) / 'news.db'}",
                connect_args={"check_same_thread": False, "timeout": 5},
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            barrier = threading.Barrier(2)
            errors = []

            class SynchronizedFirstGet:
                def __init__(self, session):
                    self.session = session
                    self.waited = False

                def get(self, entity, key):
                    value = self.session.get(entity, key)
                    if entity is NewsConfiguration and not self.waited:
                        self.waited = True
                        barrier.wait(timeout=5)
                    return value

                def __getattr__(self, name):
                    return getattr(self.session, name)

            def initialize():
                db = sessions()
                try:
                    news.ensure_defaults(SynchronizedFirstGet(db))
                except Exception as exc:  # pragma: no cover - assertion reports the exact race
                    errors.append(exc)
                finally:
                    db.close()

            workers = [threading.Thread(target=initialize) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)

            db = sessions()
            try:
                self.assertFalse(errors)
                self.assertEqual(db.query(NewsConfiguration).count(), 1)
                self.assertEqual(db.query(NewsSource).count(), len(news.STARTER_SOURCES))
            finally:
                db.close()
                engine.dispose()

    def test_disabled_scheduler_does_not_open_network(self):
        news.ensure_defaults(self.db()).enabled = False
        fetcher = mock.AsyncMock()
        result = asyncio.run(news.run_pipeline(fetcher=fetcher))
        self.assertEqual(result["reason"], "disabled")
        fetcher.assert_not_awaited()

    def test_model_failure_keeps_link_digest(self):
        db = self.db()
        with mock.patch(
            "services.model_resolver.resolve_model", side_effect=RuntimeError("offline")
        ):
            clusters, summarized = asyncio.run(
                news.summarize_clusters(
                    db,
                    [
                        {
                            "title": "source title",
                            "summary": "source excerpt",
                            "links": [{"source": "publisher"}],
                        }
                    ],
                )
            )
        self.assertFalse(summarized)
        self.assertEqual(clusters[0]["summary"], "source excerpt")
        db.close()

    def test_news_summary_does_not_force_ollama_thinking_off(self):
        db = self.db()
        completion = mock.AsyncMock(return_value='[{"index": 0, "summary": "concise"}]')
        selected = SimpleNamespace(
            endpoint=SimpleNamespace(base_url="http://ollama.local", api_key=""),
            model="qwen3",
        )
        with (
            mock.patch("services.model_resolver.resolve_model", return_value=selected),
            mock.patch("services.llm.simple_complete", completion),
        ):
            clusters, summarized = asyncio.run(
                news.summarize_clusters(
                    db,
                    [{"title": "story", "summary": "source", "links": [{"source": "wire"}]}],
                )
            )
        self.assertTrue(summarized)
        self.assertEqual(clusters[0]["summary"], "concise")
        self.assertNotIn("thinking", completion.await_args.kwargs)
        db.close()

    def test_failed_inherited_source_retries_only_after_backoff(self):
        db = self.db()
        config = news.ensure_defaults(db)
        db.query(NewsSource).delete()
        config.enabled = True
        config.next_run_at = datetime(2026, 7, 23, 9)
        source = NewsSource(
            name="Retry",
            url="https://retry.example/feed",
            schedule="inherit",
            last_checked_at=datetime(2026, 7, 22, 9),
            last_safe_error="source fetch timed out",
            next_retry_at=datetime(2026, 7, 22, 9, 5),
            failure_count=1,
        )
        db.add(source)
        db.commit()
        db.close()

        fetcher = mock.AsyncMock(return_value=Response(status_code=304))
        early = asyncio.run(news.run_pipeline(fetcher=fetcher, now=datetime(2026, 7, 22, 9, 4)))
        due = asyncio.run(news.run_pipeline(fetcher=fetcher, now=datetime(2026, 7, 22, 9, 5)))

        self.assertFalse(early["ran"])
        self.assertEqual(due["reason"], "polled")
        fetcher.assert_awaited_once()

    def test_forced_run_rejects_an_unexpired_active_lease(self):
        db = self.db()
        config = news.ensure_defaults(db)
        config.run_token = "active-run"
        config.run_lease_until = datetime(2026, 7, 22, 9, 30)
        config.next_run_at = datetime(2026, 7, 22, 9)
        db.commit()
        db.close()

        fetcher = mock.AsyncMock()
        result = asyncio.run(
            news.run_pipeline(force=True, fetcher=fetcher, now=datetime(2026, 7, 22, 9, 5))
        )

        self.assertEqual(result["reason"], "busy")
        fetcher.assert_not_awaited()

    def test_polling_only_run_rejects_an_unexpired_active_lease(self):
        db = self.db()
        config = news.ensure_defaults(db)
        db.query(NewsSource).delete()
        config.enabled = True
        config.next_run_at = datetime(2026, 7, 23, 9)
        config.run_token = "active-poll"
        config.run_lease_until = datetime(2026, 7, 22, 9, 30)
        db.add(
            NewsSource(
                name="Polling lease",
                url="https://polling.example/feed",
                schedule="six_hours",
            )
        )
        db.commit()
        db.close()

        fetcher = mock.AsyncMock()
        result = asyncio.run(news.run_pipeline(fetcher=fetcher, now=datetime(2026, 7, 22, 9, 5)))

        self.assertEqual(result["reason"], "busy")
        fetcher.assert_not_awaited()

    def test_pipeline_stops_if_another_worker_replaces_its_run_claim(self):
        db = self.db()
        config = news.ensure_defaults(db)
        db.query(NewsSource).delete()
        config.enabled = True
        config.next_run_at = datetime(2026, 7, 22, 9)
        db.add(NewsSource(name="Lease", url="https://lease.example/feed"))
        db.commit()
        db.close()

        async def fetcher(_url, **_kwargs):
            competing = self.db()
            current = competing.get(NewsConfiguration, "singleton")
            current.run_token = "new-worker"
            current.run_lease_until = datetime(2026, 7, 22, 10)
            competing.commit()
            competing.close()
            return Response(
                rss(("lease-1", "claim changed", "https://lease.example/item", "summary"))
            )

        result = asyncio.run(news.run_pipeline(fetcher=fetcher, now=datetime(2026, 7, 22, 9)))

        self.assertEqual(result["reason"], "lease_lost")
        db = self.db()
        self.assertEqual(db.query(NewsBrief).count(), 0)
        current = db.get(NewsConfiguration, "singleton")
        self.assertEqual(current.run_token, "new-worker")
        self.assertIsNone(current.last_run_at)
        self.assertEqual(current.next_run_at, datetime(2026, 7, 22, 9))
        db.close()

    def test_summary_failure_does_not_advance_the_schedule_without_a_brief(self):
        db = self.db()
        config = news.ensure_defaults(db)
        db.query(NewsSource).delete()
        config.enabled = True
        config.next_run_at = datetime(2026, 7, 22, 9)
        db.add(NewsSource(name="Durability", url="https://durability.example/feed"))
        db.commit()
        db.close()

        fetcher = mock.AsyncMock(
            return_value=Response(
                rss(("durable-1", "durable story", "https://durability.example/item", "summary"))
            )
        )
        with mock.patch(
            "services.news.summarize_clusters",
            new=mock.AsyncMock(side_effect=RuntimeError("summary interrupted")),
        ):
            with self.assertRaisesRegex(RuntimeError, "summary interrupted"):
                asyncio.run(news.run_pipeline(fetcher=fetcher, now=datetime(2026, 7, 22, 9)))

        db = self.db()
        current = db.get(NewsConfiguration, "singleton")
        self.assertIsNone(current.last_run_at)
        self.assertEqual(current.next_run_at, datetime(2026, 7, 22, 9))
        self.assertEqual(current.run_token, "")
        self.assertEqual(db.query(NewsBrief).count(), 0)
        db.close()

    def test_jarvis_delivery_text_includes_brief_content_and_stays_bounded(self):
        brief = NewsBrief(
            title="news brief",
            status="ready",
            clusters='[{"title":"story","summary":"what changed","links":[{"url":"https://example.org/story"}]}]',
        )
        delivered = news._brief_delivery_text(brief)
        self.assertIn("what changed", delivered)
        self.assertIn("https://example.org/story", delivered)
        self.assertLessEqual(len(delivered), 1900)

    def test_persisted_pending_summary_is_retried_and_completed(self):
        db = self.db()
        brief = NewsBrief(
            title="pending brief",
            status="summary_pending",
            summary="link digest",
            clusters='[{"title":"story","summary":"feed excerpt","links":[]}]',
        )
        db.add(brief)
        db.commit()

        async def summarized(_db, clusters):
            clusters[0]["summary"] = "model summary"
            return clusters, True

        with mock.patch.object(news, "summarize_clusters", side_effect=summarized):
            completed = asyncio.run(news._retry_pending_summaries(db))

        db.refresh(brief)
        self.assertEqual(completed, 1)
        self.assertEqual(brief.status, "ready")
        self.assertEqual(brief.summary, "model summary")
        self.assertIn("model summary", brief.clusters)
        db.close()

    def test_failed_jarvis_delivery_retries_durably_then_completes(self):
        db = self.db()
        brief = NewsBrief(
            title="news brief",
            status="ready",
            clusters="[]",
            jarvis_delivery_state="pending",
            created_at=datetime(2026, 7, 22, 9),
        )
        db.add(brief)
        db.commit()
        brief_id = brief.id
        db.close()

        with mock.patch(
            "services.jarvis_discord.deliver_news_brief",
            new=mock.AsyncMock(return_value="failed"),
        ) as first_send:
            failed = asyncio.run(news.deliver_pending_briefs(now=datetime(2026, 7, 22, 9)))

        db = self.db()
        stored = db.get(NewsBrief, brief_id)
        self.assertEqual(failed, {"delivered": 0, "failed": 0})
        self.assertEqual(stored.jarvis_delivery_state, "retry")
        self.assertEqual(stored.jarvis_attempt_count, 1)
        retry_at = stored.jarvis_next_attempt_at
        db.close()

        with mock.patch(
            "services.jarvis_discord.deliver_news_brief",
            new=mock.AsyncMock(return_value="delivered"),
        ) as second_send:
            delivered = asyncio.run(news.deliver_pending_briefs(now=retry_at))

        db = self.db()
        stored = db.get(NewsBrief, brief_id)
        self.assertEqual(delivered, {"delivered": 1, "failed": 0})
        self.assertEqual(stored.jarvis_delivery_state, "delivered")
        self.assertEqual(stored.jarvis_attempt_count, 2)
        self.assertIsNone(stored.jarvis_next_attempt_at)
        first_key = first_send.await_args.kwargs["idempotency_key"]
        self.assertEqual(second_send.await_args.kwargs["idempotency_key"], first_key)
        self.assertEqual(first_key, f"news-brief:{brief_id}")
        db.close()

    def test_pending_brief_is_claimed_before_network_delivery(self):
        db = self.db()
        brief = NewsBrief(
            title="claimed brief",
            status="ready",
            clusters="[]",
            jarvis_delivery_state="pending",
            created_at=datetime(2026, 7, 22, 9),
        )
        db.add(brief)
        db.commit()
        db.close()

        nested = []

        async def delivery(_text, *, idempotency_key):
            self.assertTrue(idempotency_key.startswith("news-brief:"))
            nested.append(await news.deliver_pending_briefs(now=datetime(2026, 7, 22, 9)))
            return "delivered"

        with mock.patch(
            "services.jarvis_discord.deliver_news_brief", new=mock.AsyncMock(side_effect=delivery)
        ) as send:
            result = asyncio.run(news.deliver_pending_briefs(now=datetime(2026, 7, 22, 9)))

        self.assertEqual(result, {"delivered": 1, "failed": 0})
        self.assertEqual(nested, [{"delivered": 0, "failed": 0}])
        self.assertEqual(send.await_count, 1)

    def test_scheduler_job_is_registered_without_boot_fetch(self):
        import app as app_module
        from services import jobs

        with mock.patch.object(jobs, "register") as register:
            app_module._register_jobs()
        scheduled = [call for call in register.call_args_list if call.args[0] == "scheduled_news"]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0].args[2], 60)
        self.assertFalse(scheduled[0].kwargs["run_at_start"])
