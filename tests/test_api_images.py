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

    def test_chat_image_message_write_failure_leaves_no_photo_or_note(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from uuid import uuid4

        from PIL import Image
        from starlette.testclient import TestClient

        from app import app
        from core.database import Message, Photo, get_db
        from core.database import Session as ChatSession
        from services import notes_vault

        buf = BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        db = self.db()
        endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
        chat = ChatSession(name="new chat")
        db.add_all([endpoint, chat])
        db.commit()
        endpoint_id, chat_id = endpoint.id, chat.id
        db.close()
        body = {
            "session_id": chat_id,
            "endpoint_id": endpoint_id,
            "prompt": "a red square",
            "request_id": str(uuid4()),
        }

        async def fake_generate(*_args, **_kwargs):
            return [buf.getvalue()]

        request_db = self.db()
        commit = request_db.commit

        def fail_chat_commit():
            if any(isinstance(row, Message) for row in request_db.new):
                raise OSError("chat database write failed")
            return commit()

        def use_request_db():
            yield request_db

        previous_override = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = use_request_db
        client = TestClient(app, raise_server_exceptions=False)
        try:
            with (
                TemporaryDirectory() as temp,
                patch("services.photos_store.photos_dir", return_value=Path(temp)),
                patch("services.imagegen.generate", side_effect=fake_generate),
                patch.object(request_db, "commit", side_effect=fail_chat_commit),
            ):
                response = client.post(
                    "/api/images/chat",
                    json=body,
                )
                request_db.rollback()
                media_count = len(list(Path(temp).rglob("*.png"))) + len(
                    list(Path(temp).rglob("*.jpg"))
                )
        finally:
            client.close()
            request_db.close()
            if previous_override is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous_override

        db = self.db()
        actual = {
            "status": response.status_code,
            "media": media_count,
            "photos": db.query(Photo).count(),
            "messages": db.query(Message).filter_by(session_id=chat_id).count(),
            "message_count": db.get(ChatSession, chat_id).message_count,
            "notes": len(notes_vault.all_notes()),
        }
        self.assertEqual(
            actual,
            {"status": 503, "media": 0, "photos": 0, "messages": 0, "message_count": 0, "notes": 0},
        )
        db.close()
        self.assertEqual(self.client.get(f"/api/sessions/{chat_id}/history").json()["messages"], [])
        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
        ):
            retry = self.client.post("/api/images/chat", json=body)
            self.assertEqual(retry.status_code, 200, retry.text)
        db = self.db()
        self.assertEqual(db.query(Photo).count(), 1)
        self.assertEqual(db.query(Message).filter_by(session_id=chat_id).count(), 2)
        db.close()

    def test_chat_image_replays_one_request_without_regenerating(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from uuid import uuid4

        from PIL import Image

        from core.database import Message, Photo
        from core.database import Session as ChatSession
        from services import notes_vault

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
            return [buf.getvalue()]

        body = {
            "session_id": chat_id,
            "endpoint_id": endpoint_id,
            "prompt": "a red square",
            "request_id": str(uuid4()),
        }
        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate) as generate,
        ):
            first = self.client.post("/api/images/chat", json=body)
            replay = self.client.post("/api/images/chat", json=body)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json(), first.json())
            self.assertEqual(generate.call_count, 1)
            invalid = self.client.post(
                "/api/images/chat", json={**body, "request_id": "not-a-uuid"}
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(generate.call_count, 1)
            conflict = self.client.post(
                "/api/images/chat", json={**body, "prompt": "a blue square"}
            )
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(generate.call_count, 1)

            deliberate_repeat = self.client.post(
                "/api/images/chat", json={**body, "request_id": str(uuid4())}
            )
            self.assertEqual(deliberate_repeat.status_code, 200, deliberate_repeat.text)
            self.assertNotEqual(deliberate_repeat.json()["images"], first.json()["images"])
            self.assertEqual(generate.call_count, 2)

            deleted = self.client.delete(f"/api/photos/{first.json()['images'][0]['id']}")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            gone = self.client.post("/api/images/chat", json=body)
            self.assertEqual(gone.status_code, 410)
            self.assertEqual(generate.call_count, 2)

        db = self.db()
        self.assertEqual(db.query(Photo).count(), 2)
        self.assertEqual(db.query(Message).filter_by(session_id=chat_id).count(), 4)
        self.assertEqual(db.get(ChatSession, chat_id).message_count, 4)
        self.assertEqual(len(notes_vault.all_notes()), 2)
        db.close()

    def test_chat_image_concurrent_retry_keeps_one_photo_and_turn(self):
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier
        from unittest.mock import patch
        from uuid import uuid4

        from PIL import Image
        from sqlalchemy import create_engine
        from starlette.testclient import TestClient

        import core.database as database
        from app import app
        from core.database import Message, Photo
        from core.database import Session as ChatSession
        from services import notes_vault

        def png(color):
            buf = BytesIO()
            Image.new("RGB", (4, 4), color).save(buf, "PNG")
            return buf.getvalue()

        outputs = iter([png((200, 30, 30)), png((30, 30, 200))])
        barrier = Barrier(2)

        async def fake_generate(*_args, **_kwargs):
            image = next(outputs)
            await asyncio.to_thread(barrier.wait, timeout=10)
            return [image]

        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "photos" / ".thumbs").mkdir(parents=True)
            file_engine = create_engine(
                f"sqlite:///{root / 'images.db'}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            database.Base.metadata.create_all(file_engine)
            database.engine = file_engine
            database.SessionLocal.configure(bind=file_engine)
            try:
                db = self.db()
                endpoint = ModelEndpoint(name="image provider", base_url="http://x", enabled=True)
                chat = ChatSession(name="new chat")
                db.add_all([endpoint, chat])
                db.commit()
                body = {
                    "session_id": chat.id,
                    "endpoint_id": endpoint.id,
                    "prompt": "a red square",
                    "request_id": str(uuid4()),
                }
                chat_id = chat.id
                db.close()

                def post():
                    client = TestClient(app)
                    try:
                        return client.post("/api/images/chat", json=body)
                    finally:
                        client.close()

                with (
                    patch("services.photos_store.photos_dir", return_value=root / "photos"),
                    patch("services.imagegen.generate", side_effect=fake_generate) as generate,
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    first = pool.submit(post)
                    second = pool.submit(post)
                    responses = [first.result(timeout=20), second.result(timeout=20)]
                self.assertEqual([response.status_code for response in responses], [200, 200])
                self.assertEqual(responses[0].json()["images"], responses[1].json()["images"])
                self.assertEqual(generate.call_count, 2)

                db = self.db()
                self.assertEqual(db.query(Photo).count(), 1)
                self.assertEqual(db.query(Message).filter_by(session_id=chat_id).count(), 2)
                self.assertEqual(db.get(ChatSession, chat_id).message_count, 2)
                self.assertEqual(len(notes_vault.all_notes()), 1)
                self.assertEqual(len(list((root / "photos").rglob("*.png"))), 1)
                self.assertEqual(len(list((root / "photos").rglob("*.jpg"))), 1)
                db.close()
            finally:
                database.SessionLocal.configure(bind=self.eng)
                database.engine = self.eng
                file_engine.dispose()

    def test_chat_image_note_status_write_failure_keeps_saved_turn(self):
        from io import BytesIO
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from PIL import Image
        from sqlalchemy import event
        from sqlalchemy.orm import Session as DbSession

        from core.database import Message, Photo
        from core.database import Session as ChatSession
        from services import notes_vault

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
            return [buf.getvalue()]

        def fail_note_status(db, _flush_context, _instances):
            if any(isinstance(row, Message) for row in db.dirty):
                raise OSError("note status database write failed")

        with (
            TemporaryDirectory() as temp,
            patch("services.photos_store.photos_dir", return_value=Path(temp)),
            patch("services.imagegen.generate", side_effect=fake_generate),
        ):
            event.listen(DbSession, "before_flush", fail_note_status)
            try:
                response = self.client.post(
                    "/api/images/chat",
                    json={
                        "session_id": chat_id,
                        "endpoint_id": endpoint_id,
                        "prompt": "a red square",
                    },
                )
            finally:
                event.remove(DbSession, "before_flush", fail_note_status)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("saved to notes", response.json()["content"])
            self.assertEqual(len(response.json()["images"]), 1)
            self.assertEqual(
                self.client.get(response.json()["images"][0]["original"]).status_code, 200
            )

        db = self.db()
        self.assertEqual(db.query(Photo).count(), 1)
        messages = db.query(Message).filter_by(session_id=chat_id).order_by(Message.timestamp).all()
        self.assertEqual(len(messages), 2)
        self.assertIn("image generated", messages[1].content)
        self.assertIsNone(messages[1].meta_dict()["note_id"])
        self.assertEqual(db.get(ChatSession, chat_id).message_count, 2)
        self.assertEqual(len(notes_vault.all_notes()), 1)
        db.close()
        history = self.client.get(f"/api/sessions/{chat_id}/history").json()
        self.assertEqual(len(history["messages"]), 2)
        self.assertIn("image generated", history["messages"][1]["content"])

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
        history = self.client.get(f"/api/sessions/{sid}/history").json()
        self.assertIn("saved to notes", history["messages"][1]["content"])
        self.assertEqual(history["messages"][1]["meta"]["note_id"], j["doc_id"])

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
