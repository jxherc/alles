"""Attachment request recovery using owned random fixtures only."""

import asyncio
import io
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from fastapi import UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import settings
from core.database import Base, Vault, VaultAttachment, VaultEntry, VaultUploadReceipt
from core.migrations import m0053_vault_upload_receipts
from routes import vault
from services.crypto import make_verifier
from tests._client import ApiTest


class VaultUploadRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-vault-upload-requests-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.attachments = root / "attachments"
        self.attachments.mkdir()
        self.settings_patch = mock.patch.object(settings, "_SETTINGS_FILE", root / "settings.json")
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.attach_patch = mock.patch.object(vault, "_attach_dir", return_value=self.attachments)
        self.attach_patch.start()
        self.addCleanup(self.attach_patch.stop)
        settings._clear_settings_cache()
        self.addCleanup(settings._clear_settings_cache)
        vault._unlock_tokens.clear()
        self.addCleanup(vault._unlock_tokens.clear)
        self.password = str(uuid.uuid4())
        opened = self.client.post("/api/vault/unlock", json={"password": self.password})
        self.assertEqual(opened.status_code, 200)
        self.headers = {"X-Vault-Token": opened.json()["token"]}
        self.eid = self.entry()
        self.identity = str(uuid.uuid4())
        self.content = uuid.uuid4().bytes + b"\x00\xff\r\n"

    def entry(self, headers=None):
        response = self.client.post(
            "/api/vault",
            headers=headers or self.headers,
            json={
                "name": "owned upload fixture",
                "type": "note",
                "fields": {"note": str(uuid.uuid4())},
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["id"]

    def upload(self, identity=None, data=None, name="fixture.bin", eid=None, headers=None):
        return self.client.post(
            "/api/vault/" + (eid or self.eid) + "/attachments",
            headers=headers or self.headers,
            data={"request_id": self.identity if identity is None else identity},
            files={
                "file": (name, self.content if data is None else data, "application/octet-stream")
            },
        )

    def test_same_identity_replays_exact_bytes_without_another_file(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.upload().json(), first.json())
        self.assertEqual(len(list(self.attachments.iterdir())), 1)
        download = self.client.get(
            "/api/vault/attachments/" + first.json()["id"], headers=self.headers
        )
        self.assertEqual(download.content, self.content)
        self.assertNotIn(self.content, next(self.attachments.iterdir()).read_bytes())

    def test_changed_content_name_or_entry_conflicts(self):
        self.assertEqual(self.upload().status_code, 200)
        for change in [{"data": b"changed"}, {"name": "changed.bin"}, {"eid": self.entry()}]:
            with self.subTest(change=list(change)):
                self.assertEqual(self.upload(**change).status_code, 409)
        self.assertEqual(len(list(self.attachments.iterdir())), 1)

    def test_deleted_attachment_cannot_be_recreated_by_retry(self):
        aid = self.upload().json()["id"]
        self.assertEqual(
            self.client.delete("/api/vault/attachments/" + aid, headers=self.headers).status_code,
            200,
        )
        self.assertEqual(self.upload().status_code, 410)
        self.assertEqual(list(self.attachments.iterdir()), [])

    def test_invalid_identity_does_not_create_a_file(self):
        self.assertEqual(self.upload(identity="invalid").status_code, 400)
        self.assertEqual(list(self.attachments.iterdir()), [])

    def test_new_identity_and_legacy_allow_intentional_repeats(self):
        ids = [
            self.upload(identity=value).json()["id"]
            for value in [self.identity, str(uuid.uuid4()), "", ""]
        ]
        self.assertEqual(len(set(ids)), 4)

    def test_rekey_preserves_receipt_and_rejects_old_unlock(self):
        first = self.upload().json()
        changed = self.client.post(
            "/api/vault/vaults/password",
            headers=self.headers,
            json={"new_password": str(uuid.uuid4())},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(
            self.upload(headers={"X-Vault-Token": changed.json()["token"]}).json(), first
        )

    def test_deleted_entry_does_not_leave_files_or_allow_replay(self):
        self.upload()
        self.assertEqual(
            self.client.delete("/api/vault/" + self.eid, headers=self.headers).status_code, 200
        )
        self.assertIn(self.upload().status_code, [404, 410])
        self.assertEqual(list(self.attachments.iterdir()), [])

    def test_receipt_contains_no_content_or_fingerprints(self):
        self.upload()
        self.assertEqual(
            set(VaultUploadReceipt.__table__.columns.keys()),
            {"vault_id", "id", "attachment_id", "created_at"},
        )
        with self.db() as db:
            receipt = db.query(VaultUploadReceipt).one()
            self.assertEqual(receipt.id, self.identity)
            self.client.delete(
                "/api/vault/attachments/" + receipt.attachment_id, headers=self.headers
            )
        with self.db() as db:
            self.assertIsNone(db.query(VaultUploadReceipt).one().attachment_id)

    def test_same_identity_is_vault_scoped_and_deleted_vault_cleans_receipts(self):
        first = self.upload().json()
        password = str(uuid.uuid4())
        other = self.client.post(
            "/api/vault/vaults", headers=self.headers, json={"name": "other", "password": password}
        ).json()
        opened = self.client.post(
            "/api/vault/unlock", json={"password": password, "vault_id": other["id"]}
        )
        headers = {"X-Vault-Token": opened.json()["token"]}
        eid = self.entry(headers)
        self.assertEqual(self.upload(headers=headers).status_code, 404)
        second = self.upload(eid=eid, headers=headers).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.upload(eid=eid, headers=headers).json(), second)
        self.assertEqual(
            self.client.delete("/api/vault/vaults/" + other["id"], headers=headers).status_code, 200
        )
        with self.db() as db:
            self.assertEqual(
                db.query(VaultUploadReceipt).filter_by(vault_id=other["id"]).count(), 0
            )
        self.assertEqual(self.upload().json(), first)

    def test_failed_commit_rolls_back_receipt_and_removes_new_file(self):
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    asyncio.run(
                        vault.add_attachment(
                            self.eid,
                            UploadFile(file=io.BytesIO(self.content), filename="fixture.bin"),
                            db=db,
                            ctx=(self.password, "default"),
                            request_id=self.identity,
                        )
                    )
        self.assertEqual(list(self.attachments.iterdir()), [])
        with self.db() as db:
            self.assertEqual(db.query(VaultAttachment).count(), 0)
            self.assertEqual(db.query(VaultUploadReceipt).count(), 0)
        self.assertEqual(self.upload().status_code, 200)

    def test_independent_connections_create_one_upload_and_reopen_replays(self):
        engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'concurrent.db'}")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        barrier = threading.Barrier(3)
        try:
            with sessions() as db:
                db.add(Vault(id="default", name="fixture", verifier=make_verifier(self.password)))
                db.add(VaultEntry(id=self.eid, vault_id="default", name="fixture"))
                db.commit()

            def save(wait=True):
                with sessions() as db:
                    if wait:
                        barrier.wait(timeout=10)
                    return asyncio.run(
                        vault.add_attachment(
                            self.eid,
                            UploadFile(file=io.BytesIO(self.content), filename="fixture.bin"),
                            db=db,
                            ctx=(self.password, "default"),
                            request_id=self.identity,
                        )
                    )

            with mock.patch.object(vault, "recovery_consistency_lock", nullcontext()):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(save) for _ in range(3)]
                    results = [future.result(timeout=20) for future in futures]
            self.assertEqual(results, [results[0]] * 3)
            engine.dispose()
            self.assertEqual(save(False), results[0])
            self.assertEqual(len(list(self.attachments.iterdir())), 1)
            with sessions() as db:
                self.assertEqual(db.query(VaultUploadReceipt).count(), 1)
                self.assertEqual(db.query(VaultAttachment).count(), 1)
        finally:
            engine.dispose()

    def test_migration_preserves_old_attachment_rows_and_is_repeatable(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE vault_attachments (id TEXT PRIMARY KEY, filename TEXT)")
                )
                conn.execute(
                    text("INSERT INTO vault_attachments VALUES ('existing','fixture.bin')")
                )
                m0053_vault_upload_receipts.up(conn)
                m0053_vault_upload_receipts.up(conn)
                self.assertEqual(
                    conn.execute(text("SELECT filename FROM vault_attachments")).scalar(),
                    "fixture.bin",
                )
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM vault_upload_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()
