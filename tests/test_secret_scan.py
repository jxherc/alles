import unittest

from services.secret_scan import hide, mask


class SecretScanTest(unittest.TestCase):
    def test_bars_hide_anything_and_known_keys_are_caught(self):
        text, found = mask(
            "my password is ||hunter2||, key ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )
        self.assertEqual(text, "my password is {{secret:secret_1}}, key {{secret:github_token_1}}")
        self.assertEqual(found["secret_1"], "hunter2")

    def test_ordinary_text_and_shell_stay(self):
        for plain in (
            "bold **important** word",
            "run make test || echo failed",
            "cmd||exit",
            "version 1.2.3 at https://example.com/a?b=c",
        ):
            with self.subTest(text=plain):
                self.assertEqual(mask(plain), (plain, {}))

    def test_names_are_reused_and_hide_covers_repeats(self):
        _, first = mask("||abc123xyz||")
        text, again = mask("use abc123xyz and ||new-one||", first)
        self.assertEqual(text, "use {{secret:secret_1}} and {{secret:secret_2}}")
        self.assertEqual(hide("echo abc123xyz", again), "echo {{secret:secret_1}}")

    def test_assigned_random_values(self):
        text, _ = mask("api_key=f8Kq2LmN9pRtVx3ZbY7wHs and password=short")
        self.assertEqual(text, "api_key={{secret:secret_1}} and password=short")


if __name__ == "__main__":
    unittest.main()
