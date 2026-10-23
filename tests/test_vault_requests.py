"""Vault create intent recovery with disposable random secret values."""

import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import settings
from core.database import Base, Vault, VaultCreateReceipt, VaultEntry
from core.migrations import m0050_vault_create_receipts
from routes import vault
from services.crypto import make_verifier
from tests._client import ApiTest


class VaultRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.settings_dir = tempfile.TemporaryDirectory(prefix="alles-vault-requests-")
        self.settings_patch = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self.settings_dir.name) / "settings.json"
        )
        self.settings_patch.start()
        settings._clear_settings_cache()
        vault._unlock_tokens.clear()
        self.password = str(uuid.uuid4())
        response = self.client.post("/api/vault/unlock", json={"password": self.password})
        self.assertEqual(response.status_code, 200)
        self.headers = {"X-Vault-Token": response.json()["token"]}

    def tearDown(self):
        vault._unlock_tokens.clear()
        self.settings_patch.stop()
        settings._clear_settings_cache()
        self.settings_dir.cleanup()
        super().tearDown()

    def body(self, **values):
        return {
            "name": "receipt fixture",
            "fields": {"password": str(uuid.uuid4()).center(42), "notes": "first\r\nsecond"},
            "username": " fixture ",
            "type": "login",
            "category": "Login",
            "request_id": str(uuid.uuid4()),
        } | values

    def create(self, body, headers=None):
        return self.client.post("/api/vault", json=body, headers=headers or self.headers)

    def test_retry_and_intentional_repeat_preserve_exact_secret(self):
        body = self.body()
        first = self.create(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.create(body).json(), first.json())
        self.assertEqual(len(self.client.get("/api/vault", headers=self.headers).json()), 1)
        revealed = self.client.get(f"/api/vault/{first.json()['id']}/reveal", headers=self.headers)
        self.assertEqual(revealed.json()["fields"], body["fields"])
        repeated = self.create(body | {"request_id": str(uuid.uuid4())})
        self.assertNotEqual(repeated.json()["id"], first.json()["id"])
        with self.db() as db:
            self.assertEqual(db.query(VaultEntry).count(), 2)
            for entry in db.query(VaultEntry).all():
                self.assertNotIn(body["fields"]["password"], entry.value_encrypted)

    def test_changed_payload_conflicts_without_overwriting_or_duplicating(self):
        body = self.body()
        first = self.create(body).json()
        for changes in [
            {"fields": {"password": str(uuid.uuid4())}},
            {"name": "different"},
            {"username": "fixture"},
            {"category": "other"},
            {"type": "note"},
        ]:
            response = self.create(body | changes)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["entry_id"], first["id"])
        self.assertEqual(len(self.client.get("/api/vault", headers=self.headers).json()), 1)

    def test_deleted_intent_cannot_recreate_an_entry(self):
        body = self.body()
        first = self.create(body).json()
        self.assertEqual(
            self.client.delete(f"/api/vault/{first['id']}", headers=self.headers).status_code, 200
        )
        self.assertEqual(self.create(body).status_code, 410)
        self.assertEqual(self.client.get("/api/vault", headers=self.headers).json(), [])
        self.assertEqual(
            self.client.get(
                f"/api/vault/requests/{body['request_id']}", headers=self.headers
            ).status_code,
            410,
        )
        with self.db() as db:
            self.assertIsNone(db.query(VaultCreateReceipt).one().entry_id)

    def test_retry_survives_password_change_and_old_unlock_cannot_replay(self):
        body = self.body()
        first = self.create(body).json()
        changed = self.client.post(
            "/api/vault/vaults/password",
            json={"new_password": str(uuid.uuid4())},
            headers=self.headers,
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.create(body).status_code, 403)
        headers = {"X-Vault-Token": changed.json()["token"]}
        self.assertEqual(self.create(body, headers).json(), first)
        self.assertEqual(len(self.client.get("/api/vault", headers=headers).json()), 1)

    def test_same_uuid_in_two_unlocked_vaults_remains_scoped(self):
        body = self.body()
        first = self.create(body).json()
        password = str(uuid.uuid4())
        other = self.client.post(
            "/api/vault/vaults", json={"name": "other", "password": password}, headers=self.headers
        ).json()
        tok = self.client.post(
            "/api/vault/unlock", json={"password": password, "vault_id": other["id"]}
        ).json()["token"]
        headers = {"X-Vault-Token": tok}
        second = self.create(body, headers).json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.create(body, headers).json(), second)
        self.assertEqual(self.create(body).json(), first)
        self.assertEqual(
            self.client.get(f"/api/vault/requests/{body['request_id']}", headers=headers).json()[
                "id"
            ],
            second["id"],
        )
        self.assertEqual(
            self.client.delete(f"/api/vault/vaults/{other['id']}", headers=headers).status_code, 200
        )
        with self.db() as db:
            self.assertEqual(
                db.query(VaultCreateReceipt).filter_by(vault_id=other["id"]).count(), 0
            )
        self.assertEqual(self.create(body).json(), first)

    def test_legacy_calls_repeat_and_invalid_uuid_writes_nothing(self):
        body = self.body(request_id="")
        self.create(body)
        self.create(body)
        for identity in ["invalid", uuid.uuid4().hex]:
            self.assertEqual(self.create(body | {"request_id": identity}).status_code, 400)
        self.assertEqual(len(self.client.get("/api/vault", headers=self.headers).json()), 2)

    def test_recovery_reads_current_fields_and_requires_unlock(self):
        body = self.body()
        first = self.create(body).json()
        url = f"/api/vault/requests/{body['request_id']}"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.get(url, headers=self.headers).json()["fields"], body["fields"]
        )
        changed = {"password": str(uuid.uuid4())}
        self.client.patch(
            f"/api/vault/{first['id']}", json={"fields": changed}, headers=self.headers
        )
        self.assertEqual(self.client.get(url, headers=self.headers).json()["fields"], changed)
        self.assertEqual(self.create(body).status_code, 409)
        self.assertEqual(
            self.client.get("/api/vault/requests/invalid", headers=self.headers).status_code, 400
        )
        self.assertEqual(
            self.client.get(
                f"/api/vault/requests/{uuid.uuid4()}", headers=self.headers
            ).status_code,
            404,
        )
        self.assertEqual(
            set(VaultCreateReceipt.__table__.columns.keys()),
            {"id", "vault_id", "entry_id", "created_at"},
        )

    def test_failed_commit_rolls_back_entry_and_receipt_together(self):
        body = vault.CreateEntry(**self.body())
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    vault.create_entry(body, db, (self.password, "default"))
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(VaultEntry).count(), 0)
            self.assertEqual(db.query(VaultCreateReceipt).count(), 0)
        self.assertEqual(self.create(body.model_dump()).status_code, 200)

    def test_separate_connections_retry_once_without_process_lock(self):
        with tempfile.TemporaryDirectory(prefix="alles-vault-concurrent-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'vault.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            body = vault.CreateEntry(**self.body())
            barrier = threading.Barrier(2)
            try:
                with sessions() as db:
                    db.add(
                        Vault(id="default", name="fixture", verifier=make_verifier(self.password))
                    )
                    db.commit()

                def save():
                    with sessions() as db:
                        barrier.wait(timeout=10)
                        return vault.create_entry(body, db, (self.password, "default"))

                # Separate server processes cannot share this in-memory lock.
                with mock.patch.object(vault, "recovery_consistency_lock", nullcontext()):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        pending = [pool.submit(save) for _ in range(2)]
                        results = [future.result(timeout=20) for future in pending]
                self.assertEqual(results[0], results[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(
                        vault.create_entry(body, db, (self.password, "default")), results[0]
                    )
                    self.assertEqual(db.query(VaultEntry).count(), 1)
                    self.assertEqual(db.query(VaultCreateReceipt).count(), 1)
            finally:
                engine.dispose()

    def test_migration_preserves_existing_ciphertext_and_is_repeatable(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE vault_entries (id TEXT PRIMARY KEY, value_encrypted TEXT)")
                )
                ciphertext = str(uuid.uuid4())
                conn.execute(
                    text("INSERT INTO vault_entries VALUES ('existing', :ciphertext)"),
                    {"ciphertext": ciphertext},
                )
                m0050_vault_create_receipts.up(conn)
                m0050_vault_create_receipts.up(conn)
                self.assertEqual(
                    conn.execute(text("SELECT value_encrypted FROM vault_entries")).scalar(),
                    ciphertext,
                )
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM vault_create_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()
