import asyncio
import io
import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from core.database import AuditRecord
from core.observability_middleware import ObservabilityMiddleware
from services import audit, observability
from tests._client import ApiTest


class ObservabilityUnitTest(ApiTest):
    def test_json_formatter_masks_common_credentials(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(observability.JsonFormatter())
        logger = logging.getLogger("alles.test.redaction")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        logger.info("Bearer alles_1234567890 password=hunter2 https://u:p@example.test/x?token=abc")
        row = json.loads(stream.getvalue())
        rendered = json.dumps(row)
        self.assertNotIn("alles_1234567890", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("token=abc", rendered)
        self.assertIn("***", rendered)

    def test_structured_log_reader_ignores_legacy_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "server.log"
            path.write_text(
                'old unstructured secret\n{"message":"Bearer alles_1234567890","password":"bad"}\n',
                "utf-8",
            )
            rows = observability.read_recent_logs(10, path)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("alles_1234567890", rows[0]["message"])
        self.assertEqual(rows[0]["password"], "***")

    def test_sql_parameter_blocks_are_removed(self):
        message = (
            "database write failed\n[SQL: INSERT INTO notes VALUES (?)]\n"
            "[parameters: ('my private journal text',)]\n"
            "(Background on this error: https://sqlalche.me/e/20/example)"
        )
        clean = observability.redact_text(message)
        self.assertNotIn("my private journal text", clean)
        self.assertIn("[parameters: ***]", clean)

    def test_write_request_creates_content_free_audit_record(self):
        response = self.client.post("/api/tasks", json={"title": "private task body"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("x-request-id"))
        with self.db() as db:
            row = db.query(AuditRecord).order_by(AuditRecord.created_at.desc()).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.action, "http.post")
            self.assertEqual(row.target, "/api/tasks")
            self.assertNotIn("private task body", row.details)

    def test_write_audit_is_stored_off_the_event_loop(self):
        seen = []

        def record(**fields):
            try:
                asyncio.get_running_loop()
                on_loop = True
            except RuntimeError:
                on_loop = False
            seen.append((fields["action"], on_loop, threading.current_thread().name))

        with mock.patch.object(audit, "record", record):
            response = self.client.post("/api/tasks", json={"title": "one"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(seen), 1)
        action, on_loop, thread = seen[0]
        self.assertEqual(action, "http.post")
        self.assertFalse(on_loop)
        self.assertTrue(thread.startswith("alles-audit"), thread)

    def test_lifespan_shutdown_waits_for_queued_audit_rows(self):
        stored = []
        app_saw = []

        def slow_record(**fields):
            time.sleep(0.3)
            stored.append(fields["action"])

        async def lifespan_app(scope, receive, send):
            await receive()
            await send({"type": "lifespan.startup.complete"})
            await receive()
            app_saw.append(list(stored))
            await send({"type": "lifespan.shutdown.complete"})

        async def run():
            inbox = asyncio.Queue()
            inbox.put_nowait({"type": "lifespan.startup"})
            inbox.put_nowait({"type": "lifespan.shutdown"})

            async def send(_message):
                pass

            await ObservabilityMiddleware(lifespan_app)({"type": "lifespan"}, inbox.get, send)

        with mock.patch.object(audit, "record", slow_record):
            audit.submit(action="http.post", outcome="success", actor="owner")
            asyncio.run(run())
        self.assertEqual(app_saw, [["http.post"]])

    def test_read_request_is_not_audited(self):
        self.client.get("/api/tasks")
        with self.db() as db:
            self.assertEqual(db.query(AuditRecord).count(), 0)

    def test_unmatched_route_does_not_log_private_path(self):
        self.assertEqual(
            observability.route_name({"path": "/api/private-token-value"}),
            "/api/[unmatched]",
        )

    def test_system_health_and_audit_are_structured(self):
        self.client.post("/api/tasks", json={"title": "one"})
        health = self.client.get("/api/system/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("scheduler", health.json())
        audit = self.client.get("/api/system/audit?limit=5")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json()["entries"][0]["target"], "/api/tasks")
