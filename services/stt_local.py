"""Offline speech-to-text via faster-whisper. Runs on the user's machine, no API.
Model downloads once on first use (~150MB for 'base'), then fully offline.
"""

import shutil
import tempfile
from pathlib import Path

_model = None
_loaded_size = None


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _get_model(size: str):
    global _model, _loaded_size
    if _model is not None and _loaded_size == size:
        return _model
    from faster_whisper import WhisperModel

    # try GPU, fall back to CPU/int8 (works anywhere)
    try:
        if shutil.which("nvidia-smi"):
            _model = WhisperModel(size, device="cuda", compute_type="float16")
        else:
            raise RuntimeError("no gpu")
    except Exception:
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    _loaded_size = size
    return _model


def transcribe(audio_bytes: bytes, size: str = "base", language: str = "") -> str:
    model = _get_model(size)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        kw = {"language": language} if language else {}
        segments, _info = model.transcribe(tmp, **kw)
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
