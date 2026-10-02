"""Exact Aide retry identities and delegated approval detail reads."""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import close_all_sessions
from starlette.testclient import TestClient

from app import app
from core.database import Base, DelegatedAction, JarvisRun, Session, SessionLocal
from services import jarvis_handoff
from tests._client import ApiTest


class AideRunRecoveryTest(ApiTest):
    def _failed(self):
        with self.db() as db:
            session = Session(name="owned recovery")
            db.add(session)
            db.flush()
            run = jarvis_handoff.create_handoff(db, session, "check the owned fixture")
            run.state = "failed"
            db.commit()
            return run.id

    def test_repeated_identity_returns_current_child_without_relaunch(self):
        parent = self._failed()
        identity = str(uuid4())
        with mock.patch.object(jarvis_handoff, "launch", return_value=True) as launch:
            first = self.client.post(
                f"/api/jarvis/runs/{parent}/retry", json={"request_id": identity}
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["id"], identity)
            with self.db() as db:
                child = db.get(JarvisRun, identity)
                child.state = "succeeded"
                child.result_summary = "verified result"
                db.commit()
            second = self.client.post(
                f"/api/jarvis/runs/{parent}/retry", json={"request_id": identity}
            )
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["state"], "succeeded")
            self.assertEqual(second.json()["result_summary"], "verified result")
            self.assertEqual(second.json()["title"], "check the owned fixture")
            self.assertFalse(second.json()["can_retry"])
            launch.assert_called_once_with(identity)
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 2)

    def test_identity_cannot_be_reused_for_another_parent_or_existing_run(self):
        first, second = self._failed(), self._failed()
        identity = str(uuid4())
        with mock.patch.object(jarvis_handoff, "launch", return_value=True):
            self.assertEqual(
                self.client.post(
                    f"/api/jarvis/runs/{first}/retry", json={"request_id": identity}
                ).status_code,
                200,
            )
            for parent, request_id in [(second, identity), (first, first)]:
                response = self.client.post(
                    f"/api/jarvis/runs/{parent}/retry", json={"request_id": request_id}
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["code"], "retry_identity_conflict")
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 3)

    def test_invalid_identity_and_uncertain_parent_never_create_a_child(self):
        parent = self._failed()
        for identity in ["bad", uuid4().hex]:
            response = self.client.post(
                f"/api/jarvis/runs/{parent}/retry", json={"request_id": identity}
            )
            self.assertEqual(response.status_code, 400)
        with self.db() as db:
            db.get(JarvisRun, parent).state = "uncertain"
            db.commit()
        response = self.client.post(
            f"/api/jarvis/runs/{parent}/retry", json={"request_id": str(uuid4())}
        )
        self.assertEqual(response.status_code, 409)
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 1)

    def test_two_connections_retry_one_identity_once_and_release_reservations(self):
        with tempfile.TemporaryDirectory(prefix="alles-aide-retry-") as root:
            engine = create_engine(
                f"sqlite:///{Path(root) / 'test.db'}",
                connect_args={"check_same_thread": False, "timeout": 3},
            )
            Base.metadata.create_all(engine)
            SessionLocal.configure(bind=engine)
            try:
                parent = self._failed()
                identity = str(uuid4())

                # No app lifespan in the test clients: only the explicit API calls run.
                def request():
                    client = TestClient(app)
                    try:
                        return client.post(
                            f"/api/jarvis/runs/{parent}/retry", json={"request_id": identity}
                        )
                    finally:
                        client.close()

                with mock.patch.object(jarvis_handoff, "launch", return_value=True) as launch:
                    with ThreadPoolExecutor(max_workers=2) as workers:
                        responses = list(workers.map(lambda _: request(), range(2)))
                    self.assertEqual([response.status_code for response in responses], [200, 200])
                    self.assertEqual({response.json()["id"] for response in responses}, {identity})
                    launch.assert_called_once_with(identity)
                with self.db() as db:
                    self.assertEqual(db.query(JarvisRun).count(), 2)
                    db.query(JarvisRun).filter_by(id=parent).update(
                        {JarvisRun.safe_error: "still writable"}
                    )
                    db.commit()
            finally:
                close_all_sessions()
                SessionLocal.configure(bind=self.eng)
                engine.dispose()

    def test_exact_approval_lookup_returns_the_selected_action(self):
        parent = self._failed()
        with self.db() as db:
            action = DelegatedAction(
                origin="aide",
                run_id=parent,
                scope_kind="general",
                capability="files",
                action="write_file",
                target="/owned/fixture.txt",
                exact_hash="a" * 64,
                data_summary="fixture data",
                privacy_effect="writes the selected file",
                cost="none",
                state="pending",
                expires_at=datetime.now() + timedelta(minutes=5),
            )
            db.add(action)
            db.commit()
            action_id = action.id
        response = self.client.get(f"/api/delegation/actions/{action_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], parent)
        self.assertEqual(response.json()["exact_hash"], "a" * 64)
        self.assertEqual(response.json()["target"], "/owned/fixture.txt")
        self.assertEqual(self.client.get("/api/delegation/actions/missing").status_code, 404)
