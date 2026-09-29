"""One directory for browser uploads used by routes and background work."""

from pathlib import Path

from core.settings import data_dir

UPLOAD_DIR: Path | None = None


def upload_dir() -> Path:
    directory = UPLOAD_DIR or data_dir() / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
