import io
import json
from collections import OrderedDict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from core.database import Album, Face, Person, Photo, TrashItem, get_db
from routes.vault import _master_pw
from services import photos_store as ps
from services import trash

router = APIRouter(prefix="/api/photos")


def _kw_list(s) -> list[str]:
    return [k for k in (s or "").split(",") if k]


def _norm_kw(kws) -> str:
    """lowercase, trim, drop blanks, dedup (order-stable) → csv."""
    seen, out = set(), []
    for k in kws or []:
        k = str(k).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return ",".join(out)


def _fmt(p: Photo) -> dict:
    return {
        "id": p.id,
        "thumb": f"/api/photos/thumb/{p.id}",
        "original": f"/api/photos/original/{p.id}",
        "width": p.width,
        "height": p.height,
        "taken_at": p.taken_at.isoformat() if p.taken_at else None,
        "favorite": p.favorite,
        "album_id": p.album_id,
        "original_name": p.original_name,
        "caption": p.caption or "",
        "keywords": _kw_list(p.keywords),
        "hidden": bool(p.hidden),
        "archived": bool(p.archived),
        "is_video": bool(p.is_video),
        "aspect_ratio": p.aspect_ratio or ((p.width / p.height) if (p.width and p.height) else None),
        "preview": ("data:image/jpeg;base64," + p.preview) if p.preview else "",
        "stack_id": p.stack_id,
        "exif": json.loads(p.exif or "{}"),
    }


def _attach_stacks(out, db):
    """tag cover items with stack_count so the grid can show a stack badge. one grouped query."""
    cover_ids = [it["id"] for m in out["moments"] for it in m["items"] if it.get("stack_id") == it["id"]]
    if not cover_ids:
        return out
    counts = dict(
        db.query(Photo.stack_id, func.count(Photo.id))
        .filter(Photo.stack_id.in_(cover_ids), Photo.deleted_at == None)  # noqa: E711
        .group_by(Photo.stack_id)
        .all()
    )
    for m in out["moments"]:
        for it in m["items"]:
            if it["id"] in counts:
                it["stack_count"] = counts[it["id"]]
    return out


def _moments(rows):
    rows.sort(key=lambda p: p.taken_at or p.created_at or datetime.min, reverse=True)
    moments = OrderedDict()
    for p in rows:
        d = p.taken_at or p.created_at or datetime.utcnow()
        moments.setdefault(d.strftime("%Y-%m-%d"), (d, []))[1].append(_fmt(p))
    out = [{"date": k, "label": _label(v[0]), "items": v[1]} for k, v in moments.items()]
    return {"moments": out, "count": len(rows)}


def _label(d: datetime) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"  # avoid %-d (not on Windows)


@router.get("/smart")
def smart_photos(
    period: str = Query("month"),
    from_date: str = Query(""),
    to_date: str = Query(""),
    keyword: str = Query(""),
    db: DbSession = Depends(get_db),
):
    """4c - smart albums: EXIF-date grouping (period=month|day) + optional date-range / keyword filter."""
    from services import smart_albums

    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at == None)  # noqa: E711
        .filter((Photo.hidden == False) | (Photo.hidden == None))  # noqa: E711,E712
        .all()
    )
    photos = [
        {
            "id": p.id,
            "taken_at": p.taken_at.isoformat() if p.taken_at else "",
            "keywords": p.keywords or "",
        }
        for p in rows
    ]
    if from_date and to_date:
        photos = smart_albums.in_range(photos, from_date, to_date)
    if keyword:
        photos = smart_albums.by_keyword(photos, keyword)
    groups = smart_albums.group_by_period(photos, period=period)
    return {"groups": {k: [p["id"] for p in v] for k, v in groups.items()}, "count": len(photos)}


