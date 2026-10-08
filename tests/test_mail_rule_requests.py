"""Rule creation retries, scoped cancellation and deletion use durable identities."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, CachedMessage, MailAccount, MailRule
from routes.mail import RuleBody, add_rule, delete_rule
from tests._client import ApiTest


class RuleRequestTests(ApiTest):
    def body(self, **changes):
        return (
            dict(
                match_field="from",
                match_value="sender@example.invalid",
                action="label",
                action_arg="work",
                enabled=True,
                request_id=str(uuid4()),
            )
            | changes
        )

    def create(self, body):
        return self.client.post("/api/mail/rules", json=body)

    def rules(self):
        return self.client.get("/api/mail/rules").json()["rules"]

    def scope(self):
        return self.client.get("/api/mail/rules").json()["recovery_scopes"][0]

    def test_retry_keeps_one_rule_and_new_identity_can_create_another(self):
        body = self.body()
        first, repeated = self.create(body), self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(self.rules()), 1)
        self.assertEqual(first.json()["id"], body["request_id"])
        self.assertEqual(repeated.json(), first.json())
        self.assertNotEqual(
            self.create(body | {"request_id": str(uuid4())}).json()["id"], first.json()["id"]
        )
        self.assertEqual(len(self.rules()), 2)

    def test_conflicting_reuse_does_not_create_or_replace(self):
        body = self.body()
        saved = self.create(body).json()
        for field, value in [
            ("match_field", "subject"),
            ("match_value", "other"),
            ("action", "mute"),
            ("action_arg", "other"),
            ("enabled", False),
        ]:
            self.assertEqual(self.create(body | {field: value}).status_code, 409)
        self.assertEqual(self.rules(), [saved])

    def test_deleted_identity_stays_deleted_and_clears_content(self):
        body = self.body()
        saved = self.create(body).json()
        url = "/api/mail/rules/" + saved["id"]
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(self.rules(), [])
        with self.db() as db:
            row = db.get(MailRule, saved["id"])
            self.assertFalse(row.enabled)
            self.assertEqual((row.match_value, row.action_arg), ("", ""))
            self.assertIsNotNone(row.deleted_at)

    def test_pending_cancellation_reserves_id_before_late_creation(self):
        body = self.body(recovery_scope=self.scope())
        url = "/api/mail/rules/" + body["request_id"]
        self.assertEqual(
            self.client.delete(url, params={"recovery_scope": body["recovery_scope"]}).status_code,
            200,
        )
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(self.rules(), [])

    def test_invalid_ids_and_other_store_scopes_do_not_mutate(self):
        for identity in ["invalid", str(uuid4()).replace("-", "")]:
            self.assertEqual(self.create(self.body(request_id=identity)).status_code, 400)
        scope = self.scope()
        body = self.body(recovery_scope=scope)
        saved = self.create(body).json()
        with mock.patch("routes.mail.DB_PATH", "/owned-test/other-rules.db"):
            self.assertEqual(self.create(body).status_code, 403)
            self.assertEqual(
                self.client.delete(
                    "/api/mail/rules/" + saved["id"], params={"recovery_scope": scope}
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.delete(
                    "/api/mail/rules/" + str(uuid4()), params={"recovery_scope": scope}
                ).status_code,
                403,
            )
        self.assertEqual(self.rules(), [saved])

    def test_rotation_keeps_existing_rule_recovery_scope(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="old-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture"}),
        ):
            scope = self.scope()
        with (
            mock.patch("services.secretstore.active_key_id", return_value="new-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture", "new-fixture"}),
        ):
            self.assertEqual(self.create(self.body(recovery_scope=scope)).status_code, 200)

    def test_legacy_creation_and_missing_delete_keep_their_behavior(self):
        body = dict(
            match_field="invalid",
            match_value="  sender  ",
            action="invalid",
            action_arg="  arg  ",
            enabled=False,
        )
        first, second = self.create(body).json(), self.create(body).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(
            (
                first["match_field"],
                first["match_value"],
                first["action"],
                first["action_arg"],
                first["enabled"],
            ),
            ("from", "sender", "markread", "arg", False),
        )
        self.assertEqual(self.client.delete("/api/mail/rules/missing").status_code, 404)

    def test_deleted_rules_are_excluded_from_execution(self):
        saved = self.create(self.body(action="markread")).json()
        self.assertEqual(self.client.delete("/api/mail/rules/" + saved["id"]).status_code, 200)
        with self.db() as db:
            db.add(MailAccount(id="owned", email="self@example.invalid"))
            db.add(
                CachedMessage(
                    id="owned-message",
                    account_id="owned",
                    folder="INBOX",
                    uid="1",
                    sender="sender@example.invalid",
                    seen=False,
                )
            )
            db.commit()
        self.assertEqual(self.client.post("/api/mail/rules/run/owned").json(), {"applied": 0})
        with self.db() as db:
            self.assertFalse(db.get(CachedMessage, "owned-message").seen)

    def test_failed_commit_leaves_no_rule(self):
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("owned commit failure")):
                with self.assertRaisesRegex(RuntimeError, "owned commit failure"):
                    add_rule(RuleBody(**self.body()), db)
            self.assertEqual(db.query(MailRule).count(), 0)

    def test_concurrent_retries_and_reopen_keep_one_rule(self):
        with tempfile.TemporaryDirectory(prefix="alles-rule-requests-") as root:
            engine = create_engine("sqlite:///" + str(Path(root) / "owned.db"))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, autoflush=False)
            body, barrier = RuleBody(**self.body()), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=5)
                    return add_rule(body, db)["id"]

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    identities = [future.result(timeout=10) for future in futures]
                self.assertEqual(identities[0], identities[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(add_rule(body, db)["id"], identities[0])
                    self.assertEqual(db.query(MailRule).count(), 1)
            finally:
                engine.dispose()

    def test_early_returns_release_writer(self):
        with tempfile.TemporaryDirectory(prefix="alles-rule-release-") as root:
            engine = create_engine(
                "sqlite:///" + str(Path(root) / "owned.db"), connect_args={"timeout": 0.1}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                for case in ["replay", "conflict", "deleted", "delete", "missing-delete"]:
                    with self.subTest(case=case), sessions() as db:
                        body = RuleBody(**self.body())
                        identity = add_rule(body, db)["id"]
                        if case == "deleted":
                            delete_rule(identity, db)
                        try:
                            if case in {"replay", "deleted"}:
                                add_rule(body, db)
                            elif case == "conflict":
                                add_rule(body.model_copy(update={"action_arg": "other"}), db)
                            else:
                                delete_rule(identity if case == "delete" else "missing", db)
                        except HTTPException as error:
                            self.assertEqual(
                                error.status_code,
                                {"conflict": 409, "deleted": 410, "missing-delete": 404}[case],
                            )
                        else:
                            self.assertNotIn(case, {"conflict", "deleted", "missing-delete"})
                        with engine.begin() as other:
                            other.execute(
                                text("UPDATE mail_rules SET id=id WHERE id=:id"), {"id": identity}
                            )
            finally:
                engine.dispose()

    def test_scoped_cancellation_and_creation_can_overlap_without_reviving(self):
        scope = self.scope()
        with tempfile.TemporaryDirectory(prefix="alles-rule-cancel-") as root:
            engine = create_engine("sqlite:///" + str(Path(root) / "owned.db"))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine, autoflush=False)
            body, barrier = RuleBody(**self.body(recovery_scope=scope)), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=5)
                    try:
                        return add_rule(body, db)
                    except HTTPException as error:
                        self.assertEqual(error.status_code, 410)
                        return None

            def cancel():
                with sessions() as db:
                    barrier.wait(timeout=5)
                    return delete_rule(body.request_id, db, scope)

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    one, two = pool.submit(save), pool.submit(cancel)
                    one.result(timeout=10)
                    self.assertEqual(two.result(timeout=10), {"ok": True})
                with sessions() as db:
                    rows = db.query(MailRule).all()
                    self.assertEqual(len(rows), 1)
                    self.assertIsNotNone(rows[0].deleted_at)
                    self.assertFalse(rows[0].enabled)
                    with self.assertRaises(HTTPException) as error:
                        add_rule(body, db)
                    self.assertEqual(error.exception.status_code, 410)
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_keeps_legacy_rule_fields(self):
        from core.migrations import m0059_mail_rule_recovery

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE mail_rules (id TEXT PRIMARY KEY, match_field TEXT, match_value TEXT, action TEXT, action_arg TEXT, enabled BOOLEAN, created_at DATETIME)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO mail_rules VALUES ('old','subject','invoice','label','work',1,'2026-01-01 00:00:00')"
                    )
                )
                before = tuple(conn.execute(text("SELECT * FROM mail_rules")).one())
                m0059_mail_rule_recovery.up(conn)
                m0059_mail_rule_recovery.up(conn)
                self.assertEqual(
                    tuple(conn.execute(text("SELECT * FROM mail_rules")).one()), before + (None,)
                )
        finally:
            engine.dispose()
