import hashlib
import re
import unittest

from services.pwtools import (
    breach_count,
    card_brand,
    card_last4,
    estimate_strength,
    find_reused,
    generate_password,
    is_weak,
    luhn_valid,
    mask_card,
    totp_now,
    totp_remaining,
)


class GenTests(unittest.TestCase):
    def test_length_and_charsets(self):
        pw = generate_password(
            24, upper=True, lower=True, digits=True, symbols=True, avoid_ambiguous=True
        )
        self.assertEqual(len(pw), 24)
        self.assertTrue(re.search(r"[a-z]", pw))
        self.assertTrue(re.search(r"[A-Z]", pw))
        self.assertTrue(re.search(r"\d", pw))
        self.assertTrue(re.search(r"[^a-zA-Z0-9]", pw))
        for amb in "0O1lI":  # avoid_ambiguous drops these
            self.assertNotIn(amb, pw)

    def test_clamped_and_unique(self):
        self.assertEqual(len(generate_password(2)), 4)  # min 4
        self.assertEqual(len(generate_password(500)), 128)  # max 128
        self.assertNotEqual(generate_password(20), generate_password(20))

    def test_digits_only(self):
        pw = generate_password(10, upper=False, lower=False, digits=True, symbols=False)
        self.assertTrue(pw.isdigit())

    def test_symbols_only(self):
        pw = generate_password(10, upper=False, lower=False, digits=False, symbols=True)
        self.assertTrue(all(c in "!@#$%^&*-_=+?" for c in pw))

    def test_no_flags_falls_back_to_ascii_letters(self):
        # all False → pool defaults to ascii_letters so it won't crash
        pw = generate_password(8, upper=False, lower=False, digits=False, symbols=False)
        self.assertEqual(len(pw), 8)
        self.assertTrue(pw.isalpha())

    def test_ambiguous_chars_included_when_not_avoided(self):
        # run enough iterations that 0/O/l/I/1 are likely to appear
        found = set()
        for _ in range(300):
            pw = generate_password(20, upper=True, lower=True, digits=True, avoid_ambiguous=False)
            found |= set(pw)
        self.assertTrue(found & set("0O1lI"), "expected ambiguous chars when avoid_ambiguous=False")

    def test_guaranteed_one_from_each_pool(self):
        # every enabled charset must appear at least once (guarantee logic)
        for _ in range(50):
            pw = generate_password(4, upper=True, lower=True, digits=True, symbols=True)
            self.assertTrue(re.search(r"[a-zA-Z]", pw))
            self.assertTrue(re.search(r"\d", pw))


class StrengthTests(unittest.TestCase):
    def test_empty_and_common(self):
        self.assertEqual(estimate_strength("")["score"], 0)
        self.assertIn("common", estimate_strength("password")["warning"])

    def test_repetitive_is_weak(self):
        self.assertLessEqual(estimate_strength("aaaaaaaa")["score"], 1)

    def test_generated_is_strong(self):
        self.assertGreaterEqual(estimate_strength(generate_password(24))["score"], 3)

    def test_entropy_grows_with_length(self):
        self.assertGreater(
            estimate_strength("Ab3!xyAb3!zw")["entropy"], estimate_strength("Ab3!xy")["entropy"]
        )

    def test_sequence_warning(self):
        r = estimate_strength("abcd1234qwer")
        self.assertIn("sequence", r["warning"])

    def test_repeated_chars_warning(self):
        r = estimate_strength("aaa111bbb")
        self.assertIn("repeated", r["warning"])

    def test_score_labels_match(self):
        labels = ["very weak", "weak", "fair", "strong", "very strong"]
        for pw, expected_min in [("a", 0), ("Ab3!xyAb3!xyAb3!xyAb3!xy", 3)]:
            r = estimate_strength(pw)
            self.assertEqual(r["label"], labels[r["score"]])

    def test_charset_only_lowercase_entropy(self):
        # 8 chars * log2(26) ~ 37.6 bits
        r = estimate_strength("abcdefgh")
        self.assertAlmostEqual(r["entropy"], 37.6, places=0)


