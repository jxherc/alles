"""Photo row creation and response shape shared by Photos and image generation."""

import json
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from core.database import Photo
from services import photos_store


def format_photo(photo: Photo) -> dict:
    return {
        "id": photo.id,
        "thumb": f"/api/photos/thumb/{photo.id}",
        "original": f"/api/photos/original/{photo.id}",
        "width": photo.width,
        "height": photo.height,
        "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
        "favorite": photo.favorite,
        "album_id": photo.album_id,
        "original_name": photo.original_name,
        "caption": photo.caption or "",
        "keywords": [keyword for keyword in (photo.keywords or "").split(",") if keyword],
        "hidden": bool(photo.hidden),
        "archived": bool(photo.archived),
        "is_video": bool(photo.is_video),
        "aspect_ratio": photo.aspect_ratio
        or ((photo.width / photo.height) if (photo.width and photo.height) else None),
        "preview": ("data:image/jpeg;base64," + photo.preview) if photo.preview else "",
        "stack_id": photo.stack_id,
        "exif": json.loads(photo.exif or "{}"),
    }


@contextmanager
def generated_photo_batch(db: Session, images: list[bytes], prompt: str) -> Iterator[list[Photo]]:
    """Commit imported Photos with the caller's other rows, or remove new media."""
    created_files: list[tuple[str, str]] = []
    photos: list[Photo] = []
    try:
        for index, raw in enumerate(images):
            try:
                info = photos_store.import_image(raw, f"generated-{index + 1}.png")
            except ValueError:
                continue
            created_files.append((info["filename"], info["thumb"]))
            photos.append(
                Photo(
                    filename=info["filename"],
                    thumb=info["thumb"],
                    original_name=(prompt[:60] or "generated") + ".png",
                    caption=prompt,
                    source="generated",
                    width=info["width"],
                    height=info["height"],
                    taken_at=info["taken_at"],
                    exif=info["exif"],
                    aspect_ratio=info.get("aspect_ratio"),
                    preview=info.get("preview", ""),
                    checksum=info.get("checksum"),
                )
            )
        if photos:
            db.add_all(photos)
            db.flush()
        yield photos
        if photos:
            db.commit()
    except Exception:
        try:
            db.rollback()
        finally:
            for filename, thumb in created_files:
                photos_store.delete_files(filename, thumb)
        raise
