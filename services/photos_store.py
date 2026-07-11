"""
Photos app — a local photo library (no iCloud). Thumbnails + EXIF via Pillow.
Originals live in data/photos, thumbs in data/photos/.thumbs. Path-safe like files_store.
"""

import base64
import hashlib
import io
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from core.settings import data_dir, load_settings

ROOT = Path(__file__).resolve().parent.parent
_HEIF = {"heic", "heif"}
_RAW = {"dng", "cr2", "cr3", "nef", "arw", "raf", "rw2", "orf", "pef"}
_ALLOWED = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff"} | _HEIF
_VIDEO = {"mp4", "mov", "m4v", "webm"}  # 7c — no ffmpeg here, so stored + played, not thumbnailed
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
    base = photos_dir().resolve()
    candidate = (base / (name or "").lstrip("/\\")).resolve()
    if base != candidate and base not in candidate.parents:
        raise ValueError("path escapes photos root")
    return candidate


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


def _ext_of(original_name: str) -> str:
    ext = (original_name.rsplit(".", 1)[-1] if "." in original_name else "").lower()
    return "jpg" if ext == "jpeg" else ext


def _looks_heif(data: bytes) -> bool:
    brands = (b"heic", b"heix", b"hevc", b"hevx", b"heif", b"mif1", b"msf1")
    return len(data or b"") >= 12 and data[4:8] == b"ftyp" and any(b in data[8:40] for b in brands)


def _register_heif():
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:
        pass


def _write_managed_bytes(filename: str, data: bytes) -> None:
    target = photos_dir() / filename
    try:
        target.write_bytes(data)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _store_original_only(data: bytes, original_name: str, ext: str, err: Exception) -> dict:
    fname = uuid.uuid4().hex + "." + ext
    _write_managed_bytes(fname, data)
    return {
        "filename": fname,
        "thumb": "",
        "original_name": original_name,
        "width": 0,
        "height": 0,
        "taken_at": datetime.utcnow(),
        "exif": json.dumps({"format": ext, "decode_error": type(err).__name__}),
        "is_video": False,
        "aspect_ratio": None,
        "preview": "",
        "checksum": hashlib.sha256(data).hexdigest(),
    }


def import_media(data: bytes, original_name: str) -> dict:
    """dispatch by extension: video → stored as-is (no decode), else image."""
    if _ext_of(original_name) in _VIDEO:
        return import_video(data, original_name)
    return import_image(data, original_name)


def import_media_path(path: Path, original_name: str | None = None) -> dict:
    """Import a local media file without buffering large videos in memory.

    PhotoKit can materialize iCloud-backed video resources that are much larger
    than normal browser uploads. Images still use Pillow's byte-based decoder;
    videos are streamed into the managed library while hashing.
    """
    p = Path(path)
    name = original_name or p.name
    if _ext_of(name) in _VIDEO:
        return import_video_path(p, name)
    if _ext_of(name) in _RAW:
        return import_raw_path(p, name)
    return import_image(p.read_bytes(), name)


def _preview_b64(img) -> str:
    """tiny ~24px base64 jpeg — the browser upscales it into a blur-up placeholder. no deps."""
    try:
        t = img.convert("RGB")
        t.thumbnail((24, 24))
        buf = io.BytesIO()
        t.save(buf, "JPEG", quality=40)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def import_video(data: bytes, original_name: str) -> dict:
    ext = _ext_of(original_name)
    if ext not in _VIDEO:
        raise ValueError(f"unsupported video type: .{ext}")
    fname = uuid.uuid4().hex + "." + ext
    _write_managed_bytes(fname, data)
    return {
        "filename": fname,
        "thumb": "",  # no ffmpeg → no poster frame; the UI shows a ▶ badge instead
        "original_name": original_name,
        "width": 0,
        "height": 0,
        "taken_at": datetime.utcnow(),
        "exif": json.dumps({}),
        "is_video": True,
        "aspect_ratio": None,
        "preview": "",
        "checksum": hashlib.sha256(data).hexdigest(),
    }


def import_video_path(path: Path, original_name: str) -> dict:
    ext = _ext_of(original_name)
    if ext not in _VIDEO:
        raise ValueError(f"unsupported video type: .{ext}")
    fname = uuid.uuid4().hex + "." + ext
    target = photos_dir() / fname
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as src, target.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                digest.update(chunk)
                dst.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {
        "filename": fname,
        "thumb": "",
        "original_name": original_name,
        "width": 0,
        "height": 0,
        "taken_at": datetime.utcnow(),
        "exif": json.dumps({}),
        "is_video": True,
        "aspect_ratio": None,
        "preview": "",
        "checksum": digest.hexdigest(),
    }


