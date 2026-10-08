import io
import json
import logging
import tempfile
from pathlib import Path

from core.database import AuditRecord
from services import observability
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