def _apply_filters(q, type_, camera, from_, to):
    """structured facets — media type, camera (EXIF make/model), and a taken-date range.
    the cheap stand-in for content search; covers most real 'find that photo' queries."""
    if type_ == "video":
        q = q.filter(Photo.is_video == True)  # noqa: E712
    elif type_ == "image":
        q = q.filter((Photo.is_video == False) | (Photo.is_video == None))  # noqa: E711,E712
    if camera:
        # exif is JSON text with separate Make/Model — require every token to appear
        for tok in camera.split():
            q = q.filter(Photo.exif.like(f"%{tok}%"))
    taken = func.coalesce(Photo.taken_at, Photo.created_at)
    if from_:
        try:
            q = q.filter(taken >= datetime.fromisoformat(from_))
        except ValueError:
            pass
    if to:
        try:
            q = q.filter(taken < datetime.fromisoformat(to) + timedelta(days=1))  # inclusive end-of-day
        except ValueError:
            pass
    return q


@router.get("/list")
def list_photos(
    album: str = Query(""),
    favorites: bool = Query(False),
    type: str = Query(""),  # image | video
    camera: str = Query(""),
    from_: str = Query("", alias="from"),
    to: str = Query(""),
    offset: int = Query(0),
    limit: int = Query(0),  # 0 = no paging (return everything)
    db: DbSession = Depends(get_db),
):
    q = db.query(Photo).filter(Photo.deleted_at == None)  # noqa: E711
    q = q.filter((Photo.hidden == False) | (Photo.hidden == None))  # noqa: E711,E712
    if album:
        q = q.filter(Photo.album_id == album)
    else:
        # archived assets drop out of the main timeline + favorites, but stay inside their albums
        q = q.filter((Photo.archived == False) | (Photo.archived == None))  # noqa: E711,E712
    if favorites:
        q = q.filter(Photo.favorite == True)  # noqa: E712
    q = _apply_filters(q, type, camera, from_, to)
    # collapse stacks: show only covers + un-stacked photos
    q = q.filter((Photo.stack_id == None) | (Photo.stack_id == Photo.id))  # noqa: E711
    if limit and limit > 0:
        # paged: order in sql (newest first, id as a stable tiebreak) and slice
        q = q.order_by(func.coalesce(Photo.taken_at, Photo.created_at).desc(), Photo.id.desc())
        rows = q.offset(max(0, offset)).limit(limit).all()
        out = _moments(rows)
        out["next"] = (offset + limit) if len(rows) == limit else None
        return _attach_stacks(out, db)
    return _attach_stacks(_moments(q.all()), db)


@router.get("/facets")
def facets(db: DbSession = Depends(get_db)):
    """distinct cameras present in the live library — powers the filter dropdown."""
    rows = db.query(Photo.exif).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
    ).all()
    cams = set()
    for (ex,) in rows:
        d = json.loads(ex or "{}")
        name = " ".join(str(x) for x in (d.get("Make"), d.get("Model")) if x).strip()
        if name:
            cams.add(name)
    return {"cameras": sorted(cams)}


@router.get("/duplicates")
def duplicates(db: DbSession = Depends(get_db)):
    """byte-identical live photos grouped by sha256 (2+ per group). oldest first = suggested keep."""
    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at == None, Photo.checksum != None)  # noqa: E711
        .all()
    )
    groups = {}
    for p in rows:
        groups.setdefault(p.checksum, []).append(p)
    out = []
    for cs, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda p: p.created_at or datetime.min)  # oldest first → keep that one
        out.append({"checksum": cs, "items": [_fmt(p) for p in items]})
    return {"groups": out, "count": sum(len(g["items"]) for g in out)}


class StackBody(BaseModel):
    ids: list[str]


@router.post("/stack")
def stack(body: StackBody, db: DbSession = Depends(get_db)):
    """group photos under one cover (largest by area). pulls in members of any stack touched."""
    ids = set(body.ids)
    rows = db.query(Photo).filter(Photo.id.in_(ids), Photo.deleted_at == None).all()  # noqa: E711
    if len(rows) < 2:
        raise HTTPException(400, "select at least 2 photos to stack")
    existing = {r.stack_id for r in rows if r.stack_id}
    if existing:  # merge: absorb every member of any stack among the selection
        ids |= {m.id for m in db.query(Photo).filter(Photo.stack_id.in_(existing), Photo.deleted_at == None).all()}  # noqa: E711
        rows = db.query(Photo).filter(Photo.id.in_(ids), Photo.deleted_at == None).all()  # noqa: E711
    cover = max(rows, key=lambda p: (p.width or 0) * (p.height or 0))
    for p in rows:
        p.stack_id = cover.id
    db.commit()
    return {"ok": True, "cover": cover.id, "count": len(rows)}


