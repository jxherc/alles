import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession

from core.database import GalleryImage, get_db

router = APIRouter(prefix="/api")

GALLERY_DIR = Path(__file__).parent.parent / "data" / "gallery"
GALLERY_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}


def _fmt(img: GalleryImage) -> dict:
    return {
        "id": img.id,
        "filename": img.filename,
        "prompt": img.prompt,
        "tags": img.tags,
        "source": img.source,
        "url": f"/api/gallery/file/{img.filename}",
        "created_at": img.created_at.isoformat(),
    }


@router.get("/gallery")
def list_images(db: DbSession = Depends(get_db)):
    rows = db.query(GalleryImage).order_by(GalleryImage.created_at.desc()).all()
    return [_fmt(r) for r in rows]


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
    from core.database import _uid

    fname = f"{_uid()}{ext}"
    dest = GALLERY_DIR / fname
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    img = GalleryImage(filename=fname, prompt=prompt, tags=tags, source="upload")
    db.add(img)
    db.commit()
    db.refresh(img)
    return _fmt(img)


@router.get("/gallery/file/{filename}")
def serve_file(filename: str):
    if filename != Path(filename).name:  # no separators / traversal
        raise HTTPException(404)
    path = (GALLERY_DIR / filename).resolve()
    if not path.is_relative_to(GALLERY_DIR.resolve()) or not path.is_file():
        raise HTTPException(404)
    return _serve_safely(path)


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
        (GALLERY_DIR / img.filename).unlink()
    except FileNotFoundError:
        pass
    db.delete(img)
    db.commit()
    return {"ok": True}
