"""Public share recovery pages retain their gates and usable document semantics."""

from html.parser import HTMLParser

from routes import shared
from services import vault_md
from tests._client import VaultApiTest


class PageElements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag, **attrs):
        return [
            found
            for name, found in self.elements
            if name == tag and all(found.get(key) == value for key, value in attrs.items())
        ]


class SharedStatusPageTests(VaultApiTest):
    def _mint(self, **options):
        vault_md.write("access.md", "# Shared document\n\nSynthetic reader content.")
        response = self.client.post(
            "/api/share", json={"kind": "doc", "ref": "access.md", **options}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def _status_document(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertTrue(response.text.lower().startswith("<!doctype html>"))
        elements = PageElements(response.text)
        self.assertEqual(elements.find("html")[0].get("lang"), "en")
        self.assertEqual(
            elements.find("meta", name="viewport"),
            [{"name": "viewport", "content": "width=device-width,initial-scale=1"}],
        )
        self.assertEqual(len(elements.find("title")), 1)
        self.assertEqual(len(elements.find("main")), 1)
        self.assertEqual(len(elements.find("h1")), 1)
        return elements

    def test_missing_public_routes_have_readable_recovery_pages(self):
        for path in (
            "/s/missing",
            "/s/missing/child",
            "/rsvp/missing",
            "/book/missing",
            "/sv/missing",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self._status_document(response, 404)
                self.assertIn("not found or link revoked", response.text)
                self.assertIn("Ask the person who shared it for a new link.", response.text)
        self._status_document(self.client.post("/s/missing/unlock", data={"password": "x"}), 404)

    def test_expired_share_stays_closed_on_all_entry_points(self):
        token = self._mint(expires_at="2000-01-01T00:00:00Z", password="reader-secret")
        responses = [
            self.client.get(f"/s/{token}"),
            self.client.get(f"/s/{token}/child"),
            self.client.post(f"/s/{token}/unlock", data={"password": "reader-secret"}),
        ]
        for response in responses:
            with self.subTest(url=str(response.url)):
                self._status_document(response, 410)
                self.assertIn("this link has expired", response.text)
                self.assertNotIn("Synthetic reader content", response.text)
                self.assertNotIn("set-cookie", response.headers)

    def test_password_form_is_named_and_preserves_private_gate(self):
        token = self._mint(password="reader-secret")
        response = self.client.get(f"/s/{token}")
        elements = self._status_document(response, 401)
        field = elements.find("input", name="password")[0]
        self.assertEqual(field["type"], "password")
        self.assertEqual(field["autocomplete"], "current-password")
        self.assertEqual(elements.find("label")[0]["for"], field["id"])
        self.assertEqual(elements.find("form")[0]["method"], "post")
        self.assertEqual(elements.find("form")[0]["action"], f"/s/{token}/unlock")
        self.assertEqual(elements.find("button")[0]["type"], "submit")
        self.assertNotIn("aria-invalid", field)
        self.assertNotIn("value", field)
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        self.assertNotIn("Synthetic reader content", response.text)
        self.assertNotIn("reader-secret", response.text)

    def test_wrong_password_is_associated_with_field_and_can_be_retried(self):
        token = self._mint(password="reader-secret")
        response = self.client.post(f"/s/{token}/unlock", data={"password": "wrong-secret"})
        elements = self._status_document(response, 401)
        field = elements.find("input", name="password")[0]
        self.assertEqual(field["aria-invalid"], "true")
        self.assertEqual(field["aria-describedby"], elements.find("p", role="alert")[0]["id"])
        self.assertIn("wrong password", response.text)
        self.assertNotIn("wrong-secret", response.text)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        unlocked = self.client.post(
            f"/s/{token}/unlock", data={"password": "reader-secret"}, follow_redirects=False
        )
        self.assertEqual(unlocked.status_code, 303)
        cookie = unlocked.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn(f"Path=/s/{token}", cookie)
        document = self.client.get(f"/s/{token}")
        self.assertEqual(document.status_code, 200)
        self.assertIn("Synthetic reader content", document.text)
        self.assertEqual(document.headers["cache-control"], "private, no-store, max-age=0")
        self.assertEqual(document.headers["pragma"], "no-cache")

    def test_locked_form_escapes_token_attribute(self):
        token = "token'\"><script>alert(1)</script>"
        response = shared._locked_page(token, wrong=True)
        source = response.body.decode()
        self.assertNotIn("<script>", source)
        elements = PageElements(source)
        self.assertEqual(elements.find("form")[0]["action"], f"/s/{token}/unlock")
        self.assertEqual(len(elements.find("input")), 1)

    def test_normal_public_document_remains_read_only_and_mobile_ready(self):
        token = self._mint()
        response = self.client.get(f"/s/{token}")
        self.assertEqual(response.status_code, 200)
        elements = PageElements(response.text)
        self.assertEqual(
            elements.find("meta", name="viewport")[0]["content"],
            "width=device-width,initial-scale=1",
        )
        self.assertIn("<h1>Shared document</h1>", response.text)
        self.assertIn("read-only", response.text)
        self.assertFalse(elements.find("form"))
