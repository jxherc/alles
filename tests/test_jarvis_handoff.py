import asyncio
from unittest import mock

from core.database import JarvisRun, JarvisWorkflow, ModelEndpoint, Project, Session
from services import jarvis_handoff
from tests._client import ApiTest


class JarvisHandoffTest(ApiTest):
    def _endpoint(self, *, local=True):
        db = self.db()
        endpoint = ModelEndpoint(
            name="local" if local else "remote",
            base_url="http://127.0.0.1:11434/v1" if local else "https://models.example/v1",
            api_key="",
            enabled=True,
            cached_models='["phase4-model"]',
        )
        db.add(endpoint)
        db.commit()
        endpoint_id = endpoint.id
        db.close()
        return endpoint_id

    def _session(self, *, project=False, incognito=False):
        db = self.db()
        project_id = None
        if project:
            row = Project(name="p", working_dir="/tmp/p")
            db.add(row)
            db.flush()
            project_id = row.id
        session = Session(name="phase 4", project_id=project_id, incognito=incognito)
        db.add(session)
        db.commit()
        session_id = session.id
        db.close()
        return session_id, project_id

    def test_local_handoff_preserves_session_project_request_and_files(self):
        endpoint_id = self._endpoint(local=True)
        session_id, project_id = self._session(project=True)
        with mock.patch.object(jarvis_handoff, "launch", return_value=True) as launch:
            response = self.client.post(
                "/api/jarvis/handoffs",
                json={
                    "session_id": session_id,
                    "request": "check this project carefully",
                    "endpoint_override": endpoint_id,
                    "model_override": "phase4-model",
                    "file_ids": ["upload-1"],
                },
            )
        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.assertEqual(run["session_id"], session_id)
        self.assertEqual(run["project_id"], project_id)
        self.assertEqual(run["state"], "queued")
        self.assertEqual(run["events"][-1]["data"]["file_ids"], ["upload-1"])
        self.assertEqual(run["events"][-1]["data"]["endpoint_override"], endpoint_id)
        launch.assert_called_once_with(run["id"])
        db = self.db()
        workflow = db.get(JarvisWorkflow, run["workflow_id"])
        self.assertEqual(workflow.prompt, "check this project carefully")
        self.assertEqual(workflow.deterministic_action, jarvis_handoff.HANDOFF_ACTION)
        self.assertEqual(workflow.model_override, "phase4-model")
        self.assertEqual(workflow.context_mode, "project")
        db.close()

    def test_explicit_endpoint_survives_same_named_models(self):
        first = self._endpoint(local=True)
        second = self._endpoint(local=True)
        session_id, _ = self._session()
        preview = self.client.get(
            "/api/jarvis/handoffs/preview",
            params={
                "session_id": session_id,
                "endpoint_override": second,
                "model_override": "phase4-model",
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["endpoint_id"], second)
        self.assertNotEqual(preview.json()["endpoint_id"], first)
        with mock.patch.object(jarvis_handoff, "launch", return_value=True):
            response = self.client.post(
                "/api/jarvis/handoffs",
                json={
                    "session_id": session_id,
                    "request": "keep the exact endpoint",
                    "endpoint_override": second,
                    "model_override": "phase4-model",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][-1]["data"]["endpoint_override"], second)

    def test_queued_handoffs_resume_after_server_restart(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        run = jarvis_handoff.create_handoff(db, db.get(Session, session_id), "resume this")
        db.commit()
        run_id = run.id
        db.close()
        with mock.patch.object(jarvis_handoff, "launch", return_value=True) as launch:
            resumed = jarvis_handoff.resume_queued()
        self.assertEqual(resumed, 1)
        launch.assert_called_once_with(run_id)

    def test_remote_model_must_be_shown_and_confirmed_exactly(self):
        endpoint_id = self._endpoint(local=False)
        session_id, _ = self._session()
        preview = self.client.get(
            "/api/jarvis/handoffs/preview", params={"session_id": session_id}
        ).json()
        self.assertEqual(preview["privacy_class"], "remote")
        denied = self.client.post(
            "/api/jarvis/handoffs",
            json={"session_id": session_id, "request": "research this"},
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["code"], "remote_model_confirmation_required")
        with mock.patch.object(jarvis_handoff, "launch", return_value=True):
            allowed = self.client.post(
                "/api/jarvis/handoffs",
                json={
                    "session_id": session_id,
                    "request": "research this",
                    "confirmed_endpoint_id": endpoint_id,
                    "confirmed_model": "phase4-model",
                },
            )
        self.assertEqual(allowed.status_code, 200)

    def test_incognito_handoff_is_rejected(self):
        self._endpoint(local=True)
        session_id, _ = self._session(incognito=True)
        response = self.client.post(
            "/api/jarvis/handoffs", json={"session_id": session_id, "request": "keep this"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "incognito_handoff_forbidden")

    def test_retry_creates_a_new_run_and_uncertain_never_retries(self):
        endpoint_id = self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        session = db.get(Session, session_id)
        failed = jarvis_handoff.create_handoff(
            db,
            session,
            "try again",
            endpoint_override=endpoint_id,
            model_override="phase4-model",
        )
        failed.state = "failed"
        uncertain = jarvis_handoff.create_handoff(db, session, "do not repeat")
        uncertain.state = "uncertain"
        db.commit()
        failed_id, uncertain_id = failed.id, uncertain.id
        db.close()
        with mock.patch.object(jarvis_handoff, "launch", return_value=True):
            retried = self.client.post(f"/api/jarvis/runs/{failed_id}/retry")
        self.assertEqual(retried.status_code, 200)
        self.assertNotEqual(retried.json()["id"], failed_id)
        self.assertEqual(retried.json()["events"][-1]["data"]["endpoint_override"], endpoint_id)
        refused = self.client.post(f"/api/jarvis/runs/{uncertain_id}/retry")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "handoff_not_retryable")

    def test_queued_handoff_can_cancel_without_execution(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        run = jarvis_handoff.create_handoff(db, db.get(Session, session_id), "cancel this")
        db.commit()
        run_id = run.id
        db.close()
        response = self.client.post(f"/api/jarvis/runs/{run_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "cancelled")
        db = self.db()
        self.assertEqual(db.get(JarvisRun, run_id).state, "cancelled")
        db.close()

    def test_memory_off_blocks_reads_and_memory_tools_during_execution(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        run = jarvis_handoff.create_handoff(db, db.get(Session, session_id), "work privately")
        db.commit()
        run_id = run.id
        db.close()
        settings = jarvis_handoff.load_settings()
        settings.update({"memory_policy": "off", "disabled_tools": ["shell"]})
        captured = {}

        async def stream(*_args, **kwargs):
            captured.update(kwargs["settings"])
            yield {"delta": "finished"}

        with (
            mock.patch.object(jarvis_handoff, "inject_memories") as inject,
            mock.patch.object(jarvis_handoff, "load_settings", return_value=settings),
            mock.patch("routes.chat._build_messages", return_value=[]),
            mock.patch("routes.chat._stream_and_save", side_effect=stream),
        ):
            asyncio.run(jarvis_handoff._execute(run_id))
        inject.assert_not_called()
        self.assertEqual(captured["disabled_tools"], ["memory_add", "memory_search", "shell"])
        db = self.db()
        self.assertEqual(db.get(JarvisRun, run_id).state, "succeeded")
        db.close()


class JarvisMutationBoundaryTest(ApiTest):
    def test_memory_and_run_state_tools_are_mutations(self):
        from services.agent_tools import MUTATING_TOOLS, decide_permission

        for name in ("memory_add", "revert_file", "git_push", "delete_file"):
            with self.subTest(name=name):
                self.assertIn(name, MUTATING_TOOLS)
                self.assertEqual(decide_permission(name, {}, "plan", []), "deny")
                self.assertEqual(decide_permission(name, {}, "approve", []), "ask")
