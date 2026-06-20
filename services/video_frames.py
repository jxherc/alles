"""10e — pull a handful of frames out of a video so a vision model can understand it.

We don't do any ML here: ffmpeg grabs evenly-spaced JPEG stills, we hand them to the model as
image_url parts (the same path images already take). Degrades to no frames (never raises) if ffmpeg
is missing or the file is unreadable. Video *generation* is out of scope.
"""

import base64
import os
import shutil
import subprocess

MAX_FRAMES = 12
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}


def is_video(mime: str, name: str = "") -> bool:
    if (mime or "").startswith("video/"):
        return True
    ext = os.path.splitext(name or "")[1].lower()
    return ext in _VIDEO_EXTS


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _sample_times(duration: float, n: int) -> list[float]:
    """evenly spaced grab points across the clip, capped at MAX_FRAMES."""
    n = max(1, min(int(n or 1), MAX_FRAMES))
    if not duration or duration <= 0:
        return [0.0]
    # interior points so we skip the black first/last frame
    step = duration / (n + 1)
    return [round(step * (i + 1), 3) for i in range(n)]


def _probe_duration(path: str) -> float:
    """seconds, via ffprobe; 0.0 if it can't be determined."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _grab_frame(path: str, t: float) -> bytes | None:
    """one JPEG still at timestamp t, as bytes (None on failure)."""
    try:
        out = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(t),
                "-i",
                path,
                "-frames:v",
                "1",
                "-q:v",
                "4",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
        return out.stdout or None
    except Exception:
        return None


def extract_frames(path: str, n: int = 8) -> list[str]:
    """evenly-spaced JPEG frames as data: URLs. [] if ffmpeg missing or file unreadable."""
    if not os.path.isfile(path) or not _have_ffmpeg():
        return []
    times = _sample_times(_probe_duration(path), n)
    urls = []
    for t in times:
        data = _grab_frame(path, t)
        if data:
            urls.append("data:image/jpeg;base64," + base64.b64encode(data).decode())
    return urls[:MAX_FRAMES]
