import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text

import core.settings as settings
from core.database import Message, ModelEndpoint, Project, Session
from core.migrations import m0023_memory_policy as migration
from services import memory_store
from tests._client import ApiTest


async def _fake_extract(messages, base_url, api_key, model, max_tokens=512):
    return "- prefers compact answers\n- likes local models"


class MemoryPolicyMigrationTest(unittest.TestCase):
    def test_adds_review_scope_and_usage_fields(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE memories ("
                    "id TEXT PRIMARY KEY, text TEXT, source TEXT, timestamp DATETIME)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO memories (id, text, source, timestamp) "
                    "VALUES ('m1', 'manual', 'manual', '2026-01-01'), "
                    "('m2', 'learned', 'extracted', '2026-01-02')"
                )
            )
            migration.up(conn)
            migration.up(conn)
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(memories)"))}
            rows = conn.execute(text("SELECT id, status, trust FROM memories ORDER BY id")).all()
        self.assertTrue(
            {"scope", "project_id", "status", "trust", "updated_at", "used_in_runs"}.issubset(
                columns
            )
        )
        self.assertEqual(rows, [("m1", "active", "owner"), ("m2", "suggested", "derived")])


class MemoryPolicyApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._settings_tmp = tempfile.TemporaryDirectory()
        self._settings_patch = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self._settings_tmp.name) / "settings.json"
        )
        self._settings_patch.start()
        settings._clear_settings_cache()

    def tearDown(self):
        settings._clear_settings_cache()
        self._settings_patch.stop()
        self._settings_tmp.cleanup()
        super().tearDown()

    def _endpoint_session(self, *, text_value="I prefer compact answers"):
        db = self.db()
        endpoint = ModelEndpoint(
            name="local",
            base_url="http://localhost:11434",
            cached_models=json.dumps(["chat-model"]),
        )
        session = Session(name="chat", endpoint=endpoint, model="chat-model")
        db.add_all([endpoint, session])
        db.flush()
        db.add(Message(session_id=session.id, role="user", content=text_value))
        db.add(Message(session_id=session.id, role="assistant", content="ignore this model claim"))
        db.commit()
        session_id = session.id
        db.close()
        return session_id

    def test_ask_is_default_and_extracted_items_wait_for_review(self):
        self.assertEqual(self.client.get("/api/settings").json()["memory_policy"], "ask")
        session_id = self._endpoint_session()
        with mock.patch("services.llm.simple_complete", _fake_extract):
            response = self.client.post(
                "/api/memories/extract", json={"session_id": session_id, "max_memories": 2}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extracted"], 2)
        memories = self.client.get("/api/memories").json()
        self.assertTrue(all(item["status"] == "suggested" for item in memories))
        self.assertTrue(all(item["trust"] == "derived" for item in memories))
        with mock.patch("services.memory_store._embed", return_value=None):
            self.assertEqual(memory_store.search_memories("compact answers"), [])

        accepted = self.client.post(f"/api/memories/{memories[0]['id']}/accept")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["trust"], "reviewed")
        with mock.patch("services.memory_store._embed", return_value=None):
            self.assertTrue(memory_store.search_memories("compact answers"))

    def test_off_blocks_reads_writes_extraction_and_distillation(self):
        response = self.client.patch("/api/settings", json={"memory_policy": "off"})
        self.assertEqual(response.status_code, 200)
        create = self.client.post("/api/memories", json={"text": "remember this"})
        self.assertEqual(create.status_code, 409)
        self.assertEqual(create.json()["code"], "memory_disabled")
        self.assertEqual(memory_store.search_memories("anything"), [])

        session_id = self._endpoint_session()
        extract = self.client.post("/api/memories/extract", json={"session_id": session_id})
        self.assertEqual(extract.status_code, 409)
        self.assertEqual(extract.json()["code"], "memory_disabled")

        from services import user_model

        db = self.db()
        self.assertEqual(__import__("asyncio").run(user_model.distill_async(db)), 0)
        db.close()

    def test_project_scope_and_usage_provenance(self):
        db = self.db()
        project_a = Project(name="A")
        project_b = Project(name="B")
        db.add_all([project_a, project_b])
        db.commit()
        a_id, b_id = project_a.id, project_b.id
        db.close()
        global_memory = memory_store.add_memory("global preference")
        project_memory = memory_store.add_memory(
            "project alpha preference", scope="project", project_id=a_id
        )
        memory_store.add_memory("project beta preference", scope="project", project_id=b_id)

        with mock.patch("services.memory_store._embed", return_value=None):
            text_value, ids = memory_store.inject_memories(
                "preference", project_id=a_id, run_id="run-1", return_details=True
            )
        self.assertIn("global preference", text_value)
        self.assertIn("project alpha preference", text_value)
        self.assertNotIn("project beta preference", text_value)
        self.assertIn(global_memory["id"], ids)
        self.assertIn(project_memory["id"], ids)
        rows = {item["id"]: item for item in memory_store.get_all_memories()}
        self.assertEqual(rows[project_memory["id"]]["used_in_runs"], ["run-1"])

    def test_auto_only_activates_direct_low_risk_preferences(self):
        self.client.patch("/api/settings", json={"memory_policy": "auto"})
        session_id = self._endpoint_session(
            text_value="I prefer short answers. My email is private@example.test."
        )
        with mock.patch("services.llm.simple_complete", _fake_extract):
            response = self.client.post(
                "/api/memories/extract", json={"session_id": session_id, "max_memories": 2}
            )
        self.assertEqual(response.status_code, 200)
        memories = self.client.get("/api/memories").json()
        active = [item for item in memories if item["status"] == "active"]
        suggested = [item for item in memories if item["status"] == "suggested"]
        self.assertEqual([item["text"] for item in active], ["I prefer short answers."])
        self.assertTrue(suggested)
        self.assertFalse(any("email" in item["text"].lower() for item in active))

    def test_export_and_clear(self):
        memory_store.add_memory("owner fact", provenance='{"kind":"owner_request"}')
        export = self.client.get("/api/memories/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn("owner fact", export.text)
        clear = self.client.delete("/api/memories")
        self.assertEqual(clear.status_code, 200)
        self.assertEqual(clear.json()["deleted"], 1)
        self.assertEqual(memory_store.get_all_memories(), [])

    def test_invalid_policy_has_stable_error(self):
        response = self.client.patch("/api/settings", json={"memory_policy": "sometimes"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_memory_policy")


if __name__ == "__main__":
    unittest.main()