class StackIdBody(BaseModel):
    id: str


@router.post("/unstack")
def unstack(body: StackIdBody, db: DbSession = Depends(get_db)):
    p = db.get(Photo, body.id)
    if not p:
        raise HTTPException(404)
    sid = p.stack_id or p.id
    db.query(Photo).filter(Photo.stack_id == sid).update({Photo.stack_id: None})
    db.commit()
    return {"ok": True}


@router.get("/stack/{cover_id}")
def stack_members(cover_id: str, db: DbSession = Depends(get_db)):
    """all photos in a stack, cover first — used to expand a stack in the viewer."""
    rows = db.query(Photo).filter(Photo.stack_id == cover_id, Photo.deleted_at == None).all()  # noqa: E711
    rows.sort(key=lambda p: (p.id != cover_id, p.taken_at or p.created_at or datetime.min))
    return {"items": [_fmt(p) for p in rows]}


@router.get("/archive")
def list_archive(db: DbSession = Depends(get_db)):
    """the archive — assets pushed out of the main timeline but kept in the library."""
    rows = (
        db.query(Photo)
        .filter(
            Photo.deleted_at == None,  # noqa: E711
            Photo.archived == True,  # noqa: E712
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        )
        .all()
    )
    return _moments(rows)


@router.get("/hidden")
def list_hidden(db: DbSession = Depends(get_db), _pw: str = Depends(_master_pw)):
    """the hidden/locked album — only reachable with a valid vault unlock token (7a)."""
    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at == None, Photo.hidden == True)  # noqa: E711,E712
        .all()
    )
    return _moments(rows)


@router.get("/search")
def search_photos(q: str = Query(...), db: DbSession = Depends(get_db)):
    """match on filename, EXIF (camera make/model), and the date ('june 2026',
    '2026-06', a year). returns the same moments shape as /list."""
    ql = (q or "").strip().lower()
    if not ql:
        return {"moments": [], "count": 0}
    hits = []
    base = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
    )
    for p in base.all():
        d = p.taken_at or p.created_at
        hay = " ".join(
            [
                (p.original_name or "").lower(),
                (p.exif or "").lower(),
                (p.caption or "").lower(),
                (p.keywords or "").lower(),
                (d.isoformat().lower() if d else ""),
                (d.strftime("%B %Y").lower() if d else ""),
            ]
        )
        if ql in hay:
            hits.append(p)
    hits.sort(key=lambda p: p.taken_at or p.created_at or datetime.min, reverse=True)
    moments = OrderedDict()
    for p in hits:
        d = p.taken_at or p.created_at or datetime.utcnow()
        moments.setdefault(d.strftime("%Y-%m-%d"), (d, []))[1].append(_fmt(p))
    out = [{"date": k, "label": _label(v[0]), "items": v[1]} for k, v in moments.items()]
    return {"moments": out, "count": len(hits)}


@router.get("/clip-status")
def clip_status(db: DbSession = Depends(get_db)):
    """is semantic search available, and how much of the library is indexed."""
    from services import clip

    av = clip.available()
    indexed = db.query(Photo).filter(Photo.clip != None).count() if av else 0  # noqa: E711
    total = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.is_video == False) | (Photo.is_video == None),  # noqa: E711,E712
    ).count()
    return {"available": av, "indexed": indexed, "total": total}


