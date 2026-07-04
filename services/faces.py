"""optional face recognition (phase 7a) — InsightFace buffalo_l via onnxruntime, no torch.

detect faces + 512-d ArcFace embeddings, then group them into people with a small numpy
threshold pass (no scikit-learn). models live in ALLES_FACES_DIR (default <repo>/models/faces);
insightface lays them out at <dir>/models/buffalo_l/*.onnx. everything is lazy and gated behind
available() so the app runs fine with the feature off."""

import io
import os
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIM = 512
_app = None  # cached insightface FaceAnalysis

# cosine thresholds for clustering normed ArcFace vectors
JOIN_T = 0.40   # attach a loose face to an existing person's centroid
NEW_T = 0.46    # group leftover faces into a brand-new person (stricter, avoids merging two people)
DET_T = 0.50    # min detector confidence to keep a face
MIN_SIZE = 2    # a new cluster needs at least this many faces to become a Person


def model_dir() -> Path:
    return Path(os.environ.get("ALLES_FACES_DIR") or (ROOT / "models" / "faces"))


def available() -> bool:
    """true only if the deps and the buffalo_l model files are present — gates the feature."""
    d = model_dir() / "models" / "buffalo_l"
    if not (d / "det_10g.onnx").is_file() or not (d / "w600k_r50.onnx").is_file():
        return False
    try:
        import insightface  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _load():
    global _app
    if _app is not None:
        return _app
    from insightface.app import FaceAnalysis

    # only the detection + recognition models — skip genderage/landmarks we don't use
    app = FaceAnalysis(
        name="buffalo_l",
        root=str(model_dir()),
        allowed_modules=["detection", "recognition"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))
    _app = app
    return _app


def to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(b) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def detect_embed(data: bytes):
    """find faces in image bytes. returns [{bbox:(x1,y1,x2,y2), score, emb(512 normed)}]."""
    from PIL import Image, ImageOps

    app = _load()
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)).convert("RGB"))
    arr = np.asarray(im)[:, :, ::-1].copy()  # RGB -> BGR, contiguous for onnx
    out = []
    for f in app.get(arr):
        x1, y1, x2, y2 = (int(v) for v in f.bbox)
        out.append({"bbox": (x1, y1, x2, y2), "score": float(f.det_score),
                    "emb": np.asarray(f.normed_embedding, dtype=np.float32)})
    return out


def index_pending(db, limit=20) -> int:
    """detect + store faces for up to `limit` un-scanned photos. marks each scanned (faces_at)
    even if it has zero faces, so it isn't reprocessed. returns how many faces were stored."""
    if not available():
        return 0
    from core.database import Face, Photo
    from services import photos_store as ps

    rows = (
        db.query(Photo)
        .filter(
            Photo.faces_at == None,  # noqa: E711
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
            for f in detect_embed(data):
                if f["score"] < DET_T:
                    continue
                db.add(Face(
                    photo_id=p.id,
                    bbox=",".join(str(v) for v in f["bbox"]),
                    det_score=f["score"],
                    embedding=to_blob(f["emb"]),
                ))
                n += 1
        except Exception:
            pass  # unreadable / non-image — still mark scanned below
        p.faces_at = datetime.utcnow()
    if rows:
        db.commit()
    return n


def _centroid(vecs) -> np.ndarray:
    m = np.mean(np.vstack(vecs), axis=0)
    return m / max(float(np.linalg.norm(m)), 1e-8)


def cluster(db, join_t=JOIN_T, new_t=NEW_T, min_size=MIN_SIZE) -> int:
    """assign every un-clustered face to a person. faces close to an existing person's centroid
    join it (keeps user-named clusters stable); the rest are grouped among themselves and any
    group of >= min_size becomes a new Person. singletons stay unassigned. returns #changed."""
    from core.database import Face, Person

    faces = db.query(Face).filter(Face.embedding != None).all()  # noqa: E711
    vecs, by_person, free = {}, {}, []
    for f in faces:
        if not f.embedding or len(f.embedding) != DIM * 4:
            continue
        vecs[f.id] = np.frombuffer(f.embedding, dtype=np.float32)
        if f.person_id:
            by_person.setdefault(f.person_id, []).append(f)
        else:
            free.append(f)
    if not free:
        return 0

    cids = list(by_person)
    cmat = np.vstack([_centroid([vecs[x.id] for x in by_person[c] if x.id in vecs]) for c in cids]) if cids else None

    changed = 0
    still = []
    for f in free:
        v = vecs[f.id]
        if cmat is not None:
            sims = cmat @ v
            j = int(np.argmax(sims))
            if float(sims[j]) >= join_t:
                f.person_id = cids[j]
                changed += 1
                continue
        still.append(f)

    if still:
        # union-find over leftovers at the (stricter) new-cluster threshold
        parent = list(range(len(still)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        M = np.vstack([vecs[f.id] for f in still])
        sims = M @ M.T
        for i in range(len(still)):
            for j in range(i + 1, len(still)):
                if sims[i, j] >= new_t:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
        groups = {}
        for i, f in enumerate(still):
            groups.setdefault(find(i), []).append(f)
        for g in groups.values():
            if len(g) < min_size:
                continue  # one-off face — leave it unassigned
            per = Person()
            db.add(per)
            db.flush()
            best = max(g, key=lambda f: f.det_score or 0)
            per.cover_face_id = best.id
            for f in g:
                f.person_id = per.id
            changed += 1

    if changed:
        db.commit()
    return changed
