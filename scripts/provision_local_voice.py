#!/usr/bin/env python3
"""Explicit, bounded download of public pinned voice model assets; no inference.

The isolated Python environment is installed separately from a hashed lock.
Running without --download is a read-only preflight. No remote code is loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MIN_FREE = 8 * 1024**3
MAX_RUNTIME = 4 * 1024**3
WHISPER = "https://huggingface.co/mlx-community/whisper-large-v3-turbo-4bit/resolve/0f058d38170d183f9fdee07908f5b515d91793a8/"
KOKORO = "https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/resolve/01e7505bd6a7a2ac4975463114c3a7650a9f7218/"
SILERO = "https://raw.githubusercontent.com/snakers4/silero-vad/5cd7945676eb32225748052e2e6a0580e4686a08/"
ASSETS = [
    (
        "models/whisper/config.json",
        WHISPER + "config.json",
        341,
        "538e24557b8f9bc504700add5e7bbe32087c2353001ff563e64772ad4398671a",
    ),
    (
        "models/whisper/weights.safetensors",
        WHISPER + "model.safetensors",
        463462982,
        "e2d6146b49644c13ed7467060d3c43c402bbdfca1f01f1c21f6fbeda23b6567e",
    ),
    (
        "models/kokoro/config.json",
        KOKORO + "config.json",
        3228,
        "bc333efa5ce4ceff433c8c8e5d027a1eca0166001e4e4a62bea2d26ff7a46890",
    ),
    (
        "models/kokoro/kokoro-v1_1-zh.pth",
        KOKORO + "kokoro-v1_1-zh.pth",
        327247856,
        "b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b",
    ),
    (
        "models/kokoro/voices/af_maple.pt",
        KOKORO + "voices/af_maple.pt",
        523425,
        "f1211a6b94795d843cb7957568ccf2208e6ce76d2fbb36c7279b24e1be9b862f",
    ),
    (
        "models/kokoro/voices/zf_001.pt",
        KOKORO + "voices/zf_001.pt",
        523331,
        "9bdc9a87e13e9bb1ea3e7803259c2ecbfebaeeb2ff80b5d0c76df1a464c1c962",
    ),
    (
        "models/vad/silero_vad.onnx",
        SILERO + "src/silero_vad/data/silero_vad.onnx",
        2327524,
        "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    ),
    (
        "licenses/silero-MIT.txt",
        SILERO + "LICENSE",
        1075,
        "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b",
    ),
]


def disk_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    root = args.runtime.resolve()
    if not root.is_dir() or root == Path("/") or root == Path.home():
        raise SystemExit("Use an existing, dedicated voice-runtime directory.")
    required = sum(size for relative, _url, size, _sha in ASSETS if not (root / relative).exists())
    installed = disk_size(root)
    free = shutil.disk_usage(root).free
    print(
        json.dumps(
            {
                "preflight": True,
                "runtime_bytes": installed,
                "download_bytes_upper_bound": required,
                "free_bytes": free,
                "reserve_bytes": MIN_FREE,
            }
        ),
        flush=True,
    )
    if free < MIN_FREE + required + 64 * 1024**2 or installed + required > MAX_RUNTIME:
        raise SystemExit("Voice installation exceeds the approved disk budget.")
    if not args.download:
        return 0
    existing_manifest = root / "manifest.json"
    if existing_manifest.exists():
        raise SystemExit(
            "An existing manifest must be inspected; this installer will not overwrite it."
        )
    records = []
    for relative, url, maximum, expected in ASSETS:
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise SystemExit("Refusing a model path outside this runtime.")
        if target.exists():
            if not expected or target.stat().st_size != maximum or sha256(target) != expected:
                raise SystemExit(f"Inspect the existing asset before retrying: {relative}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            if partial.exists():
                raise SystemExit(f"Inspect the unfinished download before retrying: {relative}")
            request = urllib.request.Request(
                url, headers={"User-Agent": "Alles-local-voice-provisioner/1"}
            )
            written = 0
            with (
                urllib.request.urlopen(request, timeout=30) as response,
                partial.open("xb") as output,
            ):
                if not response.geturl().startswith("https://"):
                    raise SystemExit("Refusing an insecure model redirect.")
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > maximum or shutil.disk_usage(root).free < MIN_FREE + len(chunk):
                        raise SystemExit("Model download exceeded its size or free-space limit.")
                    output.write(chunk)
            digest = sha256(partial)
            if expected and (written != maximum or digest != expected):
                raise SystemExit(
                    f"Model verification failed; partial retained for inspection: {relative}"
                )
            partial.replace(target)
        digest = sha256(target)
        records.append(
            {
                "path": relative,
                "size": target.stat().st_size,
                "sha256": digest,
                "source_url": url,
                "upstream_sha256_verified": expected is not None,
            }
        )
        print(
            json.dumps({"downloaded": relative, "bytes": target.stat().st_size, "sha256": digest}),
            flush=True,
        )
    manifest = {
        "schema_version": 1,
        "status": "assets_verified",
        "python": ".venv/bin/python",
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            "whisper": {"path": "models/whisper"},
            "kokoro": {"path": "models/kokoro"},
            "vad": {"path": "models/vad/silero_vad.onnx"},
        },
        "files": records,
        "notes": [
            "Whisper's official conversion model.safetensors is stored as weights.safetensors for mlx-whisper 0.4.3; bytes are unchanged.",
            "Not ready until offline English, Mandarin and mixed-language smoke checks pass.",
            "Models: Whisper upstream MIT and MLX conversion Apache-2.0; Kokoro Apache-2.0; Silero MIT. Dependency licenses are recorded separately.",
        ],
    }
    existing_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "assets_verified", "runtime_bytes": disk_size(root)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
