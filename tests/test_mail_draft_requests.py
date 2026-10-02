"""Draft retry and concurrency contracts on disposable records."""

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, MailDraft
from routes.mail import DraftBody, delete_draft, save_draft
from tests._client import ApiTest


class DraftRequestTests(ApiTest):
    def body(self, **changes):
        return (
            dict(
                account_id="owned-account",
                to="recipient@example.invalid",
                cc="copy@example.invalid",
                bcc="hidden@example.invalid",
                subject="  owned 中文  ",
                body='<p>exact <a href="https://example.invalid/source">body</a></p>\r\n',
                in_reply_to="<source@example.invalid>",
                references="<older@example.invalid> <source@example.invalid>",
                request_id=str(uuid4()),
            )
            | changes
        )

    def save(self, body):
        return self.client.post("/api/mail/drafts", json=body)

    def update(self, saved, **changes):
        return (
            {k: v for k, v in saved.items() if k not in {"updated_at", "revision"}}
            | {"expected_revision": saved["revision"]}
            | changes
        )

    def test_create_replay_is_same_exact_record_and_new_identity_is_distinct(self):
        body = self.body()
        first = self.save(body).json()
        self.assertEqual(first["id"], body["request_id"])
        self.assertEqual(self.save(body).json(), first)
        for key, value in body.items():
            if key != "request_id":
                self.assertEqual(first[key], value)
        self.assertNotEqual(
            self.save(body | {"request_id": str(uuid4())}).json()["id"], first["id"]
        )
        self.assertEqual(len(self.client.get("/api/mail/drafts").json()), 2)

    def test_create_replay_cannot_overwrite_changed_content_or_recreate_deleted(self):
        body = self.body()
        first = self.save(body).json()
        later = self.save(self.update(first, body="later")).json()
        self.assertEqual(self.save(body).status_code, 409)
        self.assertEqual(self.client.get("/api/mail/drafts/" + first["id"]).json(), later)
        self.assertEqual(self.client.delete("/api/mail/drafts/" + first["id"]).status_code, 200)
        self.assertEqual(self.save(body).status_code, 410)
        self.assertEqual(self.save(self.update(later, body="attempt revival")).status_code, 410)
        self.assertEqual(self.client.get("/api/mail/drafts").json(), [])
        self.assertEqual(self.client.get("/api/mail/drafts/" + first["id"]).status_code, 404)
        with self.db() as db:
            row = db.get(MailDraft, first["id"])
            self.assertIsNotNone(row.deleted_at)
            self.assertEqual(
                [
                    getattr(row, k)
                    for k in [
                        "account_id",
                        "to",
                        "cc",
                        "bcc",
                        "subject",
                        "body",
                        "in_reply_to",
                        "references",
                    ]
                ],
                [""] * 8,
            )

    def test_update_replay_has_stable_version_but_stale_changes_conflict(self):
        first = self.save(self.body()).json()
        body = self.update(first, body="second")
        second = self.save(body).json()
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(self.save(body).json(), second)
        self.assertEqual(self.save(self.update(first, subject="stale")).status_code, 409)
        self.assertEqual(self.client.get("/api/mail/drafts/" + first["id"]).json(), second)

    def test_every_saved_field_is_part_of_revision_and_replay_comparison(self):
        for field in [
            "account_id",
            "to",
            "cc",
            "bcc",
            "subject",
            "body",
            "in_reply_to",
            "references",
        ]:
            with self.subTest(field=field):
                body = self.body()
                first = self.save(body).json()
                changed = self.save(self.update(first, **{field: "changed"})).json()
                self.assertNotEqual(changed["revision"], first["revision"])
                self.assertEqual(self.save(body).status_code, 409)

    def test_stale_delete_keeps_later_edits_and_confirmed_delete_is_replayable(self):
        first = self.save(self.body()).json()
        later = self.save(self.update(first, body="later")).json()
        url = "/api/mail/drafts/" + first["id"]
        self.assertEqual(
            self.client.delete(url, params={"expected_revision": first["revision"]}).status_code,
            409,
        )
        self.assertEqual(self.client.get(url).json(), later)
        params = {"expected_revision": later["revision"]}
        self.assertEqual(self.client.delete(url, params=params).status_code, 200)
        self.assertEqual(self.client.delete(url, params=params).status_code, 200)

    def test_invalid_and_missing_update_metadata_never_create(self):
        for changes in [
            {"request_id": "invalid"},
            {"request_id": str(uuid4()).replace("-", "")},
            {"id": "old"},
            {"expected_revision": "0" * 64},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.save(self.body(**changes)).status_code, 400)
        for changes in [
            {"request_id": "", "expected_revision": "bad", "id": "unknown"},
            {"request_id": "", "expected_revision": "0" * 64},
        ]:
            self.assertEqual(self.save(self.body(**changes)).status_code, 400)
        self.assertEqual(
            self.save(
                self.body(request_id="", id="unknown", expected_revision="0" * 64)
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                "/api/mail/drafts/missing", params={"expected_revision": "0" * 64}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/mail/drafts").json(), [])

    def test_legacy_array_create_and_missing_delete_stay_compatible(self):
        body = self.body(request_id="")
        first = self.save(body).json()
        second = self.save(body).json()
        self.assertNotEqual(first["id"], second["id"])
        third = self.save(body | {"id": "unknown"}).json()
        self.assertNotEqual(third["id"], "unknown")
        self.assertIsInstance(self.client.get("/api/mail/drafts").json(), list)
        self.assertEqual(self.client.delete("/api/mail/drafts/unknown").json(), {"ok": True})
        self.assertEqual(
            self.save(body | {"id": first["id"], "body": "legacy update"}).json()["id"], first["id"]
        )

    def test_context_filters_rows_and_store_scope_protects_reads_and_writes(self):
        info = self.client.get("/api/mail/drafts?context=true").json()
        scope = info["recovery_scopes"][0]
        body = self.body(recovery_scope=scope)
        saved = self.save(body).json()
        url = "/api/mail/drafts/" + saved["id"]
        self.assertEqual(
            self.client.get(
                "/api/mail/drafts", params={"context": True, "account_id": "another"}
            ).json()["drafts"],
            [],
        )
        self.assertEqual(self.client.get("/api/mail/drafts").json(), [saved])
        with mock.patch("routes.mail.DB_PATH", "/owned-fixture/other.db"):
            self.assertEqual(self.save(body).status_code, 403)
            self.assertEqual(
                self.client.get(url, params={"recovery_scope": scope}).status_code, 403
            )
            self.assertEqual(
                self.client.delete(url, params={"recovery_scope": scope}).status_code, 403
            )
        self.assertEqual(self.save(body).json(), saved)
        search_scope = self.client.get("/api/mail/saved-searches").json()["recovery_scopes"][0]
        self.assertNotEqual(scope, search_scope)

    def test_rotation_accepts_previous_store_scope(self):
        with (
            mock.patch("services.secretstore.active_key_id", return_value="old-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture"}),
        ):
            scope = self.client.get("/api/mail/drafts?context=true").json()["recovery_scopes"][0]
        with (
            mock.patch("services.secretstore.active_key_id", return_value="new-fixture"),
            mock.patch("services.secretstore.key_ids", return_value={"old-fixture", "new-fixture"}),
        ):
            scopes = self.client.get("/api/mail/drafts?context=true").json()["recovery_scopes"]
            self.assertNotEqual(scope, scopes[0])
            self.assertIn(scope, scopes)
            self.assertEqual(self.save(self.body(recovery_scope=scope)).status_code, 200)

    def test_failed_commit_rolls_back_created_or_updated_records(self):
        for existing in [False, True]:
            with self.subTest(existing=existing), self.db() as db:
                body = DraftBody(**self.body())
                first = save_draft(body, db) if existing else None
                request = DraftBody(**self.update(first, body="changed")) if first else body
                with mock.patch.object(db, "commit", side_effect=RuntimeError("owned failure")):
                    with self.assertRaisesRegex(RuntimeError, "owned failure"):
                        save_draft(request, db)
                if first:
                    self.assertEqual(db.get(MailDraft, first["id"]).body, first["body"])
                else:
                    self.assertIsNone(db.get(MailDraft, body.request_id))

    def test_concurrent_create_and_stale_update_are_serialized_across_connections(self):
        with tempfile.TemporaryDirectory(prefix="alles-draft-concurrent-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'drafts.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)

            def race(requests):
                barrier = threading.Barrier(2)

                def save(request):
                    with sessions() as db:
                        barrier.wait(timeout=10)
                        try:
                            return save_draft(DraftBody(**request), db)
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    return [f.result(timeout=20) for f in [pool.submit(save, r) for r in requests]]

            try:
                body = self.body()
                created = race([body, body])
                self.assertEqual(created[0], created[1])
                first = created[0]
                results = race([self.update(first, body="a"), self.update(first, body="b")])
                self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
                self.assertIn(409, results)
                engine.dispose()
                with sessions() as db:
                    current = next(r for r in results if isinstance(r, dict))
                    self.assertEqual(save_draft(DraftBody(**self.update(current)), db), current)
                    self.assertEqual(db.query(MailDraft).count(), 1)
            finally:
                engine.dispose()

    def test_replays_and_rejections_release_the_write_reservation(self):
        with tempfile.TemporaryDirectory(prefix="alles-draft-reservation-") as root:
            engine = create_engine(
                f"sqlite:///{Path(root) / 'drafts.db'}", connect_args={"timeout": 0.1}
            )
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                for case in [
                    "create-replay",
                    "update-replay",
                    "create-conflict",
                    "stale-update",
                    "stale-delete",
                    "delete",
                    "missing-delete",
                    "deleted-create",
                ]:
                    with self.subTest(case=case), sessions() as db:
                        body = DraftBody(**self.body())
                        first = save_draft(body, db)
                        second = save_draft(DraftBody(**self.update(first, body="later")), db)
                        try:
                            if case == "create-replay":
                                save_draft(
                                    DraftBody(**self.body(request_id=first["id"], body="later")), db
                                )
                            elif case == "update-replay":
                                save_draft(DraftBody(**self.update(first, body="later")), db)
                            elif case == "create-conflict":
                                save_draft(body, db)
                            elif case == "stale-update":
                                save_draft(DraftBody(**self.update(first, body="third")), db)
                            elif case == "stale-delete":
                                delete_draft(first["id"], db, expected_revision=first["revision"])
                            elif case == "delete":
                                delete_draft(first["id"], db, expected_revision=second["revision"])
                            elif case == "missing-delete":
                                delete_draft("missing", db)
                            else:
                                delete_draft(first["id"], db)
                                save_draft(body, db)
                        except HTTPException as error:
                            expected = {
                                "create-conflict": 409,
                                "stale-update": 409,
                                "stale-delete": 409,
                                "deleted-create": 410,
                            }
                            self.assertIn(case, expected)
                            self.assertEqual(error.status_code, expected[case])
                        else:
                            self.assertNotIn(
                                case,
                                {
                                    "create-conflict",
                                    "stale-update",
                                    "stale-delete",
                                    "deleted-create",
                                },
                            )
                        with engine.begin() as other:
                            other.execute(
                                text("UPDATE mail_drafts SET id=id WHERE id=:id"),
                                {"id": first["id"]},
                            )
            finally:
                engine.dispose()

    def test_concurrent_delete_and_update_have_one_winner(self):
        with tempfile.TemporaryDirectory(prefix="alles-draft-delete-race-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'drafts.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                with sessions() as db:
                    first = save_draft(DraftBody(**self.body()), db)
                barrier = threading.Barrier(2)

                def mutate(remove):
                    with sessions() as db:
                        barrier.wait(timeout=10)
                        try:
                            if remove:
                                return delete_draft(
                                    first["id"], db, expected_revision=first["revision"]
                                )
                            return save_draft(
                                DraftBody(**self.update(first, body="later concurrent edit")), db
                            )
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(mutate, value) for value in [True, False]]
                    deleted, updated = [future.result(timeout=20) for future in futures]
                with sessions() as db:
                    row = db.get(MailDraft, first["id"])
                    if isinstance(deleted, dict):
                        self.assertEqual(deleted, {"ok": True})
                        self.assertEqual(updated, 410)
                        self.assertIsNotNone(row.deleted_at)
                        self.assertEqual(row.body, "")
                    else:
                        self.assertEqual(deleted, 409)
                        self.assertIsInstance(updated, dict)
                        self.assertIsNone(row.deleted_at)
                        self.assertEqual(row.body, "later concurrent edit")
            finally:
                engine.dispose()

    def test_migration_twice_preserves_existing_body_and_timestamp(self):
        from core.migrations import m0057_mail_draft_recovery

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE mail_drafts (id TEXT PRIMARY KEY, body TEXT, updated_at DATETIME)"
                    )
                )
                conn.execute(
                    text("INSERT INTO mail_drafts VALUES (:id,:body,:date)"),
                    {"id": "old", "body": "  old\r\n中文  ", "date": "2026-01-02 03:04:05"},
                )
                m0057_mail_draft_recovery.up(conn)
                m0057_mail_draft_recovery.up(conn)
                self.assertEqual(
                    tuple(
                        conn.execute(
                            text("SELECT id,body,updated_at,deleted_at FROM mail_drafts")
                        ).one()
                    ),
                    ("old", "  old\r\n中文  ", "2026-01-02 03:04:05", None),
                )
        finally:
            engine.dispose()
