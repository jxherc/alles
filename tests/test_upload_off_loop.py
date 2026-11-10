"""Slow upload work runs off the event loop: a second request is answered while it runs."""

import asyncio
import io
import tempfile
import time
from pathlib import Path
from unittest import mock

import httpx
from sqlalchemy import create_engine

import core.settings
import routes.contacts as contacts_route
import routes.files as files_route
import routes.gallery as gallery_route
import routes.uploads as uploads_route
import routes.vault as vault_route
from core import database
from services import files_store as fs
from services import fileversions, photos_store
from tests._client import ApiTest, app

SLOW = 0.8  # seconds the patched step sleeps, longer than any normal fast request


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


def _slow(real):
    def wrapper(*args, **kwargs):
        time.sleep(SLOW)
        return real(*args, **kwargs)

    return wrapper


class UploadOffLoopTests(ApiTest):
    """while a slow upload step runs, a second request is answered at once."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-offloop-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.eng.dispose()
        self.eng = create_engine(
            f"sqlite:///{self.root / 'api.sqlite'}", connect_args={"check_same_thread": False}
        )
        database.Base.metadata.create_all(self.eng)
        database.engine = self.eng
        database.SessionLocal.configure(bind=self.eng)
        self.settings = mock.patch.object(
            core.settings, "_SETTINGS_FILE", self.root / "settings.json"
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def overlap(self, send):
        """send(client) starts an upload. returns (upload response, upload s, health s)."""

        async def run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                start = time.monotonic()

                async def upload():
                    response = await send(c)
                    return response, time.monotonic() - start

                async def ping():
                    await asyncio.sleep(0.2)  # the upload is inside its slow step by now
                    response = await c.get("/health")
                    return response, time.monotonic() - start

                (up, up_at), (pong, pong_at) = await asyncio.gather(upload(), ping())
                self.assertEqual(pong.status_code, 200)
                return up, up_at, pong_at

        return asyncio.run(run())

    def check(self, sent):
        up, up_at, pong_at = sent
        self.assertEqual(up.status_code, 200, up.text)
        self.assertGreaterEqual(up_at, SLOW)
        self.assertLess(pong_at, up_at - SLOW / 2, "the second request waited for the upload")
        return up.json()

    def test_photos_upload(self):
        with mock.patch.object(photos_store, "import_media", _slow(photos_store.import_media)):
            sent = self.overlap(
                lambda c: c.post(
                    "/api/photos/upload", files={"file": ("a.png", _png(), "image/png")}
                )
            )
            body = self.check(sent)
        self.assertEqual(body["original_name"], "a.png")

    def test_photos_upload_bad_file_is_still_400(self):
        r = self.client.post("/api/photos/upload", files={"file": ("a.xyz", b"nope", "text/plain")})
        self.assertEqual(r.status_code, 400)

    def test_uploads_upload(self):
        upload_dir = self.root / "uploads"
        upload_dir.mkdir()
        with (
            mock.patch.object(uploads_route, "upload_dir", return_value=upload_dir),
            mock.patch.object(
                uploads_route, "_prune_cancellations", _slow(uploads_route._prune_cancellations)
            ),
        ):
            body = self.check(
                self.overlap(
                    lambda c: c.post(
                        "/api/uploads", files={"file": ("n.txt", b"hello", "text/plain")}
                    )
                )
            )
            self.assertEqual((body["name"], body["size"]), ("n.txt", 5))
            again = self.client.post(
                "/api/uploads",
                data={"upload_id": body["id"]},
                files={"file": ("n.txt", b"hello", "text/plain")},
            )
            self.assertEqual(again.status_code, 409)

    def test_vault_attachment(self):
        vault_route._unlock_tokens.clear()
        self.addCleanup(vault_route._unlock_tokens.clear)
        token = self.client.post("/api/vault/unlock", json={"password": "vault-password-1"}).json()[
            "token"
        ]
        headers = {"X-Vault-Token": token}
        entry = self.client.post(
            "/api/vault", json={"name": "n", "value": "v"}, headers=headers
        ).json()["id"]
        attach_dir = self.root / "vault_attachments"
        attach_dir.mkdir()
        import services.crypto as crypto

        with (
            mock.patch.object(vault_route, "_attach_dir", return_value=attach_dir),
            mock.patch.object(crypto, "encrypt_bytes", _slow(crypto.encrypt_bytes)),
        ):
            body = self.check(
                self.overlap(
                    lambda c: c.post(
                        f"/api/vault/{entry}/attachments",
                        files={"file": ("s.bin", b"secret bytes", "application/octet-stream")},
                        headers=headers,
                    )
                )
            )
        self.assertEqual((body["filename"], body["size"]), ("s.bin", 12))
        listed = self.client.get(f"/api/vault/{entry}/attachments", headers=headers).json()
        self.assertEqual([a["id"] for a in listed], [body["id"]])
        self.assertTrue((attach_dir / f"{body['id']}.enc").exists())

    def test_contacts_avatar(self):
        cid = self.client.post("/api/contacts", json={"name": "Ada"}).json()["id"]
        avatars = self.root / "avatars"
        avatars.mkdir()
        with (
            mock.patch.object(contacts_route, "_avatar_dir", return_value=avatars),
            mock.patch.object(contacts_route, "_write_avatar", _slow(contacts_route._write_avatar)),
        ):
            body = self.check(
                self.overlap(
                    lambda c: c.post(
                        f"/api/contacts/{cid}/avatar",
                        files={"file": ("a.png", _png(), "image/png")},
                    )
                )
            )
        self.assertTrue(body["avatar"])
        self.assertTrue((avatars / body["avatar"]).exists())

    def test_gallery_upload(self):
        gallery = self.root / "gallery"
        gallery.mkdir()
        with (
            mock.patch.object(gallery_route, "GALLERY_DIR", gallery),
            mock.patch.object(gallery_route, "_ensure_thumb", _slow(gallery_route._ensure_thumb)),
        ):
            body = self.check(
                self.overlap(
                    lambda c: c.post(
                        "/api/gallery/upload",
                        files={"file": ("g.png", _png(), "image/png")},
                        data={"prompt": "p"},
                    )
                )
            )
        self.assertEqual(body["source"], "upload")

    def test_files_upload_local(self):
        files = self.root / "files"
        files.mkdir()
        with (
            mock.patch.object(fs, "files_dir", return_value=files),
            mock.patch.object(fileversions, "data_dir", return_value=self.root / "versions"),
        ):
            self.client.get("/api/storage-locations").raise_for_status()
            with mock.patch.object(
                files_route, "_save_local_reviewed", _slow(files_route._save_local_reviewed)
            ):
                body = self.check(
                    self.overlap(
                        lambda c: c.post(
                            "/api/files/upload",
                            files={"file": ("draft.txt", b"hello", "text/plain")},
                        )
                    )
                )
            self.assertEqual(body["name"], "draft.txt")
            self.assertEqual((files / "draft.txt").read_bytes(), b"hello")
