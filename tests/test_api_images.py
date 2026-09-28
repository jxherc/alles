import json

from core.database import ModelEndpoint
from routes.models import _is_chat_model
from services.imagegen import image_models, is_image_model
from tests._client import VaultApiTest


class ImagesApiTest(VaultApiTest):
    def test_empty_prompt_400(self):
        self.assertEqual(
            self.client.post("/api/images/generate", json={"prompt": "  "}).status_code, 400
        )

    def test_no_endpoint_400(self):
        # fresh db has no model endpoint → clean error, not a crash
        r = self.client.post("/api/images/generate", json={"prompt": "a red bicycle"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("endpoint", r.json()["detail"].lower())

    def test_generated_image_appears_in_creations_without_a_second_copy(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image

        from core.database import GalleryImage, Photo

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        db.add(endpoint)
        db.commit()
        endpoint_id = endpoint.id
        db.close()

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue(), b"not an image"]

        prompt = "a red square with a very long descriptive prompt that should not be cut off"
        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
        ):
            result = self.client.post(
                "/api/images/generate", json={"endpoint_id": endpoint_id, "prompt": prompt}
            )
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(result.json()["images"]), 1)
            photo_id = result.json()["images"][0]["id"]
            creations = self.client.get("/api/gallery").json()["items"]
            self.assertEqual(len(creations), 1)
            self.assertEqual(creations[0]["id"], photo_id)
            self.assertEqual(creations[0]["prompt"], prompt)
            self.assertEqual(creations[0]["owner"], "photos")
            self.assertEqual(self.client.get(creations[0]["url"]).content, buf.getvalue())

        db = self.db()
        photo = db.get(Photo, photo_id)
        self.assertEqual(photo.source, "generated")
        self.assertTrue(photo.checksum)
        self.assertEqual(photo.aspect_ratio, 1)
        self.assertTrue(photo.preview)
        self.assertEqual(db.query(GalleryImage).count(), 0)
        db.close()

    def test_generate_second_media_write_failure_leaves_no_partial_photo(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image

        from core.database import Photo
        from services import photos_store

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        db.add(endpoint)
        db.commit()
        endpoint_id = endpoint.id
        db.close()

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue(), buf.getvalue()]

        import_image = photos_store.import_image
        calls = 0

        def second_write_fails(data, name):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("photos disk is full")
            return import_image(data, name)

        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
        ):
            with patch("services.photos_store.import_image", side_effect=second_write_fails):
                response = self.client.post(
                    "/api/images/generate",
                    json={"endpoint_id": endpoint_id, "prompt": "two squares"},
                )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(Path(temp).rglob("*.png")), [])
            self.assertEqual(list(Path(temp).rglob("*.jpg")), [])
            db = self.db()
            self.assertEqual(db.query(Photo).count(), 0)
            db.close()
            retry = self.client.post(
                "/api/images/generate", json={"endpoint_id": endpoint_id, "prompt": "two squares"}
            )
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(len(retry.json()["images"]), 2)

        db = self.db()
        self.assertEqual(db.query(Photo).count(), 2)
        db.close()

    def test_generate_database_write_failure_cleans_media(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image

        from core.database import Photo
        from services.photo_records import Session

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        db.add(endpoint)
        db.commit()
        endpoint_id = endpoint.id
        db.close()

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue()]

        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
            patch.object(Session, "commit", side_effect=OSError("database write failed")),
        ):
            response = self.client.post(
                "/api/images/generate", json={"endpoint_id": endpoint_id, "prompt": "one square"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(Path(temp).rglob("*.png")), [])
            self.assertEqual(list(Path(temp).rglob("*.jpg")), [])

        db = self.db()
        self.assertEqual(db.query(Photo).count(), 0)
        db.close()

    def test_chat_image_storage_failure_keeps_chat_and_photos_empty(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image

        from core.database import Message, Photo
        from core.database import Session as ChatSession
        from services import notes_vault, photos_store

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        chat = ChatSession(name="new chat")
        db.add_all([endpoint, chat])
        db.commit()
        endpoint_id, chat_id = endpoint.id, chat.id
        db.close()

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue(), buf.getvalue()]

        import_image = photos_store.import_image
        calls = 0

        def second_write_fails(data, name):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("photos disk is full")
            return import_image(data, name)

        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
            patch("services.photos_store.import_image", side_effect=second_write_fails),
        ):
            response = self.client.post(
                "/api/images/chat",
                json={"session_id": chat_id, "endpoint_id": endpoint_id, "prompt": "two squares"},
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(Path(temp).rglob("*.png")), [])
            self.assertEqual(list(Path(temp).rglob("*.jpg")), [])

        db = self.db()
        self.assertEqual(db.query(Photo).count(), 0)
        self.assertEqual(db.query(Message).filter_by(session_id=chat_id).count(), 0)
        self.assertEqual(db.get(ChatSession, chat_id).message_count, 0)
        self.assertEqual(notes_vault.all_notes(), [])
        db.close()

    def test_image_model_detection(self):
        for mid in [
            "dall-e-3",
            "gpt-image-1",
            "imagen-3.0-generate-002",
            "flux.1-dev",
            "stable-diffusion-xl",
            "sdxl-turbo",
            "ideogram-v2",
            "recraft-v3",
        ]:
            self.assertTrue(is_image_model(mid), mid)
        for mid in ["deepseek-chat", "claude-opus-4-8", "gpt-4o", "text-embedding-3-large"]:
            self.assertFalse(is_image_model(mid), mid)

    def test_image_models_kept_out_of_chat(self):
        # image models get their own picker — they must not pollute the chat list
        self.assertFalse(_is_chat_model("dall-e-3"))
        self.assertTrue(_is_chat_model("gpt-4o"))
        self.assertEqual(image_models(["gpt-4o", "dall-e-3", "flux-pro"]), ["dall-e-3", "flux-pro"])

    def test_endpoint_exposes_image_models(self):
        d = self.db()
        d.add(
            ModelEndpoint(
                name="OpenAI",
                base_url="http://x",
                enabled=True,
                cached_models=json.dumps(["gpt-4o"]),
                image_models=json.dumps(["dall-e-3", "gpt-image-1"]),
            )
        )
        d.commit()
        d.close()
        ep = [e for e in self.client.get("/api/models").json() if e["name"] == "OpenAI"][0]
        self.assertEqual(ep["image_models"], ["dall-e-3", "gpt-image-1"])
        self.assertEqual(ep["models"], ["gpt-4o"])

    # ── image-in-chat endpoint ──
    def test_chat_image_empty_prompt_400(self):
        r = self.client.post("/api/images/chat", json={"session_id": "x", "prompt": "  "})
        self.assertEqual(r.status_code, 400)

    def test_chat_image_missing_session_404(self):
        r = self.client.post("/api/images/chat", json={"session_id": "nope", "prompt": "a cat"})
        self.assertEqual(r.status_code, 404)

    def test_chat_image_no_endpoint_400(self):
        from core.database import Session as Sess

        d = self.db()
        s = Sess(name="t")
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        r = self.client.post("/api/images/chat", json={"session_id": sid, "prompt": "a cat"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("endpoint", r.json()["detail"].lower())

    def test_chat_image_full_flow(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("PIL not available")
        import tempfile
        from io import BytesIO
        from pathlib import Path

        import services.imagegen as ig
        import services.photos_store as pstore
        from core.database import Message, ModelEndpoint
        from core.database import Session as Sess
        from services import notes_vault

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        png = buf.getvalue()
        d = self.db()
        ep = ModelEndpoint(
            name="OpenAI",
            base_url="http://x",
            enabled=True,
            cached_models=json.dumps(["gpt-4o"]),
            image_models=json.dumps(["dall-e-3"]),
        )
        s = Sess(name="new chat")
        d.add(ep)
        d.add(s)
        d.commit()
        sid, epid = s.id, ep.id
        d.close()

        tmp = tempfile.TemporaryDirectory()
        (Path(tmp.name) / ".thumbs").mkdir(parents=True, exist_ok=True)
        orig_dir, orig_gen = pstore.photos_dir, ig.generate
        pstore.photos_dir = lambda: Path(tmp.name)  # keep test images out of real data/

        async def fake_gen(*a, **k):
            return [png]

        ig.generate = fake_gen
        try:
            r = self.client.post(
                "/api/images/chat",
                json={
                    "session_id": sid,
                    "prompt": "a red square",
                    "model": "dall-e-3",
                    "endpoint_id": epid,
                },
            )
        finally:
            ig.generate, pstore.photos_dir = orig_gen, orig_dir
            tmp.cleanup()

        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertIn("saved to notes", j["content"])
        self.assertTrue(j["doc_id"])
        self.assertEqual(
            len(notes_vault.all_notes()), 1
        )  # filed as a vault note (the live docs app)
        d = self.db()
        self.assertEqual(d.query(Message).filter_by(session_id=sid).count(), 2)
        # the stored count must match the 2 rows actually written (was +1, drifting the sidebar)
        self.assertEqual(d.get(Sess, sid).message_count, 2)
        self.assertEqual(d.get(Sess, sid).name, "a red square")
        self.assertEqual(self.client.get("/api/gallery").json()["items"][0]["owner"], "photos")
        d.close()

    def test_chat_image_incognito_leaves_no_trace(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("PIL not available")
        from io import BytesIO

        import services.imagegen as ig
        from core.database import Message, ModelEndpoint
        from core.database import Session as Sess
        from services import notes_vault

        buf = BytesIO()
        Image.new("RGB", (4, 4), (20, 200, 30)).save(buf, "PNG")
        png = buf.getvalue()
        d = self.db()
        ep = ModelEndpoint(
            name="OpenAI", base_url="http://x", enabled=True, image_models=json.dumps(["dall-e-3"])
        )
        s = Sess(name="new chat", incognito=True)
        d.add(ep)
        d.add(s)
        d.commit()
        sid, epid = s.id, ep.id
        d.close()

        orig_gen = ig.generate

        async def fake_gen(*a, **k):
            return [png]

        ig.generate = fake_gen
        try:
            r = self.client.post(
                "/api/images/chat",
                json={
                    "session_id": sid,
                    "prompt": "secret",
                    "model": "dall-e-3",
                    "endpoint_id": epid,
                },
            )
        finally:
            ig.generate = orig_gen

        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertIsNone(j["doc_id"])
        self.assertIn("data:image", j["content"])  # inlined, not a gallery url
        self.assertEqual(len(notes_vault.all_notes()), 0)  # incognito leaves no vault note
        d = self.db()
        self.assertEqual(d.query(Message).filter_by(session_id=sid).count(), 0)
        self.assertEqual(self.client.get("/api/gallery").json()["items"], [])
        d.close()

    def test_chat_image_keeps_the_turn_when_notes_cannot_save(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image

        from core.database import Message, Photo
        from core.database import Session as Sess
        from services import notes_vault

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        session = Sess(name="new chat")
        db.add_all([endpoint, session])
        db.commit()
        session_id, endpoint_id = session.id, endpoint.id
        db.close()

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue()]

        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
            patch.object(notes_vault, "create", side_effect=OSError("notes unavailable")),
        ):
            response = self.client.post(
                "/api/images/chat",
                json={
                    "session_id": session_id,
                    "endpoint_id": endpoint_id,
                    "prompt": "a red square",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertIsNone(result["doc_id"])
            self.assertIn("couldn't save to notes", result["content"])
            self.assertEqual(len(result["images"]), 1)
            self.assertEqual(self.client.get(result["images"][0]["original"]).status_code, 200)

            db = self.db()
            self.assertEqual(db.query(Photo).count(), 1)
            self.assertEqual(db.query(Message).filter_by(session_id=session_id).count(), 2)
            self.assertEqual(db.get(Sess, session_id).message_count, 2)
            db.close()
