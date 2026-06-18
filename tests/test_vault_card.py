import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings as cs
from services.pwtools import card_brand, card_last4, luhn_valid, mask_card
from tests._client import ApiTest


class CardHelperTests(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertTrue(luhn_valid("4111111111111111"))

    def test_luhn_invalid(self):
        self.assertFalse(luhn_valid("4111111111111112"))

    def test_brand_visa(self):
        self.assertEqual(card_brand("4111111111111111"), "Visa")

    def test_brand_mastercard(self):
        self.assertEqual(card_brand("5500000000000004"), "Mastercard")

    def test_brand_amex(self):
        self.assertEqual(card_brand("340000000000009"), "Amex")

    def test_brand_unknown(self):
        self.assertEqual(card_brand("9999000000000000"), "Card")

    def test_last4(self):
        self.assertEqual(card_last4("4111 1111 1111 1234"), "1234")

    def test_mask(self):
        self.assertTrue(mask_card("4111111111111234").endswith("1234"))
        self.assertNotIn("4111", mask_card("4111111111111234"))


class CardRevealTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = mock.patch.object(cs, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        self.sp.start()
        tok = self.client.post("/api/vault/unlock", json={"password": "m"}).json()["token"]
        self.h = {"X-Vault-Token": tok}

    def tearDown(self):
        self.sp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_card_reveal_includes_meta(self):
        eid = self.client.post(
            "/api/vault",
            headers=self.h,
            json={"name": "V", "type": "card", "fields": {"number": "4111111111111111"}},
        ).json()["id"]
        d = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(d["card"]["brand"], "Visa")
        self.assertEqual(d["card"]["last4"], "1111")
        self.assertTrue(d["card"]["valid"])

    def test_password_reveal_no_card_meta(self):
        eid = self.client.post(
            "/api/vault",
            headers=self.h,
            json={"name": "P", "type": "password", "fields": {"password": "x"}},
        ).json()["id"]
        d = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertNotIn("card", d)


if __name__ == "__main__":
    unittest.main()
