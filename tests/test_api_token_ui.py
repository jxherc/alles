import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ApiTokenUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "static" / "index.html").read_text("utf-8")
        cls.js = (ROOT / "static" / "js" / "settings.js").read_text("utf-8")

    def test_every_backend_scope_is_selectable(self):
        for scope in ("read", "write", "models", "agent", "secrets", "connections", "admin"):
            self.assertIn(f'data-token-scope="{scope}"', self.html)

    def test_read_is_the_only_default_scope(self):
        self.assertIn('class="vsp-chip active" data-token-scope="read"', self.html)
        for scope in ("write", "models", "agent", "secrets", "connections", "admin"):
            self.assertIn(f'class="vsp-chip" data-token-scope="{scope}"', self.html)

    def test_selected_scopes_are_sent_and_errors_are_shown(self):
        self.assertIn("JSON.stringify({ name, scopes })", self.js)
        self.assertIn("if (!r.ok)", self.js)
        self.assertIn("t.scopes || []", self.js)

    def test_sensitive_token_actions_can_request_recent_owner_auth(self):
        self.assertIn("/api/auth/reauth", self.js)
        self.assertIn(
            "options.secret ? 'password'", (ROOT / "static/js/dialog.js").read_text("utf-8")
        )


if __name__ == "__main__":
    unittest.main()
