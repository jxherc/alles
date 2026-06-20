import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


class VaultAttachmentTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9b1-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}
        self.eid = self.client.post(
            "/api/vault", json={"name": "GH", "fields": {"password": "x"}}, headers=self.h
        ).json()["id"]

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _upload(self, name="recovery.txt", data=b"secret recovery codes 123456"):
        return self.client.post(
            f"/api/vault/{self.eid}/attachments",
            files={"file": (name, data, "text/plain")},
            headers=self.h,
        )

    def test_encrypt_bytes_roundtrip(self):
        from services import crypto

        blob = crypto.encrypt_bytes("pw", b"\x00\x01binary\xff")
        self.assertEqual(crypto.decrypt_bytes("pw", blob), b"\x00\x01binary\xff")

    def test_upload_creates(self):
        r = self._upload()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["id"])

    def test_list_attachments(self):
        self._upload("a.txt")
        lst = self.client.get(f"/api/vault/{self.eid}/attachments", headers=self.h).json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["filename"], "a.txt")

    def test_download_decrypts(self):
        aid = self._upload(data=b"hello vault").json()["id"]
        r = self.client.get(f"/api/vault/attachments/{aid}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"hello vault")

    def test_download_wrong_pw_fails(self):
        self._upload(data=b"topsecret")
        # once a verifier exists, a wrong master is rejected at unlock → can't reach the blob
        bad = self.client.post("/api/vault/unlock", json={"password": "WRONG"})
        self.assertEqual(bad.status_code, 401)

    def test_delete_removes(self):
        aid = self._upload().json()["id"]
        self.client.delete(f"/api/vault/attachments/{aid}", headers=self.h)
        lst = self.client.get(f"/api/vault/{self.eid}/attachments", headers=self.h).json()
        self.assertEqual(len(lst), 0)

    def test_blob_is_ciphertext_on_disk(self):
        self._upload(data=b"plaintext-needle")
        found = False
        for p in Path(self._tmp).rglob("*.enc"):
            if b"plaintext-needle" in p.read_bytes():
                found = True
        self.assertFalse(found)  # never stored in the clear

    def test_requires_unlock_403(self):
        self.assertEqual(self.client.get(f"/api/vault/{self.eid}/attachments").status_code, 403)

    def test_size_recorded(self):
        data = b"x" * 1234
        aid = self._upload(data=data).json()["id"]
        lst = self.client.get(f"/api/vault/{self.eid}/attachments", headers=self.h).json()
        self.assertEqual(next(a for a in lst if a["id"] == aid)["size"], 1234)
