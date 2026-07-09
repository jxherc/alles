import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession

from core.database import GalleryImage, get_db, _uid
from core.settings import data_dir

router = APIRouter(prefix="/api")

GALLERY_DIR: Path | None = None

_ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
_RASTER = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_PAGE_MAX = 120
_THUMB = 420


def gallery_dir() -> Path:
    d = GALLERY_DIR or data_dir() / "gallery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbs_dir() -> Path:
    d = gallery_dir() / ".thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fmt(img: GalleryImage) -> dict:
    return {
        "id": img.id,
        "filename": img.filename,
        "prompt": img.prompt,
        "tags": img.tags,
        "source": img.source,
        "url": f"/api/gallery/file/{img.filename}",
        "thumb": f"/api/gallery/thumb/{img.id}",
        "created_at": img.created_at.isoformat(),
    }


@router.get("/gallery")
def list_images(
    offset: int = Query(0),
    limit: int = Query(48),
    db: DbSession = Depends(get_db),
):
    limit = max(1, min(limit or 48, _PAGE_MAX))
    offset = max(0, offset)
    q = db.query(GalleryImage).order_by(GalleryImage.created_at.desc(), GalleryImage.id.desc())
    rows = q.offset(offset).limit(limit).all()
    return {
        "items": [_fmt(r) for r in rows],
        "next": offset + limit if len(rows) == limit else None,
    }


@router.post("/gallery/upload")
async def upload_image(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    tags: str = Form(""),
    db: DbSession = Depends(get_db),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, "unsupported file type")

    fname = f"{_uid()}{ext}"
    dest = gallery_dir() / fname
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    _ensure_thumb(fname)
    img = GalleryImage(filename=fname, prompt=prompt, tags=tags, source="upload")
    db.add(img)
    db.commit()
    db.refresh(img)
    return _fmt(img)


@router.post("/gallery/rescan")
def rescan_gallery(db: DbSession = Depends(get_db)):
    root = gallery_dir()
    known = {r[0] for r in db.query(GalleryImage.filename).all()}
    added = skipped = failed = 0
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.name in known or p.suffix.lower() not in _ALLOWED:
            continue
        try:
            _ensure_thumb(p.name)
            db.add(GalleryImage(filename=p.name, prompt="", tags="", source="rescan"))
            known.add(p.name)
            added += 1
        except Exception:
            failed += 1
    db.commit()
    # keep old loose thumbnails from being counted as missing gallery files
    for p in root.iterdir():
        if p.is_file() and p.name in known:
            skipped += 1
    return {"added": added, "skipped": skipped - added, "failed": failed}


@router.get("/gallery/file/{filename}")
def serve_file(filename: str):
    if filename != Path(filename).name:  # no separators / traversal
        raise HTTPException(404)
    root = gallery_dir().resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)
    return _serve_safely(path)


@router.get("/gallery/thumb/{iid}")
def serve_thumb(iid: str, db: DbSession = Depends(get_db)):
    img = db.get(GalleryImage, iid)
    if not img:
        raise HTTPException(404)
    thumb = _ensure_thumb(img.filename)
    if thumb and thumb.is_file():
        return FileResponse(str(thumb), media_type="image/jpeg")
    # svg and broken files get a tiny neutral tile, not the original
    return FileResponse(str(_placeholder()), media_type="image/svg+xml")


def _thumb_name(filename: str) -> str:
    return Path(filename).stem + ".jpg"


def _ensure_thumb(filename: str):
    if filename != Path(filename).name:
        raise HTTPException(404)
    path = (gallery_dir() / filename).resolve()
    root = gallery_dir().resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    if path.suffix.lower() not in _RASTER:
        return None
    out = thumbs_dir() / _thumb_name(filename)
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    from PIL import Image, ImageOps

    try:
        im = ImageOps.exif_transpose(Image.open(path))
        im.load()
        im.thumbnail((_THUMB, _THUMB))
        bg = Image.new("RGB", im.size, (12, 12, 14))
        if im.mode in ("RGBA", "LA"):
            bg.paste(im, mask=im.getchannel("A"))
        else:
            bg.paste(im.convert("RGB"))
        bg.save(out, "JPEG", quality=82)
        return out
    except Exception:
        return None


def _placeholder() -> Path:
    p = thumbs_dir() / "_placeholder.svg"
    if not p.exists():
        p.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420">'
            '<rect width="100%" height="100%" fill="#0d0d10"/>'
            '<path d="M110 265l62-76 54 55 33-38 58 59" fill="none" stroke="#5b4b80" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>'
            '<circle cx="155" cy="145" r="24" fill="#7c5cff"/></svg>',
            encoding="utf-8",
        )
    return p


def _serve_safely(path: Path) -> FileResponse:
    """serve a user-uploaded file. svg/html can carry <script> that runs same-origin if rendered as
    a document, so force those to download (an <img src> still renders them); nosniff everywhere."""
    headers = {"X-Content-Type-Options": "nosniff"}
    risky = path.suffix.lower() in (".svg", ".svgz", ".html", ".htm", ".xml", ".xhtml")
    disp = "attachment" if risky else "inline"
    return FileResponse(
        str(path), headers=headers, filename=path.name, content_disposition_type=disp
    )


@router.delete("/gallery/{iid}")
def delete_image(iid: str, db: DbSession = Depends(get_db)):
    img = db.get(GalleryImage, iid)
    if not img:
        raise HTTPException(404)
    try:
        (gallery_dir() / img.filename).unlink()
    except FileNotFoundError:
        pass
    try:
        (thumbs_dir() / _thumb_name(img.filename)).unlink()
    except FileNotFoundError:
        pass
    db.delete(img)
    db.commit()
    return {"ok": True}
