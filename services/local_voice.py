"""Bounded, offline speech jobs in one killable, lazily started worker process.

Status reads never start Python, import a speech engine, or download models. The
separate installer owns the verified runtime manifest and all model downloads.
"""

import asyncio
import base64
import binascii
import json
import math
import os
import re
import shutil
import signal
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER_SCRIPT = ROOT / "scripts" / "local_voice_worker.py"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_INPUT_SECONDS = 60
MAX_TEXT_CHARS = 500
SAMPLE_RATE = 24_000
MAX_OUTPUT_BYTES = SAMPLE_RATE * 2 * 30
MAX_PCM_CHUNK = 96_000
MAX_LINE_BYTES = 128 * 1024
MAX_STDERR_BYTES = 64 * 1024
START_TIMEOUT = 30.0
JOB_TIMEOUT = 120.0
STOP_TIMEOUT = 2.0
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,8})?$")
_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
}
_MODEL_PATHS = {
    "whisper": "models/whisper",
    "kokoro": "models/kokoro",
    "vad": "models/vad/silero_vad.onnx",
}
_MODEL_FILES = {
    "models/whisper/config.json",
    "models/whisper/weights.safetensors",
    "models/kokoro/config.json",
    "models/kokoro/kokoro-v1_1-zh.pth",
    "models/kokoro/voices/af_maple.pt",
    "models/kokoro/voices/zf_001.pt",
    "models/vad/silero_vad.onnx",
}


