"""phase 7b — CLIP semantic search: ranking math, endpoints, and (when models are present) indexing."""

import io
from unittest import mock, skipUnless

import numpy as np
from PIL import Image

from core.database import Photo
from services import clip
from tests._client import ApiTest


def _e(i):  # a 512-dim unit basis vector
    v = np.zeros(clip.DIM, dtype=np.float32)
    v[i] = 1.0
    return v


class ClipSemanticTests(ApiTest):
    def _photo(self, name="f.jpg", clipvec=None, **kw):
        db = self.db()
        if clipvec is not None:
            kw["clip"] = clip.to_blob(clipvec)
        p = Photo(filename="s-" + name, original_name=name, **kw)
        db.add(p)
        db.commit()
        pid = p.id
        db.close()
        return pid

    def test_clip_status_shape(self):
        d = self.client.get("/api/photos/clip-status").json()
        for k in ("available", "indexed", "total"):
            self.assertIn(k, d)

    def test_semantic_empty_when_nothing_indexed(self):
        # no clip blobs → empty result, and (importantly) the model is never loaded
        d = self.client.get("/api/photos/semantic?q=a red bicycle").json()
        self.assertEqual(d["moments"], [])

    def test_search_ranks_by_cosine(self):
        a = self._photo(name="a.jpg", clipvec=_e(0))
        self._photo(name="b.jpg", clipvec=_e(1))
        with mock.patch.object(clip, "available", return_value=True), \
             mock.patch.object(clip, "embed_text", return_value=_e(0)):
            db = self.db()
            hits = clip.search(db, "x")
            db.close()
        self.assertEqual(hits[0][0], a)  # the vector closest to the query ranks first

    def test_search_skips_failed_blobs(self):
        self._photo(name="bad.jpg", clipvec=None, clip=b"")  # failed-index marker
        with mock.patch.object(clip, "available", return_value=True), \
             mock.patch.object(clip, "embed_text", return_value=_e(0)):
            db = self.db()
            hits = clip.search(db, "x")
            db.close()
        self.assertEqual(hits, [])

    @skipUnless(clip.available(), "CLIP models not present")
    def test_index_pending_stores_embedding(self):
        b = io.BytesIO()
        Image.new("RGB", (64, 64), (120, 90, 160)).save(b, "JPEG")
        d = self.client.post("/api/photos/upload", files={"file": ("x.jpg", b.getvalue(), "image/jpeg")}).json()
        db = self.db()
        n = clip.index_pending(db, limit=10)
        db.close()
        self.assertGreaterEqual(n, 1)
        db = self.db()
        blob = db.get(Photo, d["id"]).clip
        db.close()
        self.assertEqual(len(blob), clip.DIM * 4)  # a real 512-float32 embedding landed
