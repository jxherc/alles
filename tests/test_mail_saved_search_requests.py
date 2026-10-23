"""Saved-search write recovery on disposable records."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, SavedSearch
from routes.mail import SavedSearchBody, add_saved_search, delete_saved_search
from tests._client import ApiTest


class SavedSearchRequestTests(ApiTest):
    def body(self, **changes):
        return (
            dict(name="owned query", query="from:fixture@example.invalid", request_id=str(uuid4()))
            | changes
        )

    def create(self, body):
        return self.client.post("/api/mail/saved-searches", json=body)

    def searches(self):
        return self.client.get("/api/mail/saved-searches").json()["searches"]

    def test_retry_returns_same_record_and_explicit_new_identity_allows_another(self):
        body = self.body()
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["id"], body["request_id"])
        self.assertEqual(self.create(body).json(), first.json())
        second = self.create(body | {"request_id": str(uuid4())})
        self.assertNotEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(len(self.searches()), 2)

    def test_changed_name_or_query_conflicts_without_overwriting(self):
        body = self.body()
        original = self.create(body).json()
        for changes in [{"name": "different"}, {"query": "different"}]:
            self.assertEqual(self.create(body | changes).status_code, 409)
        self.assertEqual(self.searches(), [original])

    def test_deleted_identity_does_not_recreate_and_clears_the_saved_content(self):
        body = self.body()
        saved = self.create(body).json()
        url = "/api/mail/saved-searches/" + saved["id"]
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(self.searches(), [])
        with self.db() as db:
            tombstone = db.get(SavedSearch, saved["id"])
            self.assertEqual((tombstone.name, tombstone.query), ("", ""))
            self.assertIsNotNone(tombstone.deleted_at)

    def test_invalid_identity_and_empty_name_do_not_create(self):
        for changes in [
            {"request_id": "invalid"},
            {"request_id": str(uuid4()).replace("-", "")},
            {"name": "  "},
        ]:
            self.assertEqual(self.create(self.body(**changes)).status_code, 400)
        self.assertEqual(self.searches(), [])

    def test_legacy_requests_and_whitespace_keep_their_existing_behavior(self):
        body = {"name": "  owned query  ", "query": "  subject:project  "}
        first, second = self.create(body).json(), self.create(body).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual((first["name"], first["query"]), ("owned query", "subject:project"))
        self.assertEqual(len(self.searches()), 2)
        self.assertEqual(self.client.delete("/api/mail/saved-searches/missing").status_code, 404)

    def test_pending_save_is_bound_to_the_selected_mail_store(self):
        scope = self.client.get("/api/mail/saved-searches").json()["recovery_scopes"][0]
        body = self.body(recovery_scope=scope)
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        with mock.patch("routes.mail.DB_PATH", "/owned-test/different-store.db"):
            self.assertEqual(self.create(body).status_code, 403)
            self.assertEqual(
                self.client.delete(
                    "/api/mail/saved-searches/" + first.json()["id"],
                    params={"recovery_scope": scope},
                ).status_code,
                403,
            )
            self.assertNotIn(
                scope, self.client.get("/api/mail/saved-searches").json()["recovery_scopes"]
            )
        self.assertEqual(self.create(body).json(), first.json())

    def test_key_rotation_retains_the_pending_save_scope(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="old-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture"}),
        ):
            scope = self.client.get("/api/mail/saved-searches").json()["recovery_scopes"][0]
        with (
            mock.patch("services.secretstore.active_key_id", return_value="new-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture", "new-fixture"}),
        ):
            scopes = self.client.get("/api/mail/saved-searches").json()["recovery_scopes"]
            self.assertNotEqual(scopes[0], scope)
            self.assertIn(scope, scopes)
            self.assertEqual(self.create(self.body(recovery_scope=scope)).status_code, 200)

    def test_failed_commit_leaves_no_saved_record(self):
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("owned failed commit")):
                with self.assertRaisesRegex(RuntimeError, "owned failed commit"):
                    add_saved_search(SavedSearchBody(**self.body()), db)
            self.assertEqual(db.query(SavedSearch).count(), 0)

    def test_concurrent_retries_and_database_reopen_return_one_record(self):
        with tempfile.TemporaryDirectory(prefix="alles-saved-search-concurrent-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'searches.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            body, barrier = SavedSearchBody(**self.body()), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=10)
                    return add_saved_search(body, db)["id"]

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    identities = [future.result(timeout=20) for future in futures]
                self.assertEqual(identities[0], identities[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(add_saved_search(body, db)["id"], identities[0])
                    self.assertEqual(db.query(SavedSearch).count(), 1)
            finally:
                engine.dispose()

    def test_replays_errors_and_deletion_release_write_before_dependency_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="alles-saved-search-reservation-") as root:
            engine = create_engine(
                f"sqlite:///{Path(root) / 'searches.db'}", connect_args={"timeout": 0.1}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                for case in ["replay", "changed", "deleted", "delete", "missing-delete"]:
                    with self.subTest(case=case), sessions() as db:
                        body = SavedSearchBody(**self.body())
                        identity = add_saved_search(body, db)["id"]
                        if case == "deleted":
                            delete_saved_search(identity, db)
                        try:
                            if case in {"replay", "deleted"}:
                                add_saved_search(body, db)
                            elif case == "changed":
                                add_saved_search(body.model_copy(update={"query": "changed"}), db)
                            else:
                                delete_saved_search(identity if case == "delete" else "missing", db)
                        except HTTPException as error:
                            self.assertEqual(
                                error.status_code,
                                {"changed": 409, "deleted": 410, "missing-delete": 404}[case],
                            )
                        else:
                            self.assertNotIn(case, {"changed", "deleted", "missing-delete"})
                        with engine.begin() as other:
                            other.execute(
                                text("UPDATE mail_saved_searches SET id=id WHERE id=:id"),
                                {"id": identity},
                            )
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_keeps_existing_searches(self):
        from core.migrations import m0056_mail_saved_search_recovery

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE mail_saved_searches (id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT, created_at DATETIME)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO mail_saved_searches (id,name,query) VALUES ('old','my search','subject:old')"
                    )
                )
                m0056_mail_saved_search_recovery.up(conn)
                m0056_mail_saved_search_recovery.up(conn)
                self.assertEqual(
                    tuple(
                        conn.execute(
                            text("SELECT id,name,query,deleted_at FROM mail_saved_searches")
                        ).one()
                    ),
                    ("old", "my search", "subject:old", None),
                )
        finally:
            engine.dispose()