class LocalVoiceError(RuntimeError):
    """A safe public error; never expose worker stderr, paths or model input."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _runtime() -> Path:
    return Path(os.environ.get("ALLES_VOICE_RUNTIME") or ROOT / ".voice-runtime").resolve()


def _contained(root: Path, value) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("invalid runtime path")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("invalid runtime path")
    return path


def _manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("invalid manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("status") != "ready"
        or manifest.get("python") != ".venv/bin/python"
        or not isinstance(manifest.get("verified_at"), str)
        or not manifest["verified_at"]
        or not isinstance(manifest.get("engine_versions"), dict)
        or not manifest["engine_versions"]
    ):
        raise ValueError("runtime is not verified")
    # A venv's Python normally symlinks to its base interpreter. The manifest
    # cannot choose an arbitrary executable, but this standard symlink is valid.
    executable = root / ".venv" / "bin" / "python"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("runtime Python is unavailable")
    models = manifest.get("models")
    if not isinstance(models, dict):
        raise ValueError("models are unavailable")
    paths = {}
    for name in ("whisper", "kokoro", "vad"):
        entry = models.get(name)
        if not isinstance(entry, dict) or entry.get("path") != _MODEL_PATHS[name]:
            raise ValueError("models are unavailable")
        paths[name] = _contained(root, entry.get("path"))
        if not (paths[name].is_file() if name == "vad" else paths[name].is_dir()):
            raise ValueError("models are unavailable")
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 10_000:
        raise ValueError("model inventory is unavailable")
    inventory = set()
    for item in files:
        if (
            not isinstance(item, dict)
            or type(item.get("size")) is not int
            or item["size"] <= 0
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("invalid model inventory")
        file = _contained(root, item.get("path"))
        if file in inventory or not file.is_file() or file.stat().st_size != item["size"]:
            raise ValueError("model inventory changed")
        inventory.add(file)
    if not {root / path for path in _MODEL_FILES}.issubset(inventory):
        raise ValueError("model inventory is incomplete")
    return manifest


def metadata_status() -> dict:
    """Cheap filesystem readiness only; hashes were checked by the installer."""
    result = {
        "available": False,
        "ready": False,
        "provider": "local",
        "transport": "local-push-to-talk",
        "format": "pcm_s16le",
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "max_audio_bytes": MAX_AUDIO_BYTES,
        "max_input_seconds": MAX_INPUT_SECONDS,
        "max_text_chars": MAX_TEXT_CHARS,
        "reason": "install and verify the local voice runtime first",
    }
    try:
        _manifest(_runtime())
        if not WORKER_SCRIPT.is_file():
            return result
    except (OSError, ValueError, TypeError, RecursionError):
        return result
    return {**result, "available": True, "ready": True, "reason": ""}


def _environment(root: Path) -> dict[str, str]:
    # Do not inherit provider credentials, proxy configuration, PYTHONPATH or
    # Python startup hooks. Models and caches cannot fall back to online fetches.
    return {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "en_US.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HOME": str(root / "cache"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "ALLES_VOICE_RUNTIME": str(root),
        "TOKENIZERS_PARALLELISM": "false",
    }


def _metrics(value, required=()) -> dict:
    if not isinstance(value, dict) or len(value) > 16:
        raise LocalVoiceError("voice_protocol", "local voice returned invalid metrics")
    for key in required:
        if key not in value:
            raise LocalVoiceError("voice_protocol", "local voice omitted job metrics")
    for key, number in value.items():
        if (
            not isinstance(key, str)
            or len(key) > 64
            or type(number) not in (int, float)
            or number < 0
            or number > 1_000_000_000
            or not math.isfinite(number)
        ):
            raise LocalVoiceError("voice_protocol", "local voice returned invalid metrics")
    return value


class _Worker:
    def __init__(self):
        self.process = None
        self.root = None
        self.owner = None
        self.stderr_task = None
        self.stderr_bytes = 0
        self.stderr_overflow = False
        self.stopping = False

    def claim(self, job_id: str, cancel: asyncio.Event) -> Path:
        if not isinstance(job_id, str) or not _ID.fullmatch(job_id):
            raise LocalVoiceError("voice_input_invalid", "invalid voice job identity")
        if cancel.is_set():
            raise LocalVoiceError("voice_cancelled", "voice job cancelled")
        if self.owner is not None or self.stopping:
            raise LocalVoiceError("voice_busy", "local voice is busy; try again after this turn")
        root = _runtime()
        if not metadata_status()["available"]:
            raise LocalVoiceError("voice_unavailable", "local voice runtime is not ready")
        # No await between the capacity check and reservation: zero queued jobs.
        self.owner = job_id
        self.stderr_bytes = 0
        return root

    async def wait(self, operation, cancel: asyncio.Event, deadline: float):
        task = asyncio.ensure_future(operation)
        stopped = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {task, stopped},
                timeout=max(0, deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel.is_set():
                raise LocalVoiceError("voice_cancelled", "voice job cancelled")
            if task not in done:
                raise LocalVoiceError("voice_timeout", "local voice job timed out")
            return task.result()
        finally:
            for pending in (task, stopped):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)

    async def drain_stderr(self, process):
        while chunk := await process.stderr.read(4096):
            self.stderr_bytes += len(chunk)
            if self.stderr_bytes > MAX_STDERR_BYTES:
                self.stderr_overflow = True
                if process.returncode is None:
                    self.kill(process)
                return

    @staticmethod
    def kill(process):
        try:
            if getattr(process, "pid", None) and os.name == "posix":
                # We created this worker in its own session. Also stop its
                # owned ffmpeg decoder instead of leaving an orphaned child.
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    async def terminate(self):
        process, self.process = self.process, None
        stderr_task, self.stderr_task = self.stderr_task, None
        self.root = None
        if process is not None:
            if process.returncode is None:
                self.kill(process)
            try:
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
            except (TimeoutError, ProcessLookupError):
                pass
        if stderr_task is not None:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)

    async def packet(self, cancel, deadline, expected_id=None):
        try:
            line = await self.wait(self.process.stdout.readline(), cancel, deadline)
            if not line or len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                raise ValueError("invalid worker output")
            packet = json.loads(line)
            if not isinstance(packet, dict):
                raise ValueError("invalid packet")
            if expected_id is not None and packet.get("id") != expected_id:
                raise ValueError("wrong job identity")
        except (ValueError, UnicodeError, asyncio.LimitOverrunError) as exc:
            raise LocalVoiceError("voice_protocol", "local voice returned invalid output") from exc
        if self.stderr_overflow:
            raise LocalVoiceError("voice_protocol", "local voice exceeded its diagnostic limit")
        if packet.get("type") == "error":
            # Never surface raw engine errors: they can contain text and paths.
            code = packet.get("code")
            if code in {"audio_too_long", "no_speech", "invalid_audio", "text_too_long"}:
                raise LocalVoiceError("voice_input_invalid", "voice input could not be processed")
            raise LocalVoiceError("voice_worker_failed", "local voice could not finish this job")
        return packet

    async def start(self, root, cancel, deadline):
        if self.process is not None and (self.root != root or self.process.returncode is not None):
            await self.terminate()
        if self.process is not None:
            return
        self.stderr_overflow = False
        startup_deadline = min(deadline, time.monotonic() + START_TIMEOUT)

        async def spawn():
            # Assign ownership before returning: a simultaneous cancel must not
            # discard a successfully created process and lose its kill handle.
            self.process = await asyncio.create_subprocess_exec(
                str(root / ".venv" / "bin" / "python"),
                "-I",
                str(WORKER_SCRIPT),
                "--runtime",
                str(root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_LINE_BYTES,
                cwd=str(root),
                env=_environment(root),
                start_new_session=True,
            )
            self.root = root
            self.stderr_task = asyncio.create_task(self.drain_stderr(self.process))

        await self.wait(spawn(), cancel, startup_deadline)
        packet = await self.packet(cancel, startup_deadline)
        if any(
            packet.get(key) != value
            for key, value in {
                "type": "ready",
                "protocol": 1,
                "format": "pcm_s16le",
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
            }.items()
        ):
            raise LocalVoiceError("voice_protocol", "local voice protocol is incompatible")

    async def exchange(self, root, request, cancel):
        deadline = time.monotonic() + JOB_TIMEOUT
        # A fresh wire identity prevents a delayed packet from a reused caller
        # identity being accepted as output for its next operation.
        identity = uuid.uuid4().hex
        try:
            await self.start(root, cancel, deadline)
            self.process.stdin.write((json.dumps({**request, "id": identity}) + "\n").encode())
            await self.wait(self.process.stdin.drain(), cancel, deadline)
            while True:
                packet = await self.packet(cancel, deadline, identity)
                yield packet
                if packet.get("type") == "done":
                    return
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            raise LocalVoiceError("voice_worker_failed", "local voice worker stopped") from exc


_worker = _Worker()


async def transcribe(audio: bytes, content_type: str, job_id: str, cancel: asyncio.Event) -> dict:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if not isinstance(audio, bytes) or not 0 < len(audio) <= MAX_AUDIO_BYTES or mime not in _TYPES:
        raise LocalVoiceError("voice_input_invalid", "record up to 60 seconds of supported audio")
    root = _worker.claim(job_id, cancel)
    directory = None
    complete = False
    try:
        jobs = _contained(root, "jobs")
        jobs.mkdir(mode=0o700, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="voice-", dir=jobs))
        audio_path = directory / ("input" + _TYPES[mime])
        audio_path.write_bytes(audio)
        result = None
        async for packet in _worker.exchange(
            root, {"op": "transcribe", "audio_path": str(audio_path), "language": "auto"}, cancel
        ):
            if packet.get("type") == "result" and result is None:
                text, language = packet.get("text"), packet.get("language")
                metrics = _metrics(
                    packet.get("metrics"), ("processing_ms", "input_seconds", "vad_speech_seconds")
                )
                if (
                    not isinstance(text, str)
                    or len(text) > 16_000
                    or not isinstance(language, str)
                    or (language != "auto" and not _LANGUAGE.fullmatch(language))
                    or metrics["input_seconds"] > MAX_INPUT_SECONDS
                    or metrics["vad_speech_seconds"] > metrics["input_seconds"]
                ):
                    raise LocalVoiceError("voice_protocol", "local voice returned invalid text")
                result = {"text": text.strip(), "language": language, "metrics": metrics}
            elif packet.get("type") == "done" and result is not None:
                complete = True
            else:
                raise LocalVoiceError("voice_protocol", "local voice returned an unexpected event")
        return result
    except OSError as exc:
        raise LocalVoiceError(
            "voice_worker_failed", "local voice audio could not be prepared"
        ) from exc
    finally:
        try:
            if not complete:
                await _worker.terminate()
        finally:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            _worker.owner = None


async def synthesize(text: str, job_id: str, cancel: asyncio.Event):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise LocalVoiceError("voice_input_invalid", "speak one clause of up to 500 characters")
    root = _worker.claim(job_id, cancel)
    complete, sequence, total = False, 0, 0
    try:
        async for packet in _worker.exchange(root, {"op": "synthesize", "text": text}, cancel):
            if packet.get("type") == "audio":
                if (
                    type(packet.get("seq")) is not int
                    or packet["seq"] != sequence
                    or packet.get("sample_rate") != SAMPLE_RATE
                    or packet.get("channels") != 1
                    or not isinstance(packet.get("pcm_b64"), str)
                ):
                    raise LocalVoiceError("voice_protocol", "local voice returned invalid audio")
                try:
                    pcm = base64.b64decode(packet["pcm_b64"], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise LocalVoiceError(
                        "voice_protocol", "local voice returned invalid PCM"
                    ) from exc
                total += len(pcm)
                if not pcm or len(pcm) % 2 or len(pcm) > MAX_PCM_CHUNK or total > MAX_OUTPUT_BYTES:
                    raise LocalVoiceError("voice_protocol", "local voice exceeded its audio limit")
                sequence += 1
                yield pcm
            elif packet.get("type") == "done" and total:
                metrics = _metrics(
                    packet.get("metrics"), ("first_pcm_ms", "generation_ms", "output_samples")
                )
                if (
                    type(metrics["output_samples"]) is not int
                    or metrics["output_samples"] != total // 2
                ):
                    raise LocalVoiceError("voice_protocol", "local voice returned incomplete audio")
                complete = True
            else:
                raise LocalVoiceError("voice_protocol", "local voice returned an unexpected event")
    finally:
        try:
            if not complete:
                await _worker.terminate()
        finally:
            _worker.owner = None


async def shutdown() -> None:
    """Terminate the owned worker; an in-flight caller observes EOF, not success."""
    _worker.stopping = True
    try:
        await _worker.terminate()
    finally:
        _worker.stopping = False
