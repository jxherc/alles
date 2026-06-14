import re
import unittest
from services.pwtools import generate_password, estimate_strength


class GenTests(unittest.TestCase):
    def test_length_and_charsets(self):
        pw = generate_password(24, upper=True, lower=True, digits=True, symbols=True, avoid_ambiguous=True)
        self.assertEqual(len(pw), 24)
        self.assertTrue(re.search(r"[a-z]", pw))
        self.assertTrue(re.search(r"[A-Z]", pw))
        self.assertTrue(re.search(r"\d", pw))
        self.assertTrue(re.search(r"[^a-zA-Z0-9]", pw))
        for amb in "0O1lI":      # avoid_ambiguous drops these
            self.assertNotIn(amb, pw)

    def test_clamped_and_unique(self):
        self.assertEqual(len(generate_password(2)), 4)      # min 4
        self.assertEqual(len(generate_password(500)), 128)  # max 128
        self.assertNotEqual(generate_password(20), generate_password(20))

    def test_digits_only(self):
        pw = generate_password(10, upper=False, lower=False, digits=True, symbols=False)
        self.assertTrue(pw.isdigit())


class StrengthTests(unittest.TestCase):
    def test_empty_and_common(self):
        self.assertEqual(estimate_strength("")["score"], 0)
        self.assertIn("common", estimate_strength("password")["warning"])

    def test_repetitive_is_weak(self):
        self.assertLessEqual(estimate_strength("aaaaaaaa")["score"], 1)

    def test_generated_is_strong(self):
        self.assertGreaterEqual(estimate_strength(generate_password(24))["score"], 3)

    def test_entropy_grows_with_length(self):
        self.assertGreater(estimate_strength("Ab3!xyAb3!zw")["entropy"],
                           estimate_strength("Ab3!xy")["entropy"])


if __name__ == "__main__":
    unittest.main()
