from tests._client import VaultApiTest

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
    b"\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class DocAssetTest(VaultApiTest):
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
