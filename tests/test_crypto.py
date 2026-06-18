import base64
import unittest
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
    def test_seal_unseal_roundtrip(self):
        sealed = ss.seal("sk-ant-secret-key")
        self.assertTrue(sealed.startswith(ss.PREFIX))
        self.assertNotIn("secret-key", sealed)
        self.assertEqual(ss.unseal(sealed), "sk-ant-secret-key")

    def test_legacy_plaintext_passthrough(self):
        self.assertEqual(ss.unseal("plain-legacy-value"), "plain-legacy-value")

    def test_seal_is_idempotent(self):
        once = ss.seal("abc")
        self.assertEqual(ss.seal(once), once)  # already sealed → unchanged

    def test_empty(self):
        self.assertEqual(ss.seal(""), "")
        self.assertEqual(ss.unseal(""), "")


if __name__ == "__main__":
    unittest.main()
