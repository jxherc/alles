from pathlib import Path

from tests._client import VaultApiTest

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
    b"\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class DocAssetTest(VaultApiTest):
    @property
    def vault(self):
        return Path(self._vault_tmp)

    def test_a_pasted_image_lands_in_assets_and_serves_by_name(self):
        saved = self.client.post(
            "/api/vault-md/asset", files={"file": ("Screen Shot.png", PNG, "image/png")}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertTrue(body["path"].startswith("_assets/"))
        again = self.client.post(
            "/api/vault-md/asset", files={"file": ("Screen Shot.png", PNG, "image/png")}
        ).json()
        self.assertNotEqual(again["name"], body["name"])
        raw = self.client.get("/api/vault-md/raw", params={"path": body["name"]})
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(raw.content, PNG)

    def test_only_images_are_taken(self):
        refused = self.client.post(
            "/api/vault-md/asset", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        self.assertEqual(refused.status_code, 400)

    def test_svg_and_html_are_not_taken_as_pasted_images(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        for filename, content_type in (
            ("drawing.svg", "image/svg+xml"),
            ("x.html", "image/png"),
            ("x.png.html", "image/png"),
        ):
            refused = self.client.post(
                "/api/vault-md/asset", files={"file": (filename, svg, content_type)}
            )
            self.assertEqual(refused.status_code, 400, filename)
        self.assertFalse(
            (self.vault / "_assets").exists() and any((self.vault / "_assets").iterdir())
        )

    def test_a_paste_embeds_by_path_so_an_older_image_of_that_name_is_not_shown(self):
        old = self.vault / "Attachments" / "image.png"
        old.parent.mkdir()
        old.write_bytes(b"older image bytes")
        saved = self.client.post(
            "/api/vault-md/asset", files={"file": ("image.png", PNG, "image/png")}
        ).json()
        self.assertEqual(saved["path"], "_assets/image.png")
        raw = self.client.get("/api/vault-md/raw", params={"path": saved["path"]})
        self.assertEqual(raw.content, PNG)
        self.assertEqual(raw.headers["x-content-type-options"], "nosniff")

    def test_active_vault_files_are_served_inert(self):
        (self.vault / "page.html").write_text("<script>alert(1)</script>")
        (self.vault / "drawing.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        )
        html = self.client.get("/api/vault-md/raw", params={"path": "page.html"})
        self.assertEqual(html.status_code, 200)
        self.assertEqual(html.headers["content-type"], "application/octet-stream")
        self.assertIn("sandbox", html.headers["content-security-policy"])
        self.assertTrue(html.headers["content-disposition"].startswith("attachment"))
        svg = self.client.get("/api/vault-md/raw", params={"path": "drawing.svg"})
        # still an image for <img> embeds, but sandboxed when opened on its own
        self.assertTrue(svg.headers["content-type"].startswith("image/svg+xml"))
        self.assertIn("sandbox", svg.headers["content-security-policy"])
        self.assertEqual(svg.headers["x-content-type-options"], "nosniff")
