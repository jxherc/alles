import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._client import ApiTest


class AideConversationPhase4Test(ApiTest):
    def test_full_access_turn_override_requires_recent_owner(self):
        from routes.chat import _require_turn_authority

        request = mock.Mock()
        with mock.patch("routes.chat.require_recent_owner") as require:
            _require_turn_authority(
                request,
                {"agent_permission_mode": "full_access"},
            )
            require.assert_called_once_with(request)

            _require_turn_authority(
                request,
                {"agent_permission_mode": "full_auto"},
            )
            require.assert_called_once_with(request)

    def test_detached_chat_forces_a_noninteractive_permission_mode(self):
        source = (Path(__file__).resolve().parents[1] / "routes/chat.py").read_text("utf-8")
        foreground = source[
            source.index("async def chat(") : source.index("async def chat_background")
        ]
        background = source[
            source.index("async def chat_background") : source.index("def stop_chat")
        ]
        assignment = 'settings["agent_permission_mode"] = "full_auto"'
        self.assertNotIn(assignment, foreground)
        self.assertIn(assignment, background)
        self.assertIn('settings["agent_detached"] = True', background)
        self.assertIn("_require_turn_authority(request, settings)", foreground)
        self.assertIn("_require_turn_authority(request, settings)", background)
        self.assertLess(
            foreground.index("_apply_run_controls(settings"),
            foreground.index("_require_turn_authority(request, settings)"),
        )
        self.assertLess(
            background.index(assignment),
            background.index("_require_turn_authority(request, settings)"),
        )

    def test_chat_behavior_and_jarvis_mode_roundtrip(self):
        created = self.client.post(
            "/api/sessions",
            json={"mode": "jarvis", "chat_behavior": "answer_only"},
        )
        self.assertEqual(created.status_code, 200)
        session = created.json()
        self.assertEqual(session["mode"], "jarvis")
        self.assertEqual(session["chat_behavior"], "answer_only")

        patched = self.client.patch(
            f"/api/sessions/{session['id']}",
            json={"mode": "chat", "chat_behavior": "automatic_tools"},
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["mode"], "chat")
        self.assertEqual(patched.json()["chat_behavior"], "automatic_tools")

    def test_legacy_agent_mode_reads_as_jarvis(self):
        created = self.client.post("/api/sessions", json={"mode": "agent"})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["mode"], "jarvis")

    def test_invalid_mode_and_behavior_fail_closed(self):
        bad_mode = self.client.post("/api/sessions", json={"mode": "research"})
        bad_behavior = self.client.post(
            "/api/sessions", json={"chat_behavior": "always_run_everything"}
        )
        self.assertEqual(bad_mode.status_code, 400)
        self.assertEqual(bad_behavior.status_code, 400)

    def test_empty_behavior_follows_settings(self):
        session = self.client.post("/api/sessions", json={}).json()
        self.assertEqual(session["chat_behavior"], "")

    def test_invalid_turn_permission_and_effort_are_rejected(self):
        invalid_permission = self.client.post(
            "/api/chat",
            json={
                "session_id": "missing",
                "message": "test",
                "permission_mode": "unrestricted",
            },
        )
        invalid_effort = self.client.post(
            "/api/chat",
            json={"session_id": "missing", "message": "test", "effort": "turbo"},
        )
        self.assertEqual(invalid_permission.status_code, 422)
        self.assertEqual(invalid_effort.status_code, 422)


class AideContextProvenancePhase4Test(ApiTest):
    def test_context_provenance_names_only_context_that_was_used(self):
        from core.database import Memory, ModelEndpoint, Persona, Project, Session
        from routes.chat import _context_provenance

        db = self.db()
        project = Project(name="work", system_prompt="project rules")
        persona = Persona(name="focused", system_prompt="extra")
        endpoint = ModelEndpoint(name="local", base_url="http://127.0.0.1:11434")
        memory = Memory(text="prefers short answers", scope="project", status="active")
        db.add_all([project, persona, endpoint, memory])
        db.flush()
        memory.project_id = project.id
        session = Session(name="p", project_id=project.id, persona_id=persona.id)
        db.add(session)
        db.commit()
        provenance = _context_provenance(
            session,
            {"owner_instructions": "plain language"},
            persona,
            [memory.id],
            db,
            endpoint,
            "small-model",
        )
        self.assertTrue(provenance["owner_instructions"])
        self.assertTrue(provenance["project_instructions"])
        self.assertEqual(provenance["persona"]["name"], "focused")
        self.assertEqual(provenance["memories"][0]["text"], "prefers short answers")
        self.assertEqual(provenance["memories"][0]["scope"], "project")
        self.assertEqual(provenance["endpoint"], "local")
        db.close()

    def test_off_and_incognito_remove_memory_tools_without_touching_other_denials(self):
        from services.memory_store import apply_memory_tool_policy

        off = apply_memory_tool_policy({"memory_policy": "off", "disabled_tools": ["shell"]})
        self.assertEqual(off["disabled_tools"], ["memory_add", "memory_search", "shell"])
        private = apply_memory_tool_policy(
            {"memory_policy": "auto", "disabled_tools": []}, incognito=True
        )
        self.assertEqual(private["disabled_tools"], ["memory_add", "memory_search"])
        normal = apply_memory_tool_policy({"memory_policy": "ask", "disabled_tools": ["shell"]})
        self.assertEqual(normal["disabled_tools"], ["shell"])

    def test_memory_off_and_incognito_omit_personal_insights(self):
        from core.database import Insight, Session
        from routes.chat import _build_messages

        db = self.db()
        db.add(Insight(title="private pattern", body="personal detail", dedupe_key="phase4"))
        session = Session(name="privacy")
        db.add(session)
        db.commit()
        base = {
            "memory_auto_inject": False,
            "memory_policy": "ask",
            "insights_auto_inject": True,
            "distilled_auto_inject": False,
            "session_context_inject": False,
            "artifacts_enabled": False,
        }
        for privacy in ({"memory_policy": "off"}, {"incognito": True}):
            with self.subTest(privacy=privacy):
                prompt = _build_messages(
                    session,
                    "hello",
                    {**base, **privacy},
                    db=db,
                )[0]["content"]
                self.assertNotIn("private pattern", prompt)
                self.assertNotIn("personal detail", prompt)
        db.close()