@router.get("/semantic")
def semantic(q: str = Query(...), db: DbSession = Depends(get_db)):
    """CLIP 'find by content' search — results in relevance order. empty if ML isn't set up."""
    from services import clip

    if not clip.available():
        return {"moments": [], "count": 0, "unavailable": True}
    if not (q or "").strip():
        return {"moments": [], "count": 0}
    hits = clip.search(db, q)
    if not hits:
        return {"moments": [], "count": 0}
    rank = {pid: i for i, (pid, _) in enumerate(hits)}
    rows = db.query(Photo).filter(
        Photo.id.in_(list(rank)),
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
    ).all()
    rows.sort(key=lambda p: rank.get(p.id, 1 << 30))
    return {"moments": [{"date": "", "label": "best matches", "items": [_fmt(p) for p in rows]}], "count": len(rows)}


# ── people & faces (phase 7a) ──
def _person_counts(db, person_ids=None):
    """{person_id: #distinct live photos} — one grouped query, not N+1."""
    q = (
        db.query(Face.person_id, func.count(func.distinct(Face.photo_id)))
        .join(Photo, Photo.id == Face.photo_id)
        .filter(
            Face.person_id != None,  # noqa: E711
            Photo.deleted_at == None,  # noqa: E711
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        )
    )
    if person_ids is not None:
        q = q.filter(Face.person_id.in_(person_ids))
    return dict(q.group_by(Face.person_id).all())


def _cover_face(db, per) -> str | None:
    if per.cover_face_id:
        return per.cover_face_id
    f = (
        db.query(Face.id)
        .filter(Face.person_id == per.id)
        .order_by(Face.det_score.desc())
        .first()
    )
    return f[0] if f else None


@router.get("/faces-status")
def faces_status(db: DbSession = Depends(get_db)):
    """is face recognition available, and how much of the library is scanned."""
    from services import faces

    av = faces.available()
    scanned = db.query(Photo).filter(Photo.faces_at != None).count() if av else 0  # noqa: E711
    total = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.is_video == False) | (Photo.is_video == None),  # noqa: E711,E712
    ).count()
    return {
        "available": av,
        "scanned": scanned,
        "total": total,
        "people": db.query(Person).filter(Person.hidden == False).count() if av else 0,  # noqa: E712
        "faces": db.query(Face).count() if av else 0,
    }


@router.get("/people")
def people(db: DbSession = Depends(get_db)):
    """face clusters for the People view — named first, then unnamed by size. one query each."""
    rows = db.query(Person).filter(Person.hidden == False).all()  # noqa: E712
    counts = _person_counts(db, [p.id for p in rows])
    out = []
    for p in rows:
        c = counts.get(p.id, 0)
        if not c:
            continue  # every face landed on a hidden/trashed photo — nothing to show
        cover = _cover_face(db, p)
        out.append({
            "id": p.id,
            "name": p.name or "",
            "count": c,
            "cover": f"/api/photos/face/{cover}" if cover else "",
        })
    # named people first (alpha), then the unnamed clusters by how many photos they're in
    out.sort(key=lambda d: (d["name"] == "", d["name"].lower() if d["name"] else -d["count"]))
    return {"people": out, "count": len(out)}


@router.get("/person/{pid}")
def person_photos(pid: str, db: DbSession = Depends(get_db)):
    """the timeline of every live photo this person appears in."""
    per = db.get(Person, pid)
    if not per:
        raise HTTPException(404)
    photo_ids = [
        r[0] for r in db.query(func.distinct(Face.photo_id)).filter(Face.person_id == pid).all()
    ]
    rows = (
        db.query(Photo)
        .filter(
            Photo.id.in_(photo_ids),
            Photo.deleted_at == None,  # noqa: E711
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        )
        .all()
    )
    out = _moments(rows)
    out["person"] = {"id": per.id, "name": per.name or ""}
    return out


class NameBody(BaseModel):
    name: str


@router.post("/person/{pid}/name")
def name_person(pid: str, body: NameBody, db: DbSession = Depends(get_db)):
    per = db.get(Person, pid)
    if not per:
        raise HTTPException(404)
    per.name = (body.name or "").strip()
    db.commit()
    return {"ok": True, "id": per.id, "name": per.name}


