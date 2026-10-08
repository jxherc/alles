"""Account creation, conditional edits and deletion recovery with disposable data."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, MailAccount, MailAccountDeletion, SessionLocal
from core.database_credentials import (
    _CREDENTIAL_LOCK_INFO,
    _lock_credential_session,
    _unlock_credential_session,
)
from routes.mail import AcctBody, add_account, del_account, patch_account
from services.recovery_consistency import recovery_consistency_lock
from tests._client import ApiTest


class AccountRequests(ApiTest):
    def body(self, **changes):
        return dict(
            name="owned",
            email="owned@example.invalid",
            imap_host="127.0.0.1",
            imap_port=1,
            smtp_host="127.0.0.1",
            smtp_port=1,
            username="owned",
            password="  dummy  ",
            use_ssl=False,
            **changes,
        )

    def post(self, body):
        return self.client.post("/api/mail/accounts", json=body)

    def test_same_create_retry_returns_one_account(self):
        body = self.body(request_id=str(uuid4()))
        a, b = self.post(body), self.post(body)
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.json()["id"], b.json()["id"])
        self.assertEqual(len(self.client.get("/api/mail/accounts").json()), 1)

    def test_conflicting_retry_does_not_change_account(self):
        body = self.body(request_id=str(uuid4()))
        first = self.post(body).json()
        body["name"] = "changed"
        self.assertEqual(self.post(body).status_code, 409)
        self.assertEqual(self.client.get("/api/mail/accounts").json()[0]["name"], first["name"])

    def test_late_retry_cannot_recreate_deleted_account(self):
        body = self.body(request_id=str(uuid4()))
        row = self.post(body).json()
        self.assertEqual(self.client.delete("/api/mail/accounts/" + row["id"]).status_code, 200)
        self.assertEqual(self.post(body).status_code, 410)
        self.assertEqual(self.client.get("/api/mail/accounts").json(), [])

    def test_deleted_account_retry_is_safe(self):
        row = self.post(self.body()).json()
        url = "/api/mail/accounts/" + row["id"]
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 200)

    def test_stale_edit_does_not_overwrite_newer_fields(self):
        row = self.post(self.body()).json()
        revision = row["revision"]
        url = "/api/mail/accounts/" + row["id"]
        a = self.client.patch(url, json={"name": "newest", "expected_revision": revision})
        self.assertEqual(a.status_code, 200)
        b = self.client.patch(url, json={"name": "stale", "expected_revision": revision})
        self.assertEqual(b.status_code, 409)
        self.assertEqual(self.client.get("/api/mail/accounts").json()[0]["name"], "newest")

    def test_legacy_distinct_creation_and_password_preservation(self):
        a, b = self.post(self.body()).json(), self.post(self.body()).json()
        self.assertNotEqual(a["id"], b["id"])
        self.assertNotIn("password", a)
        self.assertNotIn("oauth_access_token", a)
        self.assertEqual(
            self.client.patch(
                "/api/mail/accounts/" + a["id"], json={"name": "edited", "password": ""}
            ).status_code,
            200,
        )
        with self.db() as db:
            row = db.get(MailAccount, a["id"])
            self.assertEqual(row.password, "  dummy  ")
            self.assertFalse(row.use_ssl)

    def test_context_scopes_and_wrong_store_reject_without_mutation(self):
        result = self.client.get("/api/mail/accounts", params={"context": True}).json()
        self.assertEqual(result["accounts"], [])
        scope = result["recovery_scopes"][0]
        self.assertRegex(scope, r"^[0-9a-f]{64}$")
        body = self.body(request_id=str(uuid4()), recovery_scope=scope)
        first = self.post(body).json()
        with mock.patch("routes.mail.DB_PATH", "/owned-test/other-accounts.db"):
            self.assertEqual(self.post(body).status_code, 403)
            self.assertEqual(
                self.client.patch(
                    "/api/mail/accounts/" + first["id"],
                    json={"name": "wrong store", "recovery_scope": scope},
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.delete(
                    "/api/mail/accounts/" + first["id"], params={"recovery_scope": scope}
                ).status_code,
                403,
            )
        self.assertEqual(self.client.get("/api/mail/accounts").json(), [first])

    def test_invalid_identity_and_revision_are_rejected(self):
        for identity in ["invalid", str(uuid4()).replace("-", "")]:
            self.assertEqual(self.post(self.body(request_id=identity)).status_code, 400)
        for revision in [True, 0, -1, 1.5, "1"]:
            self.assertEqual(self.post(self.body(expected_revision=revision)).status_code, 422)
        self.assertEqual(self.post(self.body(expected_revision=1)).status_code, 400)
        self.assertEqual(self.client.get("/api/mail/accounts").json(), [])

    def test_pending_cancel_and_physical_delete_retain_only_identity(self):
        scope = self.client.get("/api/mail/accounts", params={"context": True}).json()[
            "recovery_scopes"
        ][0]
        body = self.body(request_id=str(uuid4()), recovery_scope=scope)
        url = "/api/mail/accounts/" + body["request_id"]
        self.assertEqual(self.client.delete(url, params={"recovery_scope": scope}).status_code, 200)
        self.assertEqual(self.post(body).status_code, 410)
        row = self.post(self.body()).json()
        self.assertEqual(self.client.delete("/api/mail/accounts/" + row["id"]).status_code, 200)
        with self.db() as db:
            self.assertIsNone(db.get(MailAccount, row["id"]))
            tombstones = db.query(MailAccountDeletion).all()
            self.assertEqual({r.id for r in tombstones}, {body["request_id"], row["id"]})
            self.assertTrue(all(r.deleted_at is not None for r in tombstones))
        self.assertEqual(set(MailAccountDeletion.__table__.columns.keys()), {"id", "deleted_at"})
        self.assertEqual(self.client.get("/api/mail/test/" + row["id"]).status_code, 404)
        self.assertEqual(self.client.delete("/api/mail/accounts/never-existed").status_code, 404)

    def test_changed_password_requires_current_revision_and_replay_keeps_it(self):
        row = self.post(self.body()).json()
        url = "/api/mail/accounts/" + row["id"]
        body = {"password": "  example  ", "expected_revision": row["revision"]}
        first = self.client.patch(url, json=body).json()
        self.assertEqual(first["revision"], row["revision"] + 1)
        self.assertEqual(self.client.patch(url, json=body).json(), first)
        self.assertEqual(
            self.client.patch(
                url,
                json={"password": "placeholder", "expected_revision": row["revision"]},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                url, json={"password": "", "expected_revision": row["revision"]}
            ).json(),
            first,
        )
        self.assertNotIn("password", first)
        with self.db() as db:
            self.assertEqual(db.get(MailAccount, row["id"]).password, body["password"])
        legacy = self.client.patch(url, json={"name": "legacy edit"}).json()
        self.assertEqual(legacy["revision"], first["revision"] + 1)

    def test_conditional_delete_keeps_newer_configuration(self):
        row = self.post(self.body()).json()
        url = "/api/mail/accounts/" + row["id"]
        changed = self.client.patch(url, json={"name": "changed"}).json()
        self.assertEqual(
            self.client.delete(url, params={"expected_revision": row["revision"]}).status_code, 409
        )
        self.assertEqual(self.client.get("/api/mail/accounts").json(), [changed])
        self.assertEqual(
            self.client.delete(url, params={"expected_revision": changed["revision"]}).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(url, params={"expected_revision": changed["revision"]}).status_code,
            200,
        )

    def test_oauth_configuration_replacement_invalidates_older_edits(self):
        row = self.post(self.body()).json()
        with (
            mock.patch("services.mail_oauth.check_state", return_value=True),
            mock.patch(
                "services.mail_oauth.exchange_code",
                return_value={
                    "access_token": "dummy",
                    "refresh_token": "example",
                    "expires_in": 3600,
                },
            ),
            mock.patch("services.mail_oauth.fetch_email", return_value=row["email"]),
        ):
            response = self.client.get(
                "/api/mail/oauth/google/callback?code=fixture&state=fixture", follow_redirects=False
            )
        self.assertEqual(response.status_code, 307)
        updated = self.client.get("/api/mail/accounts").json()[0]
        self.assertEqual(updated["revision"], row["revision"] + 1)
        self.assertEqual(updated["auth_type"], "oauth")
        self.assertEqual(
            self.client.patch(
                "/api/mail/accounts/" + row["id"],
                json={"name": "stale", "expected_revision": row["revision"]},
            ).status_code,
            409,
        )

    def test_failed_commit_rolls_back_creation_edit_and_deletion(self):
        with self.db() as db:
            body = AcctBody(**self.body(request_id=str(uuid4())))
            with mock.patch.object(db, "commit", side_effect=RuntimeError("owned failed commit")):
                with self.assertRaises(RuntimeError):
                    add_account(body, db)
            self.assertIsNone(db.get(MailAccount, body.request_id))
            row = add_account(body, db)
            for operation in [
                lambda: patch_account(
                    row["id"], AcctBody(name="lost", expected_revision=row["revision"]), db
                ),
                lambda: del_account(row["id"], db),
            ]:
                with mock.patch.object(
                    db, "commit", side_effect=RuntimeError("owned failed commit")
                ):
                    with self.assertRaises(RuntimeError):
                        operation()
                self.assertEqual(db.get(MailAccount, row["id"]).name, "owned")
                self.assertEqual(db.get(MailAccount, row["id"]).revision, row["revision"])
                self.assertIsNone(db.get(MailAccountDeletion, row["id"]))

    def _assert_production_session_hooks(self, sessions):
        def lock_available():
            acquired = recovery_consistency_lock.acquire(blocking=False)
            if acquired:
                recovery_consistency_lock.release()
            return acquired

        # An RLock can be reacquired by its owner; check from another thread.
        with ThreadPoolExecutor(max_workers=1) as pool:
            for finish in ("commit", "rollback"):
                with self.subTest(transaction_end=finish), sessions() as db:
                    self.assertIn(_lock_credential_session, db.dispatch.before_flush)
                    self.assertIn(_unlock_credential_session, db.dispatch.after_transaction_end)
                    row = MailAccount(name="session hook fixture")
                    db.add(row)
                    db.flush()
                    self.assertIs(db.info.get(_CREDENTIAL_LOCK_INFO), recovery_consistency_lock)
                    self.assertFalse(pool.submit(lock_available).result(timeout=5))
                    db.delete(row)
                    db.flush()
                    self.assertFalse(pool.submit(lock_available).result(timeout=5))
                    getattr(db, finish)()
                    self.assertNotIn(_CREDENTIAL_LOCK_INFO, db.info)
                    self.assertTrue(pool.submit(lock_available).result(timeout=5))

    def test_two_sessions_serialize_creation_edit_and_cancellation(self):
        scope = self.client.get("/api/mail/accounts", params={"context": True}).json()[
            "recovery_scopes"
        ][0]
        with tempfile.TemporaryDirectory(prefix="alles-account-races-") as root:
            engine = create_engine("sqlite:///" + str(Path(root) / "owned.db"))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, class_=SessionLocal.class_, autoflush=False)

            def race(*actions):
                barrier = threading.Barrier(len(actions))

                def invoke(action):
                    with sessions() as db:
                        barrier.wait(timeout=5)
                        try:
                            return action(db)
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=len(actions)) as pool:
                    futures = [pool.submit(invoke, action) for action in actions]
                    return [future.result(timeout=10) for future in futures]

            try:
                self._assert_production_session_hooks(sessions)
                body = AcctBody(**self.body(request_id=str(uuid4()), recovery_scope=scope))
                created = race(lambda db: add_account(body, db), lambda db: add_account(body, db))
                self.assertEqual(created[0], created[1])
                row = created[0]
                edited = race(
                    lambda db: patch_account(
                        row["id"], AcctBody(name="one", expected_revision=row["revision"]), db
                    ),
                    lambda db: patch_account(
                        row["id"], AcctBody(name="two", expected_revision=row["revision"]), db
                    ),
                )
                self.assertEqual(sum(item == 409 for item in edited), 1)
                other = AcctBody(**self.body(request_id=str(uuid4()), recovery_scope=scope))
                result = race(
                    lambda db: add_account(other, db),
                    lambda db: del_account(other.request_id, db, scope),
                )
                self.assertIn({"ok": True}, result)
                with sessions() as db:
                    self.assertEqual(db.query(MailAccount).count(), 1)
                    self.assertIsNone(db.get(MailAccount, other.request_id))
                    self.assertIsNotNone(db.get(MailAccountDeletion, other.request_id))
            finally:
                engine.dispose()

    def test_early_return_transactions_release_the_writer(self):
        with tempfile.TemporaryDirectory(prefix="alles-account-release-") as root:
            engine = create_engine(
                "sqlite:///" + str(Path(root) / "owned.db"), connect_args={"timeout": 0.2}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, class_=SessionLocal.class_, autoflush=False)
            try:
                self._assert_production_session_hooks(sessions)
                with sessions() as db:
                    body = AcctBody(**self.body(request_id=str(uuid4())))
                    row = add_account(body, db)
                    for action in [
                        lambda: add_account(body, db),
                        lambda: patch_account(row["id"], AcctBody(name=row["name"]), db),
                        lambda: add_account(body.model_copy(update={"name": "conflict"}), db),
                        lambda: patch_account(
                            row["id"], AcctBody(name="stale", expected_revision=999), db
                        ),
                    ]:
                        try:
                            action()
                        except HTTPException as e:
                            self.assertEqual(e.status_code, 409)
                        with engine.begin() as other:
                            other.execute(text("UPDATE mail_accounts SET id=id"))
                    del_account(row["id"], db)
                    del_account(row["id"], db)
                    with engine.begin() as other:
                        other.execute(text("UPDATE mail_accounts SET id=id"))
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_keeps_legacy_configuration(self):
        from core.migrations import m0060_mail_account_recovery

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE mail_accounts (id TEXT PRIMARY KEY, name TEXT, password TEXT, use_ssl BOOLEAN)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO mail_accounts VALUES ('old','label','sealed fixture bytes',0)"
                    )
                )
                before = tuple(conn.execute(text("SELECT * FROM mail_accounts")).one())
                m0060_mail_account_recovery.up(conn)
                m0060_mail_account_recovery.up(conn)
                self.assertEqual(
                    tuple(conn.execute(text("SELECT * FROM mail_accounts")).one()), before + (1,)
                )
                self.assertEqual(
                    [r[1] for r in conn.execute(text("PRAGMA table_info(mail_account_deletions)"))],
                    ["id", "deleted_at"],
                )
        finally:
            engine.dispose()

    def test_same_content_edit_closes_out_older_pending_configuration(self):
        row = self.client.post(
            "/api/mail/accounts",
            json={
                "name": "original",
                "email": "owned@example.invalid",
                "password": "dummy",
            },
        ).json()
        url = "/api/mail/accounts/" + row["id"]
        pending = {"name": "delayed intermediate", "expected_revision": row["revision"]}
        restored = self.client.patch(
            url, json={"name": "original", "expected_revision": row["revision"]}
        )
        self.assertEqual(restored.status_code, 200)
        delayed = self.client.patch(url, json=pending)
        self.assertEqual(
            delayed.status_code, 409, "late earlier edit overwrote the confirmed original values"
        )
        self.assertEqual(self.client.get("/api/mail/accounts").json()[0]["name"], "original")
