"""
photo sync — import a folder of images into the photos library, skipping anything
already imported (tracked by path + mtime/size). this is the cross-platform core:
point it at an iCloud Drive folder, a Photos export, Dropbox, whatever syncs to
disk, and it pulls new shots in.

the macOS Photos *library* itself (PhotoKit) isn't a plain folder, so the native
bridge below is the integration seam for the Mac mini: export from the system
library to a temp dir (osxphotos / PhotoKit), then run the same folder sync.
"""
import sys
import json
from pathlib import Path

from services import photos_store
from core.database import SessionLocal, Photo

_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}
_STATE = Path(__file__).resolve().parent.parent / "data" / "photo_sync_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text("utf-8"))
    except Exception:
        return {}


def _save_state(s: dict):
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s), "utf-8")


def _sig(p: Path) -> str:
    st = p.stat()
    return f"{int(st.st_mtime)}:{st.st_size}"


def sync_folder(src: str, db=None, limit: int = 2000) -> dict:
    """import new images from a folder (recursive). returns counts; re-running
    only pulls files that are new or changed since last time."""
    root = Path(src).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"not a folder: {src}")
    state = _load_state()
    key_root = str(root.resolve())
    seen = state.get(key_root, {})
    own = db is None
    db = db or SessionLocal()
    imported = skipped = failed = 0
    try:
        for p in sorted(root.rglob("*")):
            if imported >= limit:
                break
            if not p.is_file() or p.suffix.lower() not in _IMG_EXT:
                continue
            k = str(p.resolve())
            sig = _sig(p)
            if seen.get(k) == sig:
                skipped += 1
                continue
            try:
                info = photos_store.import_image(p.read_bytes(), p.name)
                db.add(Photo(filename=info["filename"], thumb=info["thumb"],
                             original_name=info["original_name"], width=info["width"],
                             height=info["height"], taken_at=info["taken_at"], exif=info["exif"]))
                seen[k] = sig
                imported += 1
            except Exception:
                failed += 1
        db.commit()
        state[key_root] = seen
        _save_state(state)
    finally:
        if own:
            db.close()
    return {"imported": imported, "skipped": skipped, "failed": failed}


# ── macOS native bridge (Mac mini) ────────────────────────────────────────────
def pull_from_macos_photos(dest_dir: str) -> dict:
    """export from the system Photos library (PhotoKit) into dest_dir, then this
    folder can be handed to sync_folder. macOS only — wire osxphotos/PhotoKit on
    the Mac mini. raises on anything else so it fails loud, not silent."""
    if sys.platform != "darwin":
        raise NotImplementedError(
            "macOS-only: on the Mac mini, export via osxphotos "
            "(`osxphotos export <dest> --update`) or PhotoKit, then sync_folder(dest).")
    # on darwin: shell out to osxphotos if present (kept here as the seam)
    import shutil
    import subprocess
    if not shutil.which("osxphotos"):
        raise RuntimeError("osxphotos not installed — `pip install osxphotos` on the Mac")
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    subprocess.run(["osxphotos", "export", dest_dir, "--update"], check=True)
    return {"exported_to": dest_dir}