@router.post("/person/{pid}/hide")
def hide_person(pid: str, db: DbSession = Depends(get_db)):
    """drop a cluster from the People view (e.g. a bad detection / 'not a person')."""
    per = db.get(Person, pid)
    if not per:
        raise HTTPException(404)
    per.hidden = True
    db.commit()
    return {"ok": True}


class MergeBody(BaseModel):
    ids: list[str]


@router.post("/people/merge")
def merge_people(body: MergeBody, db: DbSession = Depends(get_db)):
    """fold several clusters into one — for when the same person split into two faces groups."""
    ids = [i for i in dict.fromkeys(body.ids)]  # de-dup, keep order
    if len(ids) < 2:
        raise HTTPException(400, "select at least 2 people to merge")
    people = {p.id: p for p in db.query(Person).filter(Person.id.in_(ids)).all()}
    keep = next((people[i] for i in ids if i in people), None)
    if keep is None:
        raise HTTPException(404)
    if not keep.name:  # adopt the first real name among the merged set
        for i in ids:
            if people.get(i) and people[i].name:
                keep.name = people[i].name
                break
    drop = [i for i in ids if i != keep.id and i in people]
    if drop:
        db.query(Face).filter(Face.person_id.in_(drop)).update({Face.person_id: keep.id}, synchronize_session=False)
        for i in drop:
            db.delete(people[i])
    keep.cover_face_id = _cover_face(db, keep)
    db.commit()
    return {"ok": True, "id": keep.id, "name": keep.name or ""}


@router.get("/photo/{pid}/faces")
def photo_faces(pid: str, db: DbSession = Depends(get_db)):
    """faces found in one photo, with their person — drives the face chips in the lightbox."""
    rows = db.query(Face).filter(Face.photo_id == pid).order_by(Face.det_score.desc()).all()
    pmap = {}
    pids = {f.person_id for f in rows if f.person_id}
    if pids:
        pmap = {p.id: p for p in db.query(Person).filter(Person.id.in_(pids)).all()}
    out = []
    for f in rows:
        per = pmap.get(f.person_id)
        out.append({
            "id": f.id,
            "person_id": f.person_id,
            "name": (per.name if per else "") or "",
            "thumb": f"/api/photos/face/{f.id}",
        })
    return {"faces": out, "count": len(out)}


