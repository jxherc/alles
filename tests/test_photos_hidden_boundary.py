"""Hidden Photos access checks against isolated image files and database rows."""

import base64
import io
import secrets
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

import core.settings
from core.database import Album, Face, Person, Photo
from services import faces
from services import photos_store as ps
from tests._client import ApiTest


class HiddenPhotosBoundaryTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".thumbs").mkdir()
        self.settings_file = self.root / "settings.json"
        self.vault_password = secrets.token_urlsafe(24)
        self.patches = [
            mock.patch.object(ps, "photos_dir", return_value=self.root),
            mock.patch.object(ps, "thumbs_dir", return_value=self.root / ".thumbs"),
            mock.patch.object(core.settings, "_SETTINGS_FILE", self.settings_file),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def photo(self, name="private.png", *, hidden=True, checksum=""):
        image = Image.new("RGB", (32, 32), (140, 20, 60))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        data = buffer.getvalue()
        (self.root / name).write_bytes(data)
        (self.root / ".thumbs" / name).write_bytes(data)
        db = self.db()
        photo = Photo(
            filename=name, thumb=name, original_name=name, hidden=hidden, checksum=checksum
        )
        db.add(photo)
        db.commit()
        pid = photo.id
        db.close()
        return pid

    def unlock(self):
        response = self.client.post("/api/vault/unlock", json={"password": self.vault_password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def open_hidden(self):
        token = self.unlock()
        response = self.client.get("/api/photos/hidden", headers={"X-Vault-Token": token})
        self.assertEqual(response.status_code, 200, response.text)
        return token, response

    def test_known_hidden_id_needs_vault_unlock_for_media(self):
        pid = self.photo()
        self.assertEqual(self.client.get("/api/photos/hidden").status_code, 403)
        self.assertEqual(self.client.get(f"/api/photos/thumb/{pid}").status_code, 403)
        self.assertEqual(self.client.get(f"/api/photos/original/{pid}").status_code, 403)

        token, listing = self.open_hidden()
        cookie = listing.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertIn("path=/api/photos", cookie)
        for kind in ("thumb", "original"):
            response = self.client.get(f"/api/photos/{kind}/{pid}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.client.post("/api/vault/lock", headers={"X-Vault-Token": token})
        self.assertEqual(self.client.get(f"/api/photos/original/{pid}").status_code, 403)

    def test_regular_photo_media_stays_available_without_vault(self):
        pid = self.photo("ordinary.png", hidden=False)
        self.assertEqual(self.client.get(f"/api/photos/thumb/{pid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/photos/original/{pid}").status_code, 200)

    def test_secondary_vault_unlock_does_not_open_hidden_photos(self):
        pid = self.photo()
        main_token = self.unlock()
        pw = secrets.token_urlsafe(24)
        created = self.client.post(
            "/api/vault/vaults",
            json={"name": "travel", "password": pw},
            headers={"X-Vault-Token": main_token},
        )
        self.assertEqual(created.status_code, 200, created.text)
        secondary = self.client.post(
            "/api/vault/unlock",
            json={
                "vault_id": created.json()["id"],
                "password": pw,
            },
        )
        self.assertEqual(secondary.status_code, 200, secondary.text)
        headers = {"X-Vault-Token": secondary.json()["token"]}
        self.assertEqual(self.client.get("/api/photos/hidden", headers=headers).status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/photos/original/{pid}", headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/photos/{pid}", json={"caption": "changed"}, headers=headers
            ).status_code,
            403,
        )
        db = self.db()
        self.assertEqual(db.get(Photo, pid).caption, "")
        db.close()

        marked = self.client.patch(
            f"/api/vault/vaults/{created.json()['id']}",
            json={"travel_safe": True},
            headers=headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        travel = self.client.put(
            "/api/vault/travel-mode", json={"on": True}, headers={"X-Vault-Token": main_token}
        )
        self.assertEqual(travel.status_code, 200, travel.text)
        self.assertEqual(self.client.get("/api/photos/hidden", headers=headers).status_code, 403)

    def test_hidden_records_stay_out_of_normal_duplicate_and_stack_views(self):
        cover = self.photo("hidden-cover.png", checksum="same")
        member = self.photo("hidden-member.png", checksum="same")
        db = self.db()
        db.get(Photo, cover).stack_id = cover
        db.get(Photo, member).stack_id = cover
        db.commit()
        db.close()
        self.assertEqual(self.client.get("/api/photos/duplicates").json()["groups"], [])
        self.assertEqual(self.client.get(f"/api/photos/stack/{cover}").status_code, 403)

    def test_hidden_metadata_stays_out_of_search_timeline_and_trash(self):
        pid = self.photo("private-result.png")
        self.assertEqual(self.client.get("/api/search?q=private-result").json()["photos"], [])
        self.assertEqual(self.client.get("/api/timeline?types=photo").json()["events"], [])
        self.assertEqual(self.client.get("/api/timeline/summary?types=photo").json()["total"], 0)

        _, _ = self.open_hidden()
        self.assertEqual(self.client.delete(f"/api/photos/{pid}").status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/photos/trash").json(), [])
        self.assertEqual(self.client.post(f"/api/photos/{pid}/restore").status_code, 403)
        token, _ = self.open_hidden()
        self.assertEqual(len(self.client.get("/api/photos/trash").json()), 1)
        self.assertEqual(self.client.post(f"/api/photos/{pid}/restore").status_code, 200)
        self.client.post("/api/vault/lock", headers={"X-Vault-Token": token})

    def test_hidden_face_metadata_and_crop_require_unlock(self):
        pid = self.photo()
        db = self.db()
        face = Face(photo_id=pid, bbox="0,0,16,16", det_score=0.9)
        db.add(face)
        db.commit()
        fid = face.id
        db.close()
        self.assertEqual(self.client.get(f"/api/photos/photo/{pid}/faces").status_code, 403)
        self.assertEqual(self.client.get(f"/api/photos/face/{fid}").status_code, 403)
        self.open_hidden()
        self.assertEqual(self.client.get(f"/api/photos/photo/{pid}/faces").status_code, 200)
        crop = self.client.get(f"/api/photos/face/{fid}")
        self.assertEqual(crop.status_code, 200)
        self.assertEqual(crop.headers.get("cache-control"), "no-store")

    def test_people_status_and_cover_only_use_visible_photos(self):
        hidden = self.photo()
        visible = self.photo("visible-face.png", hidden=False)
        db = self.db()
        person = Person(name="test person")
        db.add(person)
        db.flush()
        hidden_face = Face(photo_id=hidden, person_id=person.id, bbox="0,0,16,16")
        visible_face = Face(photo_id=visible, person_id=person.id, bbox="0,0,16,16")
        db.add_all([hidden_face, visible_face])
        db.flush()
        person.cover_face_id = hidden_face.id
        visible_face_id = visible_face.id
        db.commit()
        db.close()
        with mock.patch.object(faces, "available", return_value=True):
            status = self.client.get("/api/photos/faces-status").json()
            people = self.client.get("/api/photos/people").json()
        self.assertEqual(status["total"], 1)
        self.assertEqual(status["people"], 1)
        self.assertEqual(status["faces"], 1)
        self.assertEqual(people["people"][0]["cover"], f"/api/photos/face/{visible_face_id}")

    def test_hidden_stack_and_album_changes_require_unlock(self):
        hidden = self.photo()
        visible = self.photo("visible.png", hidden=False)
        db = self.db()
        db.get(Photo, hidden).stack_id = visible
        db.get(Photo, visible).stack_id = visible
        album = Album(name="mixed")
        db.add(album)
        db.flush()
        aid = album.id
        db.get(Photo, hidden).album_id = aid
        db.commit()
        db.close()
        self.assertEqual(
            self.client.get(f"/api/photos/stack/{visible}").json()["items"][0]["id"], visible
        )
        self.assertEqual(len(self.client.get(f"/api/photos/stack/{visible}").json()["items"]), 1)
        self.assertEqual(
            self.client.post("/api/photos/unstack", json={"id": visible}).status_code, 403
        )
        self.assertEqual(self.client.delete(f"/api/photos/albums/{aid}").status_code, 403)
        self.open_hidden()
        self.assertEqual(
            self.client.post("/api/photos/unstack", json={"id": visible}).status_code, 200
        )
        self.assertEqual(self.client.delete(f"/api/photos/albums/{aid}").status_code, 200)

    def test_visible_stack_member_survives_hidden_cover(self):
        cover = self.photo()
        member = self.photo("member.png", hidden=False)
        db = self.db()
        db.get(Photo, cover).stack_id = cover
        db.get(Photo, member).stack_id = cover
        db.commit()
        db.close()
        visible = self.client.get("/api/photos/list").json()
        items = [item for group in visible["moments"] for item in group["items"]]
        self.assertEqual([item["id"] for item in items], [member])
        self.assertEqual(self.client.get(f"/api/photos/stack/{member}").json()["items"], [])

    def test_hidden_edit_stays_hidden_and_needs_unlock(self):
        pid = self.photo()
        raw = (self.root / "private.png").read_bytes()
        body = {
            "data_url": "data:image/png;base64," + base64.b64encode(raw).decode(),
            "name": "edited.png",
            "source_photo_id": pid,
        }
        self.assertEqual(self.client.post("/api/photos/edit-save", json=body).status_code, 403)
        self.open_hidden()
        response = self.client.post("/api/photos/edit-save", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["hidden"])
        copy_id = response.json()["id"]
        self.assertEqual(self.client.get("/api/photos/list").json()["count"], 0)
        db = self.db()
        self.assertTrue(db.get(Photo, copy_id).hidden)
        db.close()

    def test_hidden_record_cannot_be_changed_without_vault_unlock(self):
        pid = self.photo()
        self.assertEqual(
            self.client.patch(f"/api/photos/{pid}", json={"caption": "changed"}).status_code,
            403,
        )
        self.assertEqual(self.client.delete(f"/api/photos/{pid}").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/photos/batch", json={"ids": [pid], "action": "unhide"}
            ).status_code,
            403,
        )
        db = self.db()
        self.assertTrue(db.get(Photo, pid).hidden)
        self.assertEqual(db.get(Photo, pid).caption, "")
        db.close()
