"""
Photos app — a local photo library (no iCloud). Thumbnails + EXIF via Pillow.
Originals live in data/photos, thumbs in data/photos/.thumbs. Path-safe like files_store.
"""

import io
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from core.settings import data_dir, load_settings

ROOT = Path(__file__).resolve().parent.parent
_ALLOWED = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
_THUMB = 512


def photos_dir() -> Path:
    d = load_settings().get("photos_dir") or str(data_dir() / "photos")
    p = Path(d).expanduser()
    if not p.is_absolute():
        p = ROOT / p  # relative dirs anchor to the app root, not cwd
    p = p.resolve()  # must be absolute — _safe() compares against resolved children
    (p / ".thumbs").mkdir(parents=True, exist_ok=True)
    return p


def thumbs_dir() -> Path:
    return photos_dir() / ".thumbs"


def _resolve_dir(raw) -> Path:
    p = Path(raw or str(data_dir() / "photos")).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def relocate(old_raw):
    """photos_dir just changed — move the existing library (originals + .thumbs) into the
    new folder. DB rows only keep bare 'uid.ext' names resolved against photos_dir(), so
    without this every prior photo 404s after a folder switch."""
    old = _resolve_dir(old_raw)
    new = photos_dir()  # resolves + creates the new dir (incl. an empty .thumbs)
    if old == new or not old.exists():
        return
    _merge_move(old, new)


def _merge_move(src: Path, dst: Path):
    # move files in, recursing into subdirs (.thumbs already exists in dst from photos_dir(),
    # so a plain shutil.move of the whole folder would be skipped — merge file-by-file instead)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _merge_move(item, target)
        elif not target.exists():  # never clobber a file already in the target
            try:
                shutil.move(str(item), str(target))
            except Exception:
                pass


def _safe(name: str) -> Path:
    base = photos_dir()
    p = (base / (name or "").lstrip("/\\")).resolve()
    if base != p and base not in p.parents:
        raise ValueError("path escapes photos root")
    return p


# tags surfaced in the photo info panel (Apple Photos' ⌘I)
_EXIF_KEEP = (
    "Make",
    "Model",
    "LensModel",
    "FNumber",
    "ExposureTime",
    "ISOSpeedRatings",
    "FocalLength",
    "Orientation",
    "Software",
    "Flash",
    "ExposureBiasValue",
    "WhiteBalance",
)


def _gps_to_decimal(gps):
    """EXIF GPS IFD → (lat, lon) decimal degrees, or None. keys: 1=latRef 2=lat
    3=lonRef 4=lon, lat/lon as (deg, min, sec)."""
    if not gps:
        return None
    try:

        def _conv(val, ref):
            d, m, s = (float(x) for x in val)
            dec = d + m / 60 + s / 3600
            return -dec if str(ref).upper() in ("S", "W") else dec

        lat = round(_conv(gps[2], gps.get(1, "N")), 6)
        lon = round(_conv(gps[4], gps.get(3, "E")), 6)
        return (lat, lon)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _exif_fields(tags: dict):
    """name-keyed EXIF dict → (taken_at, kept-fields). pure, no PIL."""
    out = {}
    taken_at = None
    dt = tags.get("DateTimeOriginal") or tags.get("DateTime")
    if dt:
        try:
            taken_at = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    for key in _EXIF_KEEP:
        if key in tags and tags[key] not in (None, ""):
            out[key] = str(tags[key])
    return taken_at, out


def _read_exif(img) -> tuple:
    from PIL import ExifTags

    taken_at, out = None, {}
    try:
        raw = img.getexif()
        if raw:
            tags = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
            taken_at, out = _exif_fields(tags)
            try:
                gps = raw.get_ifd(0x8825)  # GPSInfo IFD
            except Exception:
                gps = None
            dec = _gps_to_decimal(gps)
            if dec:
                out["lat"], out["lon"] = dec[0], dec[1]
    except Exception:
        pass
    return taken_at, out


def import_image(data: bytes, original_name: str) -> dict:
    from PIL import Image, ImageOps

    ext = (original_name.rsplit(".", 1)[-1] if "." in original_name else "jpg").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in _ALLOWED:
        raise ValueError(f"unsupported image type: .{ext}")

    fname = uuid.uuid4().hex + "." + ext
    (photos_dir() / fname).write_bytes(data)

    img = Image.open(io.BytesIO(data))
    taken_at, exif_out = _read_exif(img)  # read EXIF before transpose
    img = ImageOps.exif_transpose(img)  # honor orientation for size/thumb
    w, h = img.size
    if taken_at is None:
        taken_at = datetime.utcnow()

    thumb_name = fname.rsplit(".", 1)[0] + ".jpg"
    try:
        t = img.convert("RGB")
        t.thumbnail((_THUMB, _THUMB))
        t.save(thumbs_dir() / thumb_name, "JPEG", quality=82)
    except Exception:
        thumb_name = ""  # original still usable even if the thumb failed

    return {
        "filename": fname,
        "thumb": thumb_name,
        "original_name": original_name,
        "width": w,
        "height": h,
        "taken_at": taken_at,
        "exif": json.dumps(exif_out),
    }


def original_path(filename: str) -> Path:
    return _safe(filename)


def thumb_path(thumb: str):
    return (thumbs_dir() / thumb) if thumb else None


def delete_files(filename: str, thumb: str):
    for p in (_safe(filename) if filename else None, (thumbs_dir() / thumb) if thumb else None):
        try:
            if p and p.exists():
                p.unlink()
        except Exception:
            pass