@router.get("/face/{fid}")
def face_crop(fid: str, db: DbSession = Depends(get_db)):
    """a square-ish crop of a single face, for avatars + chips. padded a little past the bbox."""
    from PIL import Image, ImageOps

    f = db.get(Face, fid)
    if not f:
        raise HTTPException(404)
    p = db.get(Photo, f.photo_id)
    if not p:
        raise HTTPException(404)
    op = ps.original_path(p.filename)
    if not op.is_file():
        raise HTTPException(404)
    try:
        im = ImageOps.exif_transpose(Image.open(op).convert("RGB"))
        x1, y1, x2, y2 = (int(v) for v in (f.bbox or "0,0,0,0").split(","))
        bw, bh = max(1, x2 - x1), max(1, y2 - y1)
        pad = 0.4
        cx1 = max(0, int(x1 - bw * pad)); cy1 = max(0, int(y1 - bh * pad))
        cx2 = min(im.width, int(x2 + bw * pad)); cy2 = min(im.height, int(y2 + bh * pad))
        crop = im.crop((cx1, cy1, cx2, cy2))
        crop.thumbnail((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, "JPEG", quality=85)
    except Exception:
        raise HTTPException(404)
    return Response(content=buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/map")
def photos_map(db: DbSession = Depends(get_db)):
    """located photos for the map view — only ones with GPS in EXIF, excludes hidden+deleted."""
    rows = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        (Photo.archived == False) | (Photo.archived == None),  # noqa: E711,E712
    )
    points = []
    for p in rows.all():
        ex = json.loads(p.exif or "{}")
        lat, lon = ex.get("lat"), ex.get("lon")
        if lat is None or lon is None:
            continue
        points.append(
            {
                "id": p.id,
                "lat": lat,
                "lon": lon,
                "thumb": f"/api/photos/thumb/{p.id}",
                "original": f"/api/photos/original/{p.id}",
                "caption": p.caption or "",
                "taken_at": p.taken_at.isoformat() if p.taken_at else None,
            }
        )
    return {"points": points, "count": len(points)}


@router.get("/places")
def places(db: DbSession = Depends(get_db)):
    """group geotagged photos by nearest city (offline reverse-geocode) → Explore/Places tiles."""
    from services import places as geo

    rows = (
        db.query(Photo)
        .filter(
            Photo.deleted_at == None,  # noqa: E711
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
            (Photo.archived == False) | (Photo.archived == None),  # noqa: E711,E712
        )
        .order_by(func.coalesce(Photo.taken_at, Photo.created_at).desc())
        .all()
    )
    groups = {}
    for p in rows:
        ex = json.loads(p.exif or "{}")
        lat, lon = ex.get("lat"), ex.get("lon")
        if lat is None or lon is None:
            continue
        loc = geo.nearest(lat, lon)
        if not loc:
            continue
        key = f'{loc["cc"]}/{loc["city"]}'
        g = groups.get(key)
        if not g:  # rows are newest-first, so the first photo seen for a place is its cover
            g = groups[key] = {"city": loc["city"], "country": loc["country"], "cc": loc["cc"], "count": 0, "cover": p.id}
        g["count"] += 1
    out = sorted(groups.values(), key=lambda g: -g["count"])
    for g in out:
        g["cover"] = f'/api/photos/thumb/{g["cover"]}'
    return {"places": out, "count": len(out)}


@router.get("/place")
def place_photos(cc: str = Query(...), city: str = Query(...), db: DbSession = Depends(get_db)):
    """all photos whose nearest city matches (cc, city) — the moments behind one Places tile."""
    from services import places as geo

    rows = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        (Photo.archived == False) | (Photo.archived == None),  # noqa: E711,E712
    ).all()
    hits = []
    for p in rows:
        ex = json.loads(p.exif or "{}")
        lat, lon = ex.get("lat"), ex.get("lon")
        if lat is None or lon is None:
            continue
        loc = geo.nearest(lat, lon)
        if loc and loc["cc"] == cc and loc["city"] == city:
            hits.append(p)
    return _moments(hits)


@router.get("/memories")
def memories(date: str = Query(""), db: DbSession = Depends(get_db)):
    """'on this day' — photos taken the same month/day in strictly earlier years,
    grouped by how many years ago. default date is today."""
    try:
        ref = datetime.fromisoformat(date) if date else datetime.utcnow()
    except ValueError:
        raise HTTPException(400, "date must be ISO (YYYY-MM-DD)")
    rows = db.query(Photo).filter(
        Photo.deleted_at == None,  # noqa: E711
        (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        (Photo.archived == False) | (Photo.archived == None),  # noqa: E711,E712
        Photo.taken_at != None,  # noqa: E711
    )
    buckets = {}  # years_ago -> [photos]
    for p in rows.all():
        t = p.taken_at
        if t.month == ref.month and t.day == ref.day and t.year < ref.year:
            buckets.setdefault(ref.year - t.year, []).append(p)
    groups = []
    for ya in sorted(buckets):
        items = sorted(buckets[ya], key=lambda p: p.taken_at, reverse=True)
        groups.append(
            {
                "years_ago": ya,
                "year": ref.year - ya,
                "date": f"{ref.year - ya:04d}-{ref.month:02d}-{ref.day:02d}",
                "items": [_fmt(p) for p in items],
            }
        )
    return {"groups": groups, "count": sum(len(g["items"]) for g in groups)}


class CollageBody(BaseModel):
    ids: list[str]
    cols: int = 3


@router.post("/collage")
def collage(body: CollageBody, db: DbSession = Depends(get_db)):
    """build a PIL grid collage from the given photos and save it as a new photo."""
    if not body.ids:
        raise HTTPException(400, "no photos given")
    paths = []
    for pid in body.ids:
        p = db.get(Photo, pid)
        if not p or p.deleted_at is not None:
            continue  # skip unknown / trashed
        op = ps.original_path(p.filename)
        if op.is_file():
            paths.append(op)
    if not paths:
        raise HTTPException(400, "no usable photos")
    try:
        raw = ps.make_collage(paths, cols=body.cols)
    except ValueError as e:
        raise HTTPException(400, str(e))
    info = ps.import_image(raw, "collage.png")
    np = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
        aspect_ratio=info.get("aspect_ratio"),
        preview=info.get("preview", ""),
        checksum=info.get("checksum"),
    )
    db.add(np)
    db.commit()
    db.refresh(np)
    return _fmt(np)


