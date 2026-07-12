import json
import tempfile
from pathlib import Path
from unittest import mock

from core.database import Message, ModelEndpoint, Session, Upload
from services import incognito
from tests._client import ApiTest


async def _fake_stream(messages, base_url, api_key, model, **kwargs):
    yield {"delta": "private reply"}
    yield {"done": True, "usage": {}}


class IncognitoIsolationTest(ApiTest):
    def setUp(self):
        super().setUp()
        incognito.clear_for_tests()
        self._uploads = tempfile.TemporaryDirectory()
        self._upload_patch = mock.patch("routes.uploads.UPLOAD_DIR", Path(self._uploads.name))
        self._upload_patch.start()

    def tearDown(self):
        incognito.clear_for_tests()
        self._upload_patch.stop()
        self._uploads.cleanup()
        super().tearDown()

    def _endpoint(self):
        db = self.db()
        endpoint = ModelEndpoint(
            name="local",
            base_url="http://localhost:11434",
            cached_models=json.dumps(["chat-model"]),
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        endpoint_id = endpoint.id
        db.close()
        return endpoint_id

    def _session(self):
        endpoint_id = self._endpoint()
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "private",
                "incognito": True,
                "endpoint_id": endpoint_id,
                "model": "chat-model",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        return response.json()["id"]

    def test_incognito_session_never_enters_sqlite(self):
        session_id = self._session()
        db = self.db()
        self.assertIsNone(db.get(Session, session_id))
        self.assertEqual(db.query(Session).count(), 0)
        db.close()
        self.assertIsNotNone(incognito.get_session(session_id))
        history = self.client.get(f"/api/sessions/{session_id}/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["messages"], [])
        self.assertEqual(self.client.get("/api/sessions").json()["today"], [])

    def test_incognito_chat_reads_no_memory_and_keeps_turns_only_in_ram(self):
        session_id = self._session()
        with (
            mock.patch("routes.chat.inject_memories") as memory,
            mock.patch("routes.chat.stream_chat", _fake_stream),
        ):
            response = self.client.post(
                "/api/chat",
                json={"session_id": session_id, "message": "keep this private", "incognito": True},
            )
        self.assertEqual(response.status_code, 200)
        memory.assert_not_called()
        db = self.db()
        self.assertEqual(db.query(Message).count(), 0)
        self.assertEqual(db.query(Session).count(), 0)
        db.close()
        history = self.client.get(f"/api/sessions/{session_id}/history").json()["messages"]
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])

    def test_incognito_keeps_context_between_turns(self):
        session_id = self._session()
        captured = []

        async def stream(messages, base_url, api_key, model, **kwargs):
            captured.append(messages)
            async for chunk in _fake_stream(messages, base_url, api_key, model, **kwargs):
                yield chunk

        with mock.patch("routes.chat.stream_chat", stream):
            for text in ("first private turn", "second private turn"):
                response = self.client.post(
                    "/api/chat",
                    json={"session_id": session_id, "message": text, "incognito": True},
                )
                self.assertEqual(response.status_code, 200)

        self.assertIn("first private turn", str(captured[1]))
        db = self.db()
        self.assertEqual(db.query(Message).count(), 0)
        self.assertEqual(db.query(Session).count(), 0)
        db.close()

    def test_incognito_upload_stays_in_memory_and_is_consumed(self):
        session_id = self._session()
        upload = self.client.post(
            "/api/uploads?incognito=true",
            files={"file": ("private.txt", b"private attachment", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200)
        upload_id = upload.json()["id"]
        self.assertEqual(list(Path(self._uploads.name).iterdir()), [])
        db = self.db()
        self.assertIsNone(db.get(Upload, upload_id))
        db.close()
        self.assertEqual(
            self.client.get(f"/api/uploads/{upload_id}").content, b"private attachment"
        )

        captured = {}

        async def stream(messages, base_url, api_key, model, **kwargs):
            captured["messages"] = messages
            async for chunk in _fake_stream(messages, base_url, api_key, model, **kwargs):
                yield chunk

        with mock.patch("routes.chat.stream_chat", stream):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": session_id,
                    "message": "read it",
                    "file_ids": [upload_id],
                    "incognito": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("private attachment", str(captured["messages"][-1]["content"]))
        self.assertIsNone(incognito.get_upload(upload_id))
        self.assertEqual(list(Path(self._uploads.name).iterdir()), [])

    def test_incognito_background_work_is_rejected(self):
        session_id = self._session()
        response = self.client.post(
            "/api/agent/background",
            json={"session_id": session_id, "message": "run later", "incognito": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "incognito_background_forbidden")

    def test_incognito_memory_extraction_is_rejected(self):
        session_id = self._session()
        response = self.client.post("/api/memories/extract", json={"session_id": session_id})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "incognito_memory_forbidden")

    def test_incognito_flag_cannot_hide_a_turn_in_a_normal_session(self):
        endpoint_id = self._endpoint()
        response = self.client.post(
            "/api/sessions",
            json={"endpoint_id": endpoint_id, "model": "chat-model"},
        )
        session_id = response.json()["id"]
        response = self.client.post(
            "/api/chat",
            json={"session_id": session_id, "message": "private?", "incognito": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "incognito_session_required")
        db = self.db()
        self.assertEqual(db.query(Message).count(), 0)
        db.close()

    def test_uploads_cannot_cross_the_incognito_boundary(self):
        private_session_id = self._session()
        normal_upload = self.client.post(
            "/api/uploads",
            files={"file": ("normal.txt", b"normal attachment", "text/plain")},
        ).json()["id"]
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": private_session_id,
                "message": "read it",
                "file_ids": [normal_upload],
                "incognito": True,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "incognito_upload_required")

        endpoint_id = self._endpoint()
        normal_session_id = self.client.post(
            "/api/sessions", json={"endpoint_id": endpoint_id, "model": "chat-model"}
        ).json()["id"]
        private_upload = self.client.post(
            "/api/uploads?incognito=true",
            files={"file": ("private.txt", b"private attachment", "text/plain")},
        ).json()["id"]
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": normal_session_id,
                "message": "read it",
                "file_ids": [private_upload],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "incognito_upload_forbidden")

    def test_delete_forgets_in_memory_session(self):
        session_id = self._session()
        self.assertEqual(self.client.delete(f"/api/sessions/{session_id}").status_code, 200)
        self.assertIsNone(incognito.get_session(session_id))