class LuhnTests(unittest.TestCase):
    def test_valid_visa(self):
        self.assertTrue(luhn_valid("4532015112830366"))

    def test_invalid_number(self):
        self.assertFalse(luhn_valid("1234567890123456"))

    def test_too_short(self):
        self.assertFalse(luhn_valid("1234"))

    def test_with_spaces_and_dashes(self):
        # strips non-digits
        self.assertTrue(luhn_valid("4532 0151 1283 0366"))
        self.assertTrue(luhn_valid("4532-0151-1283-0366"))


class CardBrandTests(unittest.TestCase):
    def test_visa(self):
        self.assertEqual(card_brand("4111111111111111"), "Visa")

    def test_mastercard(self):
        self.assertEqual(card_brand("5500005555555559"), "Mastercard")

    def test_amex(self):
        self.assertEqual(card_brand("378282246310005"), "Amex")

    def test_discover(self):
        self.assertEqual(card_brand("6011111111111117"), "Discover")

    def test_unknown_brand(self):
        self.assertEqual(card_brand("9999999999999999"), "Card")

    def test_last4_and_mask(self):
        self.assertEqual(card_last4("4111111111111111"), "1111")
        m = mask_card("4111111111111111")
        self.assertTrue(m.endswith("1111"))
        self.assertIn("•", m)

    def test_mask_empty(self):
        self.assertEqual(mask_card(""), "")


class TotpTests(unittest.TestCase):
    _SECRET = "JBSWY3DPEHPK3PXP"

    def test_code_is_6_digits(self):
        code = totp_now(self._SECRET, t=1000)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_same_period_gives_same_code(self):
        # t=0 and t=29 are in the same 30s window
        self.assertEqual(totp_now(self._SECRET, t=0), totp_now(self._SECRET, t=29))

    def test_different_period_gives_different_code(self):
        self.assertNotEqual(totp_now(self._SECRET, t=0), totp_now(self._SECRET, t=30))

    def test_custom_digits(self):
        code = totp_now(self._SECRET, digits=8, t=500)
        self.assertEqual(len(code), 8)

    def test_remaining_seconds(self):
        # at t=10 with period=30, should be 20s left
        self.assertEqual(totp_remaining(period=30, t=10), 20)
        self.assertEqual(totp_remaining(period=30, t=0), 30)


class WatchtowerTests(unittest.TestCase):
    def test_find_reused_groups(self):
        entries = [
            {"id": "a", "password": "x"},
            {"id": "b", "password": "x"},
            {"id": "c", "password": "y"},
        ]
        groups = find_reused(entries)
        self.assertEqual(len(groups), 1)
        self.assertIn("a", groups[0])
        self.assertIn("b", groups[0])

    def test_find_reused_no_dupes(self):
        entries = [{"id": "a", "password": "x"}, {"id": "b", "password": "y"}]
        self.assertEqual(find_reused(entries), [])

    def test_find_reused_ignores_empty_pw(self):
        entries = [{"id": "a", "password": ""}, {"id": "b", "password": ""}]
        self.assertEqual(find_reused(entries), [])

    def test_is_weak_true_for_short(self):
        self.assertTrue(is_weak("abc"))

    def test_is_weak_false_for_strong(self):
        self.assertFalse(is_weak("Tr0ub4dor&3xtra!!Long"))

    def test_breach_count_match(self):
        # mock the fetch to return a matching suffix
        sha = hashlib.sha1(b"hunter2").hexdigest().upper()
        suffix = sha[5:]

        def fake_fetch(prefix):
            return suffix + ":42\nOTHER:1"

        self.assertEqual(breach_count("hunter2", fake_fetch), 42)

    def test_breach_count_no_match(self):
        self.assertEqual(breach_count("notinlist", lambda p: "DEADBEEF:999"), 0)

    def test_breach_count_empty_password(self):
        self.assertEqual(breach_count("", lambda p: "anything"), 0)

    def test_breach_count_fetch_error(self):
        def bad_fetch(p):
            raise RuntimeError("network down")

        # should not raise, returns 0
        self.assertEqual(breach_count("pw", bad_fetch), 0)


if __name__ == "__main__":
    unittest.main()
