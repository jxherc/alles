import json
from tests._client import ApiTest
from core.database import ModelEndpoint
from services.imagegen import is_image_model, image_models
from routes.models import _is_chat_model


class ImagesApiTest(ApiTest):
    def test_empty_prompt_400(self):
        self.assertEqual(
            self.client.post("/api/images/generate", json={"prompt": "  "}).status_code, 400
        )

    def test_no_endpoint_400(self):
        # fresh db has no model endpoint → clean error, not a crash
        r = self.client.post("/api/images/generate", json={"prompt": "a red bicycle"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("endpoint", r.json()["detail"].lower())

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
        from core.database import Session as Sess, ModelEndpoint, Note, Message

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
        self.assertIn("saved to docs", j["content"])
        self.assertTrue(j["doc_id"])
        d = self.db()
        self.assertEqual(d.query(Note).count(), 1)  # filed as a note (the live docs app)
        self.assertEqual(d.query(Message).filter_by(session_id=sid).count(), 2)
        self.assertEqual(d.get(Sess, sid).name, "a red square")
        d.close()

    def test_chat_image_incognito_leaves_no_trace(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("PIL not available")
        from io import BytesIO
        import services.imagegen as ig
        from core.database import Session as Sess, ModelEndpoint, Note, Message

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
        d = self.db()
        self.assertEqual(d.query(Note).count(), 0)
        self.assertEqual(d.query(Message).filter_by(session_id=sid).count(), 0)
        d.close()