class AideInsightGenerationPrivacyPhase4Test(ApiTest):
    def test_force_generation_cannot_bypass_memory_off_or_incognito(self):
        from services import insights

        calls = []

        async def model(corpus):
            calls.append(corpus)
            return '[{"title":"leak","evidence":["private"]}]'

        db = self.db()
        with mock.patch(
            "core.settings.load_settings",
            return_value={"insights_enabled": True, "memory_policy": "off"},
        ):
            memory_off = asyncio.run(insights.generate_async(db, model_fn=model, force=True))
        incognito = asyncio.run(
            insights.generate_async(
                db,
                model_fn=model,
                force=True,
                incognito=True,
                settings={"insights_enabled": True, "memory_policy": "ask"},
            )
        )
        self.assertEqual(memory_off, {"ran": False, "reason": "memory_off", "count": 0})
        self.assertEqual(incognito, {"ran": False, "reason": "incognito", "count": 0})
        self.assertEqual(calls, [])
        db.close()

    def test_scheduled_generation_stops_before_opening_the_insight_pipeline(self):
        import app as app_module
        from services import insights, jobs

        with mock.patch.object(jobs, "register") as register:
            app_module._register_jobs()
        insight_job = next(
            call.args[1] for call in register.call_args_list if call.args[0] == "insights"
        )
        settings = {"insights_enabled": True, "memory_policy": "off"}
        with (
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch.object(insights, "generate_async", new_callable=mock.AsyncMock) as generate,
        ):
            asyncio.run(insight_job())
        generate.assert_not_awaited()


class AideAgentRunMetaPhase4Test(ApiTest):
    @staticmethod
    async def _run_agent(
        messages,
        endpoint,
        model,
        stop_event,
        settings,
        accumulated,
        thinking,
        steps,
        session_id="",
    ):
        yield {"agent_run": {"id": "phase4-live-run", "status": "running"}}
        accumulated.append("finished")
        yield {"delta": "finished"}
        yield {"done": True, "usage": {"completion_tokens": 1}}

    def _drive(self, session_id, *, incognito=False):
        from routes import chat as chat_module

        async def run():
            async for _ in chat_module._stream_and_save(
                session_id=session_id,
                user_text="do this",
                messages=[{"role": "user", "content": "do this"}],
                ep=SimpleNamespace(),
                model="phase4-model",
                stop_event=asyncio.Event(),
                db_factory=self.db,
                incognito=incognito,
                mode="agent",
                settings={"context_provenance": {}},
            ):
                pass

        with mock.patch.object(chat_module, "run_agent", self._run_agent):
            asyncio.run(run())

    def test_saved_assistant_message_keeps_agent_run_id_for_reload(self):
        from core.database import Session

        db = self.db()
        session = Session(name="normal")
        db.add(session)
        db.commit()
        session_id = session.id
        db.close()
        self._drive(session_id)
        history = self.client.get(f"/api/sessions/{session_id}/history").json()
        assistant = next(row for row in history["messages"] if row["role"] == "assistant")
        self.assertEqual(assistant["meta"]["agent_run_id"], "phase4-live-run")

    def test_incognito_assistant_message_keeps_agent_run_id_in_memory(self):
        from services import incognito

        session = incognito.create_session(mode="jarvis")
        try:
            self._drive(session.id, incognito=True)
            history = self.client.get(f"/api/sessions/{session.id}/history").json()
            assistant = next(row for row in history["messages"] if row["role"] == "assistant")
            self.assertEqual(assistant["meta"]["agent_run_id"], "phase4-live-run")
            self.assertEqual(
                json.loads(session.messages[-1].meta)["agent_run_id"], "phase4-live-run"
            )
        finally:
            incognito.delete_session(session.id)
