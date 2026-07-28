"""optional CLIP semantic search (phase 7b) — lightweight: onnxruntime + tokenizers, no torch.

models live in ALLES_CLIP_DIR (default <repo>/models/clip): visual/model.onnx, textual/model.onnx,
textual/tokenizer.json, visual/preprocess_cfg.json — Immich's ViT-B-32__openai ONNX exports.
everything lazy-loads; the module degrades to unavailable() if the deps or model files are missing,
so the app runs fine with the feature off."""

import io
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 512
_loaded = None  # (visual_session, textual_session, tokenizer, cfg)


def model_dir() -> Path:
    return Path(os.environ.get("ALLES_CLIP_DIR") or (ROOT / "models" / "clip"))


def available() -> bool:
    """true only if both the deps and the model files are present — gates the whole feature."""
    d = model_dir()
    if not (d / "visual" / "model.onnx").is_file() or not (d / "textual" / "model.onnx").is_file():
        return False
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except Exception:
        return False
    return True


def _load():
    global _loaded
    if _loaded is not None:
        return _loaded
    import onnxruntime as ort
    from tokenizers import Tokenizer

    d = model_dir()
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    vis = ort.InferenceSession(
        str(d / "visual" / "model.onnx"), so, providers=["CPUExecutionProvider"]
    )
    txt = ort.InferenceSession(
        str(d / "textual" / "model.onnx"), so, providers=["CPUExecutionProvider"]
    )
    tok = Tokenizer.from_file(str(d / "textual" / "tokenizer.json"))
    tok.enable_truncation(max_length=77)
    tok.enable_padding(length=77, pad_id=0)
    cfg = json.loads((d / "visual" / "preprocess_cfg.json").read_text())
    _loaded = (vis, txt, tok, cfg)
    return _loaded


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.clip(np.linalg.norm(v, axis=-1, keepdims=True), 1e-8, None)


def embed_text(text: str) -> np.ndarray:
    _, txt, tok, _ = _load()
    ids = np.array([tok.encode(text or "").ids], dtype=np.int32)
    out = txt.run(None, {"text": ids})[0]
    return _norm(out)[0]


def embed_image(data: bytes) -> np.ndarray:
    from PIL import Image, ImageOps

    vis, _, _, cfg = _load()
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)).convert("RGB"))
    s = int((cfg.get("size") or [224, 224])[0])
    # resize shortest side to s (bicubic), then center-crop s×s — matches preprocess_cfg
    w, h = im.size
    scale = s / min(w, h)
    im = im.resize((max(s, round(w * scale)), max(s, round(h * scale))), Image.BICUBIC)
    w, h = im.size
    left, top = (w - s) // 2, (h - s) // 2
    im = im.crop((left, top, left + s, top + s))
    x = np.asarray(im, dtype=np.float32) / 255.0
    x = (x - np.array(cfg["mean"], dtype=np.float32)) / np.array(cfg["std"], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None, ...].astype(np.float32)  # [1,3,s,s]
    out = vis.run(None, {"image": x})[0]
    return _norm(out)[0]


def to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(b) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def index_pending(db, limit=40) -> int:
    """embed up to `limit` not-yet-indexed photos. success → 512-float blob; failure → empty blob
    (so a broken file isn't retried forever). returns how many were embedded. no-op if unavailable."""
    if not available():
        return 0
    from core.database import Photo
    from services import photos_store as ps

    rows = (
        db.query(Photo)
        .filter(
            Photo.clip == None,  # noqa: E711
            Photo.deleted_at == None,  # noqa: E711
            (Photo.is_video == False) | (Photo.is_video == None),  # noqa: E711,E712
        )
        .limit(limit)
        .all()
    )
    n = 0
    for p in rows:
        try:
            data = ps.original_path(p.filename).read_bytes()
            p.clip = to_blob(embed_image(data))
            n += 1
        except Exception:
            p.clip = b""  # mark attempted so the filter skips it next pass
    if rows:
        db.commit()
    return n


def search(db, query: str, k=120):
    """rank live photos by cosine similarity to the text query. returns [(photo_id, score)]."""
    if not available():
        return []
    from core.database import Photo

    rows = (
        db.query(Photo.id, Photo.clip)
        .filter(Photo.clip != None, Photo.deleted_at == None)  # noqa: E711
        .all()
    )
    ids, mats = [], []
    for pid, blob in rows:
        if blob and len(blob) == DIM * 4:  # skip empty (failed) blobs
            ids.append(pid)
            mats.append(np.frombuffer(blob, dtype=np.float32))
    if not mats:
        return []  # nothing indexed → skip loading the model entirely
    qv = embed_text(query)
    sims = np.vstack(mats) @ qv  # both L2-normalized → dot product is cosine
    order = np.argsort(-sims)[:k]
    return [(ids[i], float(sims[i])) for i in order]
