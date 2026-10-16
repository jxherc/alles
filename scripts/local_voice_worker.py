#!/usr/bin/env python3
"""Offline speech worker. Provisioning is deliberately a separate, explicit step.

One bounded NDJSON request runs at a time. Stdout is protocol-only; third-party
diagnostics go to stderr. Nothing imports Alles or opens its database. The app
owns cancellation by terminating this process and fencing the request identity.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

RATE = 24000
INPUT_RATE = 16000
MAX_SECONDS = 60
MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 500
MAX_OUTPUT_SAMPLES = 30 * RATE
MAX_REQUEST_BYTES = 16384
ENGINE_PACKAGES = ("mlx-whisper", "kokoro", "misaki", "onnxruntime", "en-core-web-sm")


class VoiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise VoiceError("invalid_path", "Voice asset path is outside its runtime.")
    return candidate


def inspect_runtime(root: Path, *, allow_unverified: bool = False) -> dict:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise VoiceError("not_installed", "The local voice runtime is not installed.")
    manifest = json.loads(manifest_path.read_text())
    permitted = {"ready", "assets_verified"} if allow_unverified else {"ready"}
    if manifest.get("schema_version") != 1 or manifest.get("status") not in permitted:
        raise VoiceError("not_verified", "Local voice has not passed its offline checks.")
    required = {
        "models/whisper/config.json",
        "models/whisper/weights.safetensors",
        "models/kokoro/config.json",
        "models/kokoro/kokoro-v1_1-zh.pth",
        "models/kokoro/voices/af_maple.pt",
        "models/kokoro/voices/zf_001.pt",
        "models/vad/silero_vad.onnx",
    }
    inventory = manifest.get("files")
    if not isinstance(inventory, list) or not required.issubset(
        {entry.get("path") for entry in inventory if isinstance(entry, dict)}
    ):
        raise VoiceError("invalid_manifest", "The local voice manifest is incomplete.")
    for entry in inventory:
        asset = contained(root, entry["path"])
        if not asset.is_file() or asset.stat().st_size != entry["size"]:
            raise VoiceError("invalid_asset", "A local voice asset is missing or changed.")
        # Hash once on worker startup, never on a status request.
        digest = hashlib.sha256()
        with asset.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise VoiceError("invalid_asset", "A local voice asset failed verification.")
    for package in ENGINE_PACKAGES:
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise VoiceError("missing_dependency", "A pinned voice dependency is missing.") from exc
    if not shutil.which("ffmpeg"):
        raise VoiceError("missing_decoder", "Local voice requires the installed ffmpeg decoder.")
    return manifest


def offline_environment(root: Path) -> None:
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HOME=str(root / "cache" / "huggingface"),
        NUMBA_CACHE_DIR=str(root / "cache" / "numba"),
        TOKENIZERS_PARALLELISM="false",
        PYTORCH_ENABLE_MPS_FALLBACK="1",
    )

    def deny_network(*_args, **_kwargs):
        raise PermissionError("Networking is disabled in the local voice worker.")

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network


def decode_audio(root: Path, path: str):
    import numpy as np

    jobs = (root / "jobs").resolve()
    audio_path = Path(path).resolve()
    if not audio_path.is_relative_to(jobs) or not audio_path.is_file():
        raise VoiceError(
            "invalid_audio", "Audio must belong to this voice runtime's job directory."
        )
    if audio_path.stat().st_size > MAX_BYTES or audio_path.stat().st_size == 0:
        raise VoiceError("audio_too_large", "Record a nonempty utterance of at most 60 seconds.")
    command = [
        shutil.which("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(audio_path),
        "-t",
        str(MAX_SECONDS + 0.1),
        "-vn",
        "-sn",
        "-dn",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "1",
        "-ar",
        str(INPUT_RATE),
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VoiceError("decode_failed", "The recording could not be decoded locally.") from exc
    if result.returncode or not result.stdout or len(result.stdout) % 4:
        raise VoiceError("decode_failed", "The recording could not be decoded locally.")
    audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    if len(audio) > MAX_SECONDS * INPUT_RATE:
        raise VoiceError("audio_too_long", "Record no more than 60 seconds at a time.")
    if not np.isfinite(audio).all():
        raise VoiceError("invalid_audio", "The recording contains invalid samples.")
    return audio


class LocalSpeech:
    """Adapter boundary: no provider credentials, network clients or paid fallback."""

    def __init__(self, root: Path):
        self.root = root
        self.vad = None
        self.tts_model = None
        self.pipelines = {}
        self.voices = {}

    def speech_frames(self, audio):
        import numpy as np
        import onnxruntime as ort

        if self.vad is None:
            options = ort.SessionOptions()
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            self.vad = ort.InferenceSession(
                str(self.root / "models/vad/silero_vad.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, 64), dtype=np.float32)
        speech = []
        for offset in range(0, len(audio), 512):
            frame = audio[offset : offset + 512]
            frame = np.pad(frame, (0, 512 - len(frame))).reshape(1, 512)
            combined = np.concatenate((context, frame), axis=1)
            probability, state = self.vad.run(
                None,
                {"input": combined, "state": state, "sr": np.array(INPUT_RATE, dtype=np.int64)},
            )
            context = combined[:, -64:]
            if float(probability.reshape(-1)[0]) >= 0.5:
                speech.append(offset)
        return speech

    def transcribe(self, path: str, language: str) -> dict:
        started = time.perf_counter()
        audio = decode_audio(self.root, path)
        speech = self.speech_frames(audio)
        metrics = {
            "input_seconds": len(audio) / INPUT_RATE,
            "vad_speech_seconds": min(len(audio), len(speech) * 512) / INPUT_RATE,
        }
        # A short gate prevents silence/noise from being passed to Whisper. This
        # is not hands-free turn detection, echo cancellation or semantic VAD.
        if len(speech) < 3:
            metrics["processing_ms"] = (time.perf_counter() - started) * 1000
            return {"text": "", "language": language, "metrics": metrics}
        import mlx_whisper

        first = max(0, speech[0] - int(0.2 * INPUT_RATE))
        last = min(len(audio), speech[-1] + 512 + int(0.2 * INPUT_RATE))
        result = mlx_whisper.transcribe(
            audio[first:last],
            path_or_hf_repo=str(self.root / "models/whisper"),
            language=None if language == "auto" else language,
            task="transcribe",
            verbose=None,
            temperature=0.0,
            condition_on_previous_text=False,
        )
        metrics["processing_ms"] = (time.perf_counter() - started) * 1000
        return {
            "text": str(result.get("text", "")).strip(),
            "language": result.get("language", language),
            "metrics": metrics,
        }

    def load_tts(self):
        if self.tts_model is not None:
            return
        import logging

        import jieba
        import torch
        from loguru import logger

        # Dependency debug logs can contain phonemes/full text; never retain
        # utterance content in process diagnostics.
        logger.remove()
        jieba.setLogLevel(logging.ERROR)
        jieba_cache = self.root / "cache/jieba"
        jieba_cache.mkdir(parents=True, exist_ok=True)
        jieba.dt.tmp_dir = str(jieba_cache)
        from kokoro import KModel, KPipeline

        # CPU is predictable for this small Torch engine while MLX owns ASR's
        # Metal work. Device changes require separate latency/quality evidence.
        torch.set_num_threads(4)
        model_root = self.root / "models/kokoro"
        model = (
            KModel(
                repo_id="hexgrad/Kokoro-82M-v1.1-zh",
                config=str(model_root / "config.json"),
                model=str(model_root / "kokoro-v1_1-zh.pth"),
            )
            .to("cpu")
            .eval()
        )
        english = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M-v1.1-zh", model=model)
        phonemizer = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M-v1.1-zh", model=False)
        if english.g2p.fallback is None or phonemizer.g2p.fallback is None:
            raise VoiceError(
                "missing_pronunciation", "The offline English pronunciation fallback is missing."
            )

        def english_pronunciation(text):
            return next(phonemizer(text)).phonemes

        chinese = KPipeline(
            lang_code="z",
            repo_id="hexgrad/Kokoro-82M-v1.1-zh",
            model=model,
            en_callable=english_pronunciation,
        )
        self.voices = {
            "en": torch.load(
                model_root / "voices/af_maple.pt", map_location="cpu", weights_only=True
            ),
            "zh": torch.load(
                model_root / "voices/zf_001.pt", map_location="cpu", weights_only=True
            ),
        }
        self.pipelines = {"en": english, "zh": chinese}
        self.tts_model = model

    def synthesize(self, text: str, language: str, emit) -> dict:
        import numpy as np
        import torch

        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise VoiceError("invalid_text", "Speak one nonempty clause of at most 500 characters.")
        started = time.perf_counter()
        self.load_tts()
        selected = "zh" if re.search(r"[\u3400-\u9fff]", text) else "en"
        if language in {"en", "zh"}:
            selected = language
        output_samples = 0
        first_pcm_ms = None
        seq = 0
        # Keep synthesis clauses short. This bounds cancellation latency and
        # mitigates the official Chinese model's documented long-phrase rush.
        chunks = re.split(r"(?<=[.!?。！？;；])\s*|\n+", text)
        with torch.inference_mode():
            for clause in chunks:
                limit = 40 if selected == "zh" else 120
                segments = []
                remainder = clause.strip()
                while remainder:
                    cut = min(limit, len(remainder))
                    if cut < len(remainder):
                        word_boundary = remainder.rfind(" ", 0, cut + 1)
                        if word_boundary >= limit // 2:
                            cut = word_boundary
                    segments.append(remainder[:cut])
                    remainder = remainder[cut:].lstrip()
                for segment in segments:
                    segment = segment.strip()
                    if not segment:
                        continue
                    generator = self.pipelines[selected](
                        segment, voice=self.voices[selected], speed=1.0
                    )
                    for result in generator:
                        samples = result.audio
                        if samples is None:
                            continue
                        samples = (
                            samples.detach().cpu().numpy()
                            if hasattr(samples, "detach")
                            else samples
                        )
                        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
                        if not np.isfinite(samples).all():
                            raise VoiceError(
                                "invalid_output", "Local speech produced invalid samples."
                            )
                        output_samples += len(samples)
                        if output_samples > MAX_OUTPUT_SAMPLES:
                            raise VoiceError(
                                "output_too_long", "This speech clause exceeds the playback limit."
                            )
                        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                        # Small independently playable raw PCM packets; never
                        # imply token-level synthesis inside Kokoro's segment.
                        for at in range(0, len(pcm), 4800 * 2):
                            if first_pcm_ms is None:
                                first_pcm_ms = (time.perf_counter() - started) * 1000
                            emit(
                                {
                                    "type": "audio",
                                    "seq": seq,
                                    "pcm_b64": base64.b64encode(pcm[at : at + 9600]).decode(
                                        "ascii"
                                    ),
                                    "sample_rate": RATE,
                                    "channels": 1,
                                }
                            )
                            seq += 1
        if first_pcm_ms is None:
            raise VoiceError("empty_output", "Local speech did not produce any audio.")
        return {
            "first_pcm_ms": first_pcm_ms,
            "generation_ms": (time.perf_counter() - started) * 1000,
            "output_samples": output_samples,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument(
        "--allow-unverified", action="store_true", help="Installer smoke tests only"
    )
    args = parser.parse_args()
    root = args.runtime.resolve()
    output = sys.stdout

    def emit(event):
        output.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        output.flush()

    offline_environment(root)
    try:
        inspect_runtime(root, allow_unverified=args.allow_unverified)
    except (VoiceError, ValueError, KeyError, OSError) as exc:
        emit(
            {
                "type": "error",
                "code": getattr(exc, "code", "invalid_runtime"),
                "message": str(exc)
                if isinstance(exc, VoiceError)
                else "The local runtime is invalid.",
            }
        )
        return 1
    engine = LocalSpeech(root)
    emit(
        {"type": "ready", "protocol": 1, "format": "pcm_s16le", "sample_rate": RATE, "channels": 1}
    )
    while True:
        line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            break
        request_id = None
        try:
            if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                raise VoiceError("invalid_request", "The voice request exceeds its limit.")
            request = json.loads(line)
            request_id = request.get("id")
            if not isinstance(request_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", request_id
            ):
                raise VoiceError("invalid_request", "A valid voice request ID is required.")
            language = request.get("language", "auto")
            if language not in {"auto", "en", "zh"}:
                raise VoiceError(
                    "invalid_language", "Choose automatic, English or Mandarin speech."
                )
            op = request.get("op")
            with contextlib.redirect_stdout(sys.stderr):
                if op == "health":
                    emit(
                        {
                            "id": request_id,
                            "type": "result",
                            "ready": True,
                            "engine_versions": {
                                name: importlib.metadata.version(name) for name in ENGINE_PACKAGES
                            },
                        }
                    )
                    metrics = None
                elif op == "transcribe":
                    result = engine.transcribe(request["audio_path"], language)
                    emit({"id": request_id, "type": "result", **result})
                    metrics = None
                elif op == "synthesize":
                    metrics = engine.synthesize(
                        request["text"], language, lambda event: emit({"id": request_id, **event})
                    )
                else:
                    raise VoiceError(
                        "invalid_operation", "That local voice operation is not supported."
                    )
            emit({"id": request_id, "type": "done", **({"metrics": metrics} if metrics else {})})
        except VoiceError as exc:
            emit({"id": request_id, "type": "error", "code": exc.code, "message": str(exc)})
        except (KeyboardInterrupt, BrokenPipeError):
            return 0
        except Exception:
            # Do not leak speech, filesystem paths or dependency diagnostics to
            # the browser. The caller receives an honest, recoverable failure.
            emit(
                {
                    "id": request_id,
                    "type": "error",
                    "code": "engine_failed",
                    "message": "Local speech failed. The text remains available; retry the voice turn.",
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
