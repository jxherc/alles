#!/usr/bin/env python3
"""Reproduce the Phase 1 Kopia compatibility spike with synthetic data only."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli  # noqa: E402
from services.backup_recovery import (  # noqa: E402
    create_recovery_archive,
    stage_recovery_archive,
)
from services.recovery_crypto import (  # noqa: E402
    decrypt_recovery_container,
    encrypt_recovery_archive,
    load_or_create_recovery_key,
    parse_recovery_key,
    recovery_key_document,
)

REPOSITORY_PASSWORD = "synthetic-kopia-phase-one-password"
MARKER_ONE = "kopia-spike-marker-first"
MARKER_TWO = "kopia-spike-marker-second"
PAYLOAD_BYTES = 12 * 1024 * 1024


def _run(kopia: Path, env: dict[str, str], *args: str, check: bool = True):
    command = [
        str(kopia),
        "--disable-file-logging",
        "--no-use-keychain",
        "--no-persist-credentials",
        "--no-progress",
        *args,
    ]
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "kopia command failed").strip()
        message = message.replace(REPOSITORY_PASSWORD, "[hidden]")
        raise RuntimeError(message)
    return result


def _content_bytes(output: str) -> int:
    match = re.search(r"^Total Bytes:\s*([0-9]+)\s*$", output, re.MULTILINE)
    if not match:
        raise RuntimeError("Kopia content statistics did not include raw total bytes")
    return int(match.group(1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_incompressible_fixture(path: Path) -> None:
    generator = random.Random(20260712)
    remaining = PAYLOAD_BYTES
    with path.open("wb") as handle:
        while remaining:
            block = generator.randbytes(min(1024 * 1024, remaining))
            handle.write(block)
            remaining -= len(block)


def _create_artifact(root: Path, work: Path, artifact: Path, key: bytes) -> None:
    plaintext = work / "recovery.zip"
    plaintext.unlink(missing_ok=True)
    artifact.unlink(missing_ok=True)
    create_recovery_archive(root, plaintext, expected_recovery_key=key)
    try:
        encrypt_recovery_archive(plaintext, artifact, key)
    finally:
        plaintext.unlink(missing_ok=True)


def _repository_contains(paths: list[Path], needles: list[bytes]) -> bool:
    for root in paths:
        files = [root] if root.is_file() else root.rglob("*") if root.exists() else []
        for path in files:
            if not path.is_file():
                continue
            content = path.read_bytes()
            if any(needle in content for needle in needles):
                return True
    return False


def run_spike(kopia: Path) -> dict:
    if not kopia.is_file() or not os.access(kopia, os.X_OK):
        raise RuntimeError("--kopia must point to an executable Kopia CLI binary")
    version_output = _run(kopia, os.environ.copy(), "--version").stdout.strip()

    with tempfile.TemporaryDirectory(prefix="alles-kopia-spike-") as temp:
        base = Path(temp)
        source_install = base / "source-install"
        source = source_install / "data"
        work = source_install / "work"
        artifacts = source_install / "artifacts"
        owner_keys = base / "owner-keys"
        repository = base / "repository"
        client = base / "client"
        clean = base / "clean-install" / "data"
        restored = base / "restored"
        for path in (source, work, artifacts, owner_keys, repository, client, clean):
            path.mkdir(parents=True)

        if not cli._run_recovery_probe(source, passes=1):
            raise RuntimeError("synthetic source did not pass the Alles recovery probe")
        files = source / "files"
        files.mkdir(exist_ok=True)
        _write_incompressible_fixture(files / "stable-random.bin")
        marker = files / "kopia-marker.txt"
        marker.write_text(MARKER_ONE, "utf-8")

        recovery_key = load_or_create_recovery_key(source)
        exported_key = owner_keys / "alles-recovery-key.txt"
        exported_key.write_bytes(recovery_key_document(recovery_key))
        artifact = artifacts / "backup.alles-backup"
        _create_artifact(source, work, artifact, recovery_key)
        first_size = artifact.stat().st_size
        first_sha256 = _sha256(artifact)

        env = os.environ.copy()
        env.update(
            {
                "KOPIA_PASSWORD": REPOSITORY_PASSWORD,
                "KOPIA_CONFIG_PATH": str(client / "repository.config"),
                "KOPIA_CACHE_DIRECTORY": str(client / "cache"),
                "KOPIA_LOG_DIR": str(client / "logs"),
            }
        )
        _run(
            kopia,
            env,
            "repository",
            "create",
            "filesystem",
            "--path",
            str(repository),
            "--no-check-for-updates",
        )
        _run(kopia, env, "repository", "validate-provider")
        status_output = _run(kopia, env, "repository", "status").stdout
        if "Encryption:          AES256-GCM-HMAC-SHA256" not in status_output:
            raise RuntimeError("Kopia repository did not report the expected encryption")

        first_snapshot = json.loads(
            _run(
                kopia,
                env,
                "snapshot",
                "create",
                str(artifacts),
                "--json",
                "--force-hash=100",
                "--description=alles phase 1 first artifact",
            ).stdout
        )
        first_repository_bytes = _content_bytes(
            _run(kopia, env, "content", "stats", "--raw").stdout
        )

        marker.write_text(MARKER_TWO, "utf-8")
        _create_artifact(source, work, artifact, recovery_key)
        second_size = artifact.stat().st_size
        second_sha256 = _sha256(artifact)
        if second_sha256 == first_sha256:
            raise RuntimeError("independent encrypted backups unexpectedly matched")

        second_snapshot = json.loads(
            _run(
                kopia,
                env,
                "snapshot",
                "create",
                str(artifacts),
                "--json",
                "--force-hash=100",
                "--description=alles phase 1 second artifact",
            ).stdout
        )
        second_repository_bytes = _content_bytes(
            _run(kopia, env, "content", "stats", "--raw").stdout
        )
        _run(
            kopia,
            env,
            "snapshot",
            "verify",
            second_snapshot["id"],
            "--verify-files-percent=100",
            "--json",
        )
        _run(kopia, env, "repository", "disconnect")

        shutil.rmtree(source_install)
        shutil.rmtree(client)
        if source.exists() or artifact.exists():
            raise RuntimeError("source installation was not deleted")

        wrong_env = dict(env)
        wrong_env["KOPIA_PASSWORD"] = "synthetic-wrong-password"
        wrong = _run(
            kopia,
            wrong_env,
            "repository",
            "connect",
            "filesystem",
            "--path",
            str(repository),
            check=False,
        )
        if wrong.returncode == 0:
            raise RuntimeError("Kopia accepted the wrong repository password")
        shutil.rmtree(client, ignore_errors=True)
        client.mkdir()

        _run(
            kopia,
            env,
            "repository",
            "connect",
            "filesystem",
            "--path",
            str(repository),
        )
        _run(
            kopia,
            env,
            "restore",
            second_snapshot["rootEntry"]["obj"],
            str(restored),
            "--write-files-atomically",
            "--no-overwrite-files",
            "--no-overwrite-directories",
            "--no-overwrite-symlinks",
        )
        restored_artifact = restored / artifact.name
        if _sha256(restored_artifact) != second_sha256:
            raise RuntimeError("Kopia restore changed the encrypted artifact")

        downloaded_key = parse_recovery_key(exported_key.read_bytes())
        decrypted = base / "restored-recovery.zip"
        decrypt_recovery_container(restored_artifact, decrypted, downloaded_key)
        staged = stage_recovery_archive(decrypted, clean)
        if (staged.data_dir / "files" / marker.name).read_text("utf-8") != MARKER_TWO:
            raise RuntimeError("staged restore did not contain the newest marker")
        if not cli._run_recovery_probe(staged.data_dir, passes=2):
            raise RuntimeError("Kopia-restored artifact did not pass repeat boot/migration probes")

        repository_leaked_plaintext = _repository_contains(
            [repository, client / "repository.config"],
            [
                REPOSITORY_PASSWORD.encode(),
                MARKER_ONE.encode(),
                MARKER_TWO.encode(),
                exported_key.read_bytes(),
            ],
        )
        if repository_leaked_plaintext:
            raise RuntimeError("Kopia repository or config exposed synthetic plaintext")

        s3_help = _run(kopia, env, "repository", "create", "s3", "--help").stdout
        webdav_help = _run(kopia, env, "repository", "create", "webdav", "--help").stdout
        if "Create repository in an S3 bucket" not in s3_help:
            raise RuntimeError("Kopia CLI did not expose its S3 repository provider")
        if "Create repository in a WebDAV storage" not in webdav_help:
            raise RuntimeError("Kopia CLI did not expose its WebDAV repository provider")

        added_bytes = second_repository_bytes - first_repository_bytes
        return {
            "kopia_version": version_output,
            "repository_encryption": "AES256-GCM-HMAC-SHA256",
            "provider_validation": "passed",
            "supported_provider_commands": ["filesystem", "s3", "webdav"],
            "first_artifact_bytes": first_size,
            "second_artifact_bytes": second_size,
            "first_repository_content_bytes": first_repository_bytes,
            "second_repository_content_bytes": second_repository_bytes,
            "new_content_bytes_for_second_artifact": added_bytes,
            "new_content_ratio": round(added_bytes / second_size, 4),
            "snapshot_ids": [first_snapshot["id"], second_snapshot["id"]],
            "wrong_password_rejected": True,
            "source_install_deleted": True,
            "restored_artifact_sha256_matched": True,
            "staged_restore_repeat_probe": "passed",
            "repository_plaintext_scan": "passed",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kopia", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_spike(args.kopia.expanduser().resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
