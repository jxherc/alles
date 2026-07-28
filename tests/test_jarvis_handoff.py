import asyncio
import tempfile
from pathlib import Path
from unittest import mock

from core.database import (
    JarvisRun,
    JarvisRunEvent,
    JarvisWorkflow,
    ModelEndpoint,
    Project,
    Session,
)
from services import jarvis_handoff
from services.jarvis_store import create_run
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
                    "permission_mode": "full_auto",
                    "effort": "high",
                },
            )
        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.assertEqual(run["session_id"], session_id)
        self.assertEqual(run["project_id"], project_id)
        self.assertEqual(run["state"], "queued")
        self.assertEqual(run["events"][-1]["data"]["file_ids"], ["upload-1"])
        self.assertEqual(run["events"][-1]["data"]["endpoint_override"], endpoint_id)
        self.assertEqual(run["events"][-1]["data"]["permission_mode"], "full_auto")
        self.assertEqual(run["events"][-1]["data"]["effort"], "high")
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

    def test_scheduled_aide_work_creates_its_own_conversation_and_runs(self):
        self._endpoint(local=True)
        db = self.db()
        project = Project(name="scheduled project", working_dir="/tmp/scheduled-project")
        db.add(project)
        db.flush()
        workflow = JarvisWorkflow(
            name="morning check",
            prompt="prepare the morning check",
            project_id=project.id,
            context_mode="project",
            deterministic_action=jarvis_handoff.HANDOFF_ACTION,
            enabled=True,
        )
        db.add(workflow)
        db.flush()
        run = create_run(db, workflow)
        db.commit()
        run_id = run.id
        project_id = project.id
        db.close()

        async def stream(*_args, **_kwargs):
            yield {"delta": "scheduled work finished"}

        with (
            mock.patch("routes.chat._build_messages", return_value=[]),
            mock.patch("routes.chat._stream_and_save", side_effect=stream),
        ):
            asyncio.run(jarvis_handoff._execute(run_id))

        db = self.db()
        saved = db.get(JarvisRun, run_id)
        session = db.get(Session, saved.session_id)
        self.assertEqual(saved.state, "succeeded")
        self.assertEqual(saved.result_summary, "scheduled work finished")
        self.assertIsNotNone(session)
        self.assertEqual(session.project_id, project_id)
        self.assertEqual(session.name, "morning check")
        db.close()

    def test_deleted_legacy_session_restores_its_exact_working_folder(self):
        self._endpoint(local=True)
        with tempfile.TemporaryDirectory() as folder:
            expected = str(Path(folder).resolve())
            db = self.db()
            session = Session(name="folder handoff", working_dir=expected)
            db.add(session)
            db.flush()
            run = jarvis_handoff.create_handoff(
                db,
                session,
                "continue in this folder",
                permission_mode="full_auto",
            )
            db.commit()
            run_id = run.id
            db.delete(session)
            db.commit()
            db.close()
            captured = {}

            async def stream(*_args, **kwargs):
                captured.update(kwargs["settings"])
                yield {"delta": "folder work finished"}

            with (
                mock.patch("routes.chat._build_messages", return_value=[]),
                mock.patch("routes.chat._stream_and_save", side_effect=stream),
            ):
                asyncio.run(jarvis_handoff._execute(run_id))

            db = self.db()
            saved = db.get(JarvisRun, run_id)
            replacement = db.get(Session, saved.session_id)
            self.assertEqual(saved.state, "succeeded")
            self.assertEqual(replacement.working_dir, expected)
            self.assertEqual(captured["agent_cwd"], expected)
            db.close()

    def test_deleted_session_without_durable_context_fails_closed(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        session = db.get(Session, session_id)
        run = jarvis_handoff.create_handoff(db, session, "old ambiguous handoff")
        db.flush()
        event = db.query(JarvisRunEvent).filter_by(run_id=run.id, kind="handoff_requested").one()
        event.data = "{}"
        db.commit()
        run_id = run.id
        db.delete(session)
        db.commit()
        db.close()

        with mock.patch("routes.chat._stream_and_save") as stream:
            asyncio.run(jarvis_handoff._execute(run_id))

        stream.assert_not_called()
        db = self.db()
        saved = db.get(JarvisRun, run_id)
        self.assertEqual(saved.state, "failed")
        self.assertEqual(saved.failure_class, "missing_context")
        db.close()

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

    def test_invalid_custom_turn_limit_is_a_client_error(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        response = self.client.post(
            "/api/jarvis/handoffs",
            json={
                "session_id": session_id,
                "request": "validate this",
                "effort": "custom",
                "custom_effort": {"max_turns": []},
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "custom_max_turns_invalid")

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

    def test_retry_preserves_discord_origin_metadata(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        failed = jarvis_handoff.create_handoff(
            db,
            db.get(Session, session_id),
            "retry discord work",
            origin={
                "kind": "discord",
                "connector_id": "connector-1",
                "channel_id": "channel-1",
                "message_id": "message-1",
            },
        )
        failed.state = "failed"
        db.commit()
        retry = jarvis_handoff.retry_handoff(db, failed)
        db.commit()
        self.assertTrue(jarvis_handoff._has_discord_origin(db, retry))
        from core.database import JarvisRunEvent

        event = db.query(JarvisRunEvent).filter_by(run_id=retry.id, kind="handoff_requested").one()
        self.assertIn('"origin_channel_id":"channel-1"', event.data)
        db.close()

    def test_running_handoff_is_not_executed_again(self):
        self._endpoint(local=True)
        session_id, _ = self._session()
        db = self.db()
        run = jarvis_handoff.create_handoff(db, db.get(Session, session_id), "already running")
        run.state = "running"
        db.commit()
        run_id = run.id
        db.close()

        with mock.patch("routes.chat._stream_and_save") as stream:
            asyncio.run(jarvis_handoff._execute(run_id))

        stream.assert_not_called()

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
        run = jarvis_handoff.create_handoff(
            db,
            db.get(Session, session_id),
            "work privately",
            permission_mode="full_auto",
            effort="high",
        )
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
        self.assertEqual(captured["agent_permission_mode"], "full_auto")
        self.assertEqual(captured["agent_effort"], "high")
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