def import_raw_path(path: Path, original_name: str) -> dict:
    """Keep a PhotoKit RAW original even when Pillow cannot render the format."""
    ext = _ext_of(original_name)
    if ext not in _RAW:
        raise ValueError(f"unsupported raw image type: .{ext}")
    fname = uuid.uuid4().hex + "." + ext
    target = photos_dir() / fname
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as src, target.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                digest.update(chunk)
                dst.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {
        "filename": fname,
        "thumb": "",
        "original_name": original_name,
        "width": 0,
        "height": 0,
        "taken_at": datetime.utcnow(),
        "exif": json.dumps({"format": ext, "preview": "unavailable"}),
        "is_video": False,
        "aspect_ratio": None,
        "preview": "",
        "checksum": digest.hexdigest(),
    }


def import_image(data: bytes, original_name: str) -> dict:
    from PIL import Image, ImageOps

    ext = _ext_of(original_name) or "jpg"
    if ext not in _ALLOWED:
        raise ValueError(f"unsupported image type: .{ext}")
    if ext in _HEIF:
        _register_heif()

    # decode BEFORE writing to disk: a corrupt/truncated/fake image or a decompression bomb raises
    # UnidentifiedImageError / OSError / DecompressionBombError - turn those into a clean 400 and
    # don't leave an orphan file behind (the old code wrote the bytes first, then 500'd on decode).
    try:
        img = Image.open(io.BytesIO(data))
        taken_at, exif_out = _read_exif(img)  # read EXIF before transpose
        img = ImageOps.exif_transpose(img)  # honor orientation for size/thumb
        w, h = img.size
        img.load()  # force a full decode so a bomb/corruption fails here, not later
    except Exception as e:
        if ext in _HEIF and _looks_heif(data):
            return _store_original_only(data, original_name, ext, e)
        raise ValueError(f"not a valid image: {type(e).__name__}")

    fname = uuid.uuid4().hex + "." + ext
    _write_managed_bytes(fname, data)
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
        "is_video": False,
        "aspect_ratio": (w / h) if (w and h) else None,
        "preview": _preview_b64(img),
        "checksum": hashlib.sha256(data).hexdigest(),
    }


def register_existing(path: Path) -> dict:
    from PIL import Image, ImageOps

    base = photos_dir().resolve()
    p = path.resolve()
    if p == base or base not in p.parents or ".thumbs" in p.parts:
        raise ValueError("path escapes photos root")
    ext = p.suffix.lower().lstrip(".")
    if ext not in (_ALLOWED | _VIDEO):
        raise ValueError(f"unsupported media type: .{ext}")
    data = p.read_bytes()
    rel = p.relative_to(base).as_posix()
    if ext in _VIDEO:
        return {
            "filename": rel,
            "thumb": "",
            "original_name": p.name,
            "width": 0,
            "height": 0,
            "taken_at": datetime.utcfromtimestamp(p.stat().st_mtime),
            "exif": json.dumps({}),
            "is_video": True,
            "aspect_ratio": None,
            "preview": "",
            "checksum": hashlib.sha256(data).hexdigest(),
        }
    if ext in _HEIF:
        _register_heif()
    try:
        img = Image.open(io.BytesIO(data))
        taken_at, exif_out = _read_exif(img)
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        img.load()
    except Exception as e:
        if ext in _HEIF and _looks_heif(data):
            return {
                "filename": rel,
                "thumb": "",
                "original_name": p.name,
                "width": 0,
                "height": 0,
                "taken_at": datetime.utcfromtimestamp(p.stat().st_mtime),
                "exif": json.dumps({"format": ext, "decode_error": type(e).__name__}),
                "is_video": False,
                "aspect_ratio": None,
                "preview": "",
                "checksum": hashlib.sha256(data).hexdigest(),
            }
        raise ValueError(f"not a valid image: {type(e).__name__}")

    thumb_name = Path(rel).with_suffix(".jpg").name
    try:
        t = img.convert("RGB")
        t.thumbnail((_THUMB, _THUMB))
        t.save(thumbs_dir() / thumb_name, "JPEG", quality=82)
    except Exception:
        thumb_name = ""

    return {
        "filename": rel,
        "thumb": thumb_name,
        "original_name": p.name,
        "width": w,
        "height": h,
        "taken_at": taken_at or datetime.utcfromtimestamp(p.stat().st_mtime),
        "exif": json.dumps(exif_out),
        "is_video": False,
        "aspect_ratio": (w / h) if (w and h) else None,
        "preview": _preview_b64(img),
        "checksum": hashlib.sha256(data).hexdigest(),
    }


def backfill_perf(db) -> int:
    """fill aspect_ratio / preview / checksum on rows imported before phase 4. gated on
    checksum being null, so it processes each photo once and is a cheap no-op after that."""
    from PIL import Image, ImageOps

    from core.database import Photo

    rows = db.query(Photo).filter(Photo.checksum == None).all()  # noqa: E711
    n = 0
    for p in rows:
        if not p.filename:
            continue
        op = _safe(p.filename)
        if not op.is_file():
            continue
        try:
            data = op.read_bytes()
            p.checksum = hashlib.sha256(data).hexdigest()
            if not p.is_video:
                im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
                w, h = im.size
                if w and h:
                    p.aspect_ratio = w / h
                p.preview = _preview_b64(im)
            n += 1
        except Exception:
            continue
    if n:
        db.commit()
    return n


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
