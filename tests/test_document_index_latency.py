"""Response and event-loop boundaries with an indexer that cannot finish yet."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, FastAPI

from core.database import get_db
from routes import vault_md as routes
from services import document_safety, vault_md


class DocumentIndexLatencyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-document-latency-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "vault").mkdir()
        self.enterContext(patch.object(vault_md, "vault_dir", return_value=root / "vault"))
        self.enterContext(patch.object(document_safety, "data_dir", return_value=root / "state"))
        self.app = FastAPI()
        self.app.include_router(routes.router)

    async def request(self, path, payload, response_sent):
        body = json.dumps(payload).encode()
        messages = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                response_sent.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
        await self.app(scope, receive, send)
        status = next(
            message["status"] for message in messages if message["type"] == "http.response.start"
        )
        content = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return status, json.loads(content)

    async def assert_acknowledged_before_index_finishes(
        self, path, payload, expected, document_path=None
    ):
        entered = threading.Event()
        release = threading.Event()
        response_sent = asyncio.Event()
        indexed = []

        def blocked_index(ref, content):
            entered.set()
            release.wait(timeout=3)
            indexed.append((ref, content))

        with patch.object(routes, "_reindex_doc", side_effect=blocked_index):
            request = asyncio.create_task(self.request(path, payload, response_sent))
            try:
                started = await asyncio.to_thread(entered.wait, 2)
                acknowledged = response_sent.is_set()
                persisted = vault_md.read(document_path or payload["path"])["content"]
            finally:
                release.set()
                status, result = await asyncio.wait_for(request, 3)
        self.assertTrue(started, "the fake indexer was never exercised")
        self.assertTrue(acknowledged, "persisted save acknowledgment waited for indexing")
        self.assertEqual(status, 200, result)
        self.assertEqual(persisted, expected)
        self.assertEqual(indexed[-1], (document_path or payload["path"], expected))

    async def test_safe_save_acknowledges_persisted_bytes_before_indexing_finishes(self):
        opened = vault_md.write("save.md", "original")
        await self.assert_acknowledged_before_index_finishes(
            "/api/vault-md/safety/save",
            {"path": "save.md", "content": "saved", "expected_hash": opened["hash"]},
            "saved",
        )

    async def test_revision_restore_acknowledges_restored_bytes_before_indexing_finishes(self):
        opened = vault_md.write("revision.md", "original")
        saved = document_safety.save_document("revision.md", "changed", opened["hash"])
        revision = document_safety.list_revisions("revision.md")[0]
        await self.assert_acknowledged_before_index_finishes(
            "/api/vault-md/safety/revisions/restore",
            {"path": "revision.md", "revision_id": revision["id"], "expected_hash": saved["hash"]},
            "original",
        )

    async def test_trash_restore_acknowledges_restored_file_before_indexing_finishes(self):
        self.app.dependency_overrides[get_db] = lambda: None
        item = SimpleNamespace(kind="vault", ref="restored.md")

        def restore(_db, _item, destination):
            destination.write_text("restored")

        with (
            patch.object(routes.trash, "get", return_value=item),
            patch.object(routes.trash, "restore_path", side_effect=restore),
        ):
            await self.assert_acknowledged_before_index_finishes(
                "/api/vault-md/trash/restore",
                {"id": "synthetic-trash-id"},
                "restored",
                "restored.md",
            )

    async def test_newer_save_is_acknowledged_and_eventually_wins_slow_indexing(self):
        opened = vault_md.write("queued.md", "original")
        entered = threading.Event()
        release = threading.Event()
        indexed = []
        first_sent = asyncio.Event()
        second_sent = asyncio.Event()

        def index(_path, content):
            if content == "first":
                entered.set()
                release.wait(timeout=3)
            indexed.append(content)

        with patch.object(routes, "_reindex_doc", side_effect=index):
            first = asyncio.create_task(
                self.request(
                    "/api/vault-md/safety/save",
                    {"path": "queued.md", "content": "first", "expected_hash": opened["hash"]},
                    first_sent,
                )
            )
            second = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                second = asyncio.create_task(
                    self.request(
                        "/api/vault-md/safety/save",
                        {
                            "path": "queued.md",
                            "content": "second",
                            "expected_hash": vault_md.read("queued.md")["hash"],
                        },
                        second_sent,
                    )
                )
                await asyncio.wait_for(second_sent.wait(), 1)
                self.assertEqual(vault_md.read("queued.md")["content"], "second")
            finally:
                release.set()
                results = await asyncio.gather(first, *([second] if second else []))
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(indexed[-1], "second")

    async def test_failed_indexing_is_logged_after_save_was_acknowledged(self):
        opened = vault_md.write("logging.md", "original")
        sent = asyncio.Event()
        with (
            patch("services.textindex.index", side_effect=RuntimeError("index unavailable")),
            patch("core.database.SessionLocal"),
        ):
            with self.assertLogs("routes.vault_md", level="ERROR") as logged:
                status, result = await self.request(
                    "/api/vault-md/safety/save",
                    {"path": "logging.md", "content": "saved", "expected_hash": opened["hash"]},
                    sent,
                )
        self.assertTrue(sent.is_set())
        self.assertEqual(status, 200, result)
        self.assertEqual(vault_md.read("logging.md")["content"], "saved")
        self.assertIn("could not refresh document search index", "\n".join(logged.output))

    async def test_queued_folder_renames_remove_original_index_identities(self):
        vault_md.write("first/item.md", "current content")
        indexed = {"first/item.md": "current content"}
        first = BackgroundTasks()
        second = BackgroundTasks()
        routes.rename_file(routes.RenameBody(path="first", new_path="second"), first)
        routes.rename_file(routes.RenameBody(path="second", new_path="third"), second)
        with (
            patch.object(
                routes,
                "_reindex_doc",
                side_effect=lambda path, content: indexed.update({path: content}),
            ),
            patch.object(routes, "_unindex_doc", side_effect=lambda path: indexed.pop(path, None)),
        ):
            await first()
            await second()
        self.assertEqual(indexed, {"third/item.md": "current content"})

    async def test_conflict_response_does_not_enqueue_rejected_content(self):
        opened = vault_md.write("conflict.md", "original")
        vault_md.write("conflict.md", "external")
        with patch.object(routes, "_sync_changed") as refresh:
            status, result = await self.request(
                "/api/vault-md/safety/save",
                {"path": "conflict.md", "content": "stale", "expected_hash": opened["hash"]},
                asyncio.Event(),
            )
        self.assertEqual(status, 409, result)
        refresh.assert_not_called()
        self.assertEqual(vault_md.read("conflict.md")["content"], "external")

    async def test_stream_removal_indexing_does_not_block_the_event_loop(self):
        entered = threading.Event()
        responsive = threading.Event()
        observed = []

        def blocked_remove(_path):
            entered.set()
            observed.append(responsive.wait(timeout=1))

        async def unrelated_async_request():
            started = await asyncio.to_thread(entered.wait, 2)
            self.assertTrue(started)
            responsive.set()

        with (
            patch.object(routes, "VAULT_WATCH_INTERVAL", 0),
            patch.object(routes, "_vault_sig", side_effect=[{"gone.md": "1:1"}, {}]),
            patch.object(
                routes, "_observed_event", return_value={"path": "gone.md", "kind": "removed"}
            ),
            patch.object(routes, "_unindex_doc", side_effect=blocked_remove),
        ):
            response = await routes.stream()
            iterator = response.body_iterator
            await anext(iterator)
            try:
                event, _ = await asyncio.gather(anext(iterator), unrelated_async_request())
            finally:
                responsive.set()
                await iterator.aclose()
        self.assertIn('"removed": ["gone.md"]', event)
        self.assertEqual(observed, [True], "index removal blocked unrelated async work")


if __name__ == "__main__":
    unittest.main()
