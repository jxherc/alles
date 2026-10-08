import tempfile
import uuid
from pathlib import Path
from unittest import mock

from core import settings
from core.database import Vault, VaultEntry
from routes import vault
from services.crypto import make_verifier
from tests._client import ApiTest


class VaultSetupTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory(prefix="alles-vault-setup-")
        self.setting_patch = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self.directory.name) / "settings.json"
        )
        self.setting_patch.start()
        settings._clear_settings_cache()
        vault._unlock_tokens.clear()

    def tearDown(self):
        vault._unlock_tokens.clear()
        self.setting_patch.stop()
        settings._clear_settings_cache()
        self.directory.cleanup()
        super().tearDown()

    def status(self):
        response = self.client.get("/api/vault/setup")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_empty_default_reports_setup_without_creating_anything(self):
        self.assertEqual(self.status(), {"state": "setup", "minimum_password_length": 12})
        with self.db() as db:
            self.assertEqual(db.query(Vault).count(), 0)
        self.assertEqual(vault._unlock_tokens, {})

    def test_initialized_default_reports_unlock_without_revealing_verifier(self):
        password = str(uuid.uuid4())
        response = self.client.post("/api/vault/unlock", json={"password": password})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status(), {"state": "locked", "minimum_password_length": 12})

    def test_legacy_settings_verifier_reports_unlock_without_database_creation(self):
        settings.save_settings({"vault_verifier": make_verifier(str(uuid.uuid4()))})
        self.assertEqual(self.status()["state"], "locked")
        with self.db() as db:
            self.assertEqual(db.query(Vault).count(), 0)

    def test_existing_data_without_verifier_requires_recovery(self):
        with self.db() as db:
            db.add(Vault(id="default", name="Personal", verifier="", travel_safe=True))
            db.add(
                VaultEntry(
                    vault_id="default", name="existing", value_encrypted="fixture ciphertext"
                )
            )
            db.commit()
        self.assertEqual(self.status()["state"], "recovery")
        response = self.client.post("/api/vault/unlock", json={"password": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 409)

    def test_second_factor_without_verifier_requires_recovery(self):
        settings.save_settings({"vault_require_2fa": {"default": True}})
        self.assertEqual(self.status()["state"], "recovery")
        with self.db() as db:
            self.assertEqual(db.query(Vault).count(), 0)