class EditSaveBody(BaseModel):
    data_url: str
    name: str = "edited.png"


@router.post("/edit-save")
def edit_save(body: EditSaveBody, db: DbSession = Depends(get_db)):
    """save an edited image (a canvas data-url from the editor) as a new photo."""
    import base64

    du = body.data_url or ""
    if "," in du:
        du = du.split(",", 1)[1]
    try:
        raw = base64.b64decode(du)
    except Exception:
        raise HTTPException(400, "bad image data")
    if not raw:
        raise HTTPException(400, "empty image")
    try:
        info = ps.import_image(raw, body.name or "edited.png")
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
        aspect_ratio=info.get("aspect_ratio"),
        preview=info.get("preview", ""),
        checksum=info.get("checksum"),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _fmt(p)


@router.post("/upload")
async def upload(
    album_id: str = Form(""), file: UploadFile = File(...), db: DbSession = Depends(get_db)
):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "file too large (100MB max)")
    try:
        info = ps.import_media(data, file.filename or "photo.jpg")
    except ValueError as e:
        raise HTTPException(400, str(e))
    p = Photo(
        filename=info["filename"],
        thumb=info["thumb"],
        original_name=info["original_name"],
        width=info["width"],
        height=info["height"],
        taken_at=info["taken_at"],
        exif=info["exif"],
        aspect_ratio=info.get("aspect_ratio"),
        preview=info.get("preview", ""),
        checksum=info.get("checksum"),
        is_video=info.get("is_video", False),
        album_id=album_id or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _fmt(p)


class SyncBody(BaseModel):
    source: str  # a folder path (iCloud Drive / Photos export / any synced dir)


@router.post("/sync")
def sync(body: SyncBody, db: DbSession = Depends(get_db)):
    """import new images from a folder, skipping anything already pulled in."""
    from services import photo_sync

    try:
        return photo_sync.sync_folder(body.source, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/sync/macos")
def sync_macos():
    """pull from the macOS Photos library (Mac mini only) then import."""
    import shutil
    import tempfile

    from services import photo_sync

    dest = tempfile.mkdtemp(prefix="alles-photos-")
    try:
        photo_sync.pull_from_macos_photos(dest)
        return photo_sync.sync_folder(dest)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        # the originals are already copied into the library by import; don't leak the GB-sized export
        shutil.rmtree(dest, ignore_errors=True)


@router.get("/thumb/{pid}")
def thumb(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    tp = ps.thumb_path(p.thumb)
    if tp and tp.is_file():
        return FileResponse(str(tp))
    op = ps.original_path(p.filename)  # fall back to the original if no thumb
    if op.is_file():
        return FileResponse(str(op))
    raise HTTPException(404)


@router.get("/original/{pid}")
def original(pid: str, download: bool = False, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    op = ps.original_path(p.filename)
    if not op.is_file():
        raise HTTPException(404)
    return FileResponse(str(op), filename=p.original_name if download else None)


@router.delete("/{pid}")
def delete_photo(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    # soft-delete (1d): keep the files, hide it, record in the trash registry
    p.deleted_at = datetime.utcnow()
    db.commit()
    trash.record(db, "photo", pid, p.original_name or p.filename)
    return {"ok": True, "trashed": True}


@router.get("/trash")
def photo_trash(db: DbSession = Depends(get_db)):
    rows = (
        db.query(Photo)
        .filter(Photo.deleted_at != None)  # noqa: E711
        .order_by(Photo.deleted_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "thumb": f"/api/photos/thumb/{p.id}",
            "original_name": p.original_name,
            "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None,
        }
        for p in rows
    ]


@router.post("/{pid}/restore")
def restore_photo(pid: str, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p or p.deleted_at is None:
        raise HTTPException(404)
    p.deleted_at = None
    db.query(TrashItem).filter_by(kind="photo", ref=pid).delete()
    db.commit()
    return {"ok": True, "restored": pid}


class PatchPhoto(BaseModel):
    favorite: bool | None = None
    album_id: str | None = None
    caption: str | None = None
    keywords: list[str] | None = None
    hidden: bool | None = None
    archived: bool | None = None


@router.patch("/{pid}")
def patch_photo(pid: str, body: PatchPhoto, db: DbSession = Depends(get_db)):
    p = db.get(Photo, pid)
    if not p:
        raise HTTPException(404)
    if body.favorite is not None:
        p.favorite = body.favorite
    if body.album_id is not None:
        p.album_id = body.album_id or None
    if body.caption is not None:
        p.caption = body.caption.strip()
    if body.keywords is not None:
        p.keywords = _norm_kw(body.keywords)
    if body.hidden is not None:
        p.hidden = body.hidden
    if body.archived is not None:
        p.archived = body.archived
    db.commit()
    return _fmt(p)


_BATCH_ACTIONS = {
    "favorite", "unfavorite", "archive", "unarchive",
    "hide", "unhide", "album", "delete", "restore",
}


class BatchBody(BaseModel):
    ids: list[str]
    action: str
    album_id: str | None = None  # only for action=album


@router.post("/batch")
def batch(body: BatchBody, db: DbSession = Depends(get_db)):
    """act on many photos in one call — favorite/archive/hide/move-to-album/delete/restore.
    keeps multi-select snappy (one round-trip, not N)."""
    if body.action not in _BATCH_ACTIONS:
        raise HTTPException(400, f"unknown action: {body.action}")
    if not body.ids:
        raise HTTPException(400, "no photos given")
    rows = db.query(Photo).filter(Photo.id.in_(body.ids)).all()
    a = body.action
    for p in rows:
        if a == "favorite":
            p.favorite = True
        elif a == "unfavorite":
            p.favorite = False
        elif a == "archive":
            p.archived = True
        elif a == "unarchive":
            p.archived = False
        elif a == "hide":
            p.hidden = True
        elif a == "unhide":
            p.hidden = False
        elif a == "album":
            p.album_id = body.album_id or None
        elif a == "delete":
            if p.deleted_at is None:
                p.deleted_at = datetime.utcnow()
                trash.record(db, "photo", p.id, p.original_name or p.filename)
        elif a == "restore":
            p.deleted_at = None
            db.query(TrashItem).filter_by(kind="photo", ref=p.id).delete()
    db.commit()
    return {"ok": True, "count": len(rows), "action": a}


# ── albums ──
@router.get("/albums")
def albums(db: DbSession = Depends(get_db)):
    # one grouped count for every album instead of a count query per album (N+1)
    counts = dict(
        db.query(Photo.album_id, func.count(Photo.id))
        .filter(
            Photo.album_id != None,  # noqa: E711
            Photo.deleted_at == None,  # noqa: E711
            (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
        )
        .group_by(Photo.album_id)
        .all()
    )
    return [
        {"id": a.id, "name": a.name, "count": counts.get(a.id, 0)}
        for a in db.query(Album).order_by(Album.created_at.desc()).all()
    ]


class AlbumBody(BaseModel):
    name: str


@router.post("/albums")
def add_album(body: AlbumBody, db: DbSession = Depends(get_db)):
    a = Album(name=body.name)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "name": a.name, "count": 0}


@router.delete("/albums/{aid}")
def del_album(aid: str, db: DbSession = Depends(get_db)):
    a = db.get(Album, aid)
    if not a:
        raise HTTPException(404)
    for p in db.query(Photo).filter(Photo.album_id == aid).all():
        p.album_id = None
    db.delete(a)
    db.commit()
    return {"ok": True}
