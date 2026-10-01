import unittest

from services.redaction import redact_args, redact_mapping, redact_url, sensitive_name


class RedactionTest(unittest.TestCase):
    def test_sensitive_names(self):
        for name in ("token", "api_key", "client-secret", "authorization", "db_password"):
            self.assertTrue(sensitive_name(name))
        self.assertFalse(sensitive_name("monkey"))

    def test_url_credentials_query_and_fragment_are_hidden(self):
        redacted = redact_url("https://user:pass@example.test/path?token=abc&view=list#private")
        self.assertEqual(redacted, "https://***@example.test/path?token=%2A%2A%2A&view=list#***")

    def test_nested_mapping_and_command_args_are_redacted(self):
        value = redact_mapping({"nested": {"password": "pw"}, "safe": "shown"})
        self.assertEqual(value, {"nested": {"password": "***"}, "safe": "shown"})
        self.assertEqual(
            redact_args(["--token", "abc", "--api-key=def", "safe"]),
            ["--token", "***", "--api-key=***", "safe"],
        )


if __name__ == "__main__":
    unittest.main()
