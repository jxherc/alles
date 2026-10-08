import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services import crypto
from services import secretstore as ss


class CryptoTests(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        ct = crypto.encrypt("hunter2", "my secret value")
        self.assertNotIn("my secret value", ct)  # not stored in clear
        self.assertEqual(crypto.decrypt("hunter2", ct), "my secret value")

    def test_wrong_password_fails(self):
        ct = crypto.encrypt("right", "data")
        with self.assertRaises(Exception):  # GCM tag check fails
            crypto.decrypt("wrong", ct)

    def test_distinct_ciphertexts(self):
        # random salt+nonce → same plaintext encrypts differently each time
        self.assertNotEqual(crypto.encrypt("pw", "x"), crypto.encrypt("pw", "x"))

    def test_verifier(self):
        v = crypto.make_verifier("master-pw")
        self.assertTrue(crypto.verify_master("master-pw", v))
        self.assertFalse(crypto.verify_master("nope", v))
        self.assertFalse(crypto.verify_master("x", "not-base64-!!"))

    def test_derive_key_deterministic(self):
        salt = b"0123456789abcdef"
        self.assertEqual(crypto.derive_key("p", salt), crypto.derive_key("p", salt))
        self.assertNotEqual(crypto.derive_key("p", salt), crypto.derive_key("q", salt))


class SecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = {
            "file": ss._KEY_FILE,
            "key": ss._key,
            "path": ss._key_path,
            "keys": ss._keys,
            "active": ss._active_id,
        }
        ss._KEY_FILE = Path(self.tmp.name) / "secret.key"
        self._clear_cache()

    def tearDown(self):
        ss._KEY_FILE = self.original["file"]
        ss._key = self.original["key"]
        ss._key_path = self.original["path"]
        ss._keys = self.original["keys"]
        ss._active_id = self.original["active"]
        self.tmp.cleanup()

    def _clear_cache(self):
        ss._key = None
        ss._key_path = None
        ss._keys = {}
        ss._active_id = ""

    def test_seal_unseal_roundtrip(self):
        sealed = ss.seal("sk-ant-secret-key", "models.api_key")
        self.assertTrue(sealed.startswith(ss.PREFIX))
        self.assertNotIn("secret-key", sealed)
        self.assertEqual(ss.unseal(sealed, "models.api_key"), "sk-ant-secret-key")

    def test_ciphertext_is_bound_to_its_field_purpose(self):
        sealed = ss.seal("secret", "connections.token")
        with self.assertRaises(ss.SecretStoreError):
            ss.unseal(sealed, "settings.openai_api_key")

    def test_legacy_plaintext_passthrough(self):
        self.assertEqual(ss.unseal("plain-legacy-value"), "plain-legacy-value")

    def test_seal_is_idempotent(self):
        once = ss.seal("abc")
        self.assertEqual(ss.seal(once), once)  # already sealed → unchanged

    def test_empty(self):
        self.assertEqual(ss.seal(""), "")
        self.assertEqual(ss.unseal(""), "")

    def test_legacy_key_and_ciphertext_migrate_without_losing_data(self):
        key = os.urandom(32)
        ss._KEY_FILE.write_text(base64.b64encode(key).decode("ascii"), "utf-8")
        nonce = os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce, b"legacy secret", None)
        value = ss.LEGACY_PREFIX + base64.b64encode(nonce + encrypted).decode("ascii")

        self.assertEqual(ss.unseal(value, "connections.token"), "legacy secret")
        self.assertEqual(ss.reseal(value, "connections.token").startswith(ss.PREFIX), True)
        self.assertEqual(json.loads(ss._KEY_FILE.read_text())["version"], 2)

    def test_rotation_keeps_old_values_readable_until_resealed_and_pruned(self):
        old = ss.seal("old value", "connections.token")
        old_id = ss.cipher_key_id(old)
        new_id = ss.rotate_key()
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(ss.unseal(old, "connections.token"), "old value")

        current = ss.reseal(old, "connections.token")
        self.assertEqual(ss.cipher_key_id(current), new_id)
        ss.prune_keys({new_id})
        self.assertEqual(ss.unseal(current, "connections.token"), "old value")
        with self.assertRaises(ss.SecretStoreError):
            ss.unseal(old, "connections.token")

    def test_invalid_key_file_fails_without_being_replaced(self):
        ss._KEY_FILE.write_text("not a key", "utf-8")
        with self.assertRaises(ss.SecretStoreError):
            ss.seal("secret")
        self.assertEqual(ss._KEY_FILE.read_text("utf-8"), "not a key")


if __name__ == "__main__":
    unittest.main()
