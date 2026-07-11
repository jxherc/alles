"""Native Apple Photos adapter backed by a small signed PhotoKit helper app.

The FastAPI process never receives Photos permission. On the first explicit
Gallery import, Alles builds a local helper app under ``ALLES_DATA`` with the
required privacy purpose string and Photos entitlement, then macOS grants (or
denies) access to that narrowly-scoped helper identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import select
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.settings import data_dir


class PhotoKitError(RuntimeError):
    pass


class PhotoKitUnavailableError(PhotoKitError):
    pass


class PhotoKitPermissionError(PhotoKitError):
    def __init__(self, state: str):
        self.state = state
        super().__init__(
            "Apple Photos access is not allowed. Enable Alles Photo Import in "
            "System Settings > Privacy & Security > Photos."
        )


class PhotoKitTimeoutError(PhotoKitError):
    pass


class PhotoKitExportError(PhotoKitError):
    pass


@dataclass(frozen=True)
class PhotoKitResource:
    source_id: str
    asset_id: str
    kind: str  # photo | video | paired_video
    original_name: str
    taken_at: datetime | None
    modified_at: datetime | None
    favorite: bool
    hidden: bool
    width: int
    height: int
    exif: dict
    resource: object


_NATIVE = Path(__file__).with_name("native")
_SOURCE = _NATIVE / "photokit_bridge.swift"
_INFO = _NATIVE / "photokit_bridge_Info.plist"
_ENTITLEMENTS = _NATIVE / "photokit_bridge.entitlements"
_BUILD_LOCK = threading.Lock()
_EXPORT_LOCK = threading.Lock()
_EXPORT_PROCESS = None
_READY = {"authorized", "limited"}
_MIN_MACOS = "11.0"


def _app_path() -> Path:
    return data_dir() / "native" / "AllesPhotoKitBridge.app"


def _binary_path() -> Path:
    return _app_path() / "Contents" / "MacOS" / "AllesPhotoKitBridge"


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _build_target() -> str:
    architecture = platform.machine().lower()
    if architecture not in {"arm64", "x86_64"}:
        raise PhotoKitUnavailableError("this Mac architecture is not supported")
    return f"{architecture}-apple-macosx{_MIN_MACOS}"


def _signing_identity() -> str:
    """Optional real identity gives helper updates a stable, signer-bound DR.

    The secure fallback is a version-bound ad-hoc signature. Deliberately avoid
    an identifier-only custom requirement, which another local binary could spoof.
    """
    return os.environ.get("ALLES_PHOTOKIT_SIGN_IDENTITY", "").strip()


def _source_digest() -> str:
    digest = hashlib.sha256()
    for path in (_SOURCE, _INFO, _ENTITLEMENTS):
        digest.update(path.read_bytes())
    digest.update(_build_target().encode("ascii"))
    digest.update((_signing_identity() or "adhoc").encode("utf-8"))
    return digest.hexdigest()


def _built_digest() -> str:
    try:
        return (_app_path() / "Contents" / "Resources" / "source.sha256").read_text("utf-8").strip()
    except OSError:
        return ""


def _support_reason() -> str | None:
    if sys.platform != "darwin":
        return "Apple Photos import requires macOS"
    if platform.machine().lower() not in {"arm64", "x86_64"}:
        return "this Mac architecture is not supported"
    if not _tool("xcrun"):
        return "install Apple Command Line Tools to prepare the PhotoKit helper"
    if not _tool("codesign"):
        return "macOS code signing tools are unavailable"
    if not all(path.is_file() for path in (_SOURCE, _INFO, _ENTITLEMENTS)):
        return "the PhotoKit helper sources are missing"
    return None


def _ensure_helper() -> Path:
    reason = _support_reason()
    if reason:
        raise PhotoKitUnavailableError(reason)
    with _BUILD_LOCK:
        expected = _source_digest()
        binary = _binary_path()
        if binary.is_file() and _built_digest() == expected:
            return binary

        parent = _app_path().parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="photokit-build-", dir=parent) as temp:
            app = Path(temp) / "AllesPhotoKitBridge.app"
            macos = app / "Contents" / "MacOS"
            resources = app / "Contents" / "Resources"
            macos.mkdir(parents=True)
            resources.mkdir(parents=True)
            shutil.copy2(_INFO, app / "Contents" / "Info.plist")
            binary = macos / "AllesPhotoKitBridge"
            try:
                subprocess.run(
                    [
                        _tool("xcrun"),
                        "swiftc",
                        "-target",
                        _build_target(),
                        "-swift-version",
                        "5",
                        "-O",
                        "-framework",
                        "Photos",
                        "-framework",
                        "UniformTypeIdentifiers",
                        str(_SOURCE),
                        "-o",
                        str(binary),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=180,
                )
                (resources / "source.sha256").write_text(expected, "utf-8")
                subprocess.run(
                    [
                        _tool("codesign"),
                        "--force",
                        "--sign",
                        _signing_identity() or "-",
                        "--options",
                        "runtime",
                        "--timestamp=none",
                        "--entitlements",
                        str(_ENTITLEMENTS),
                        str(app),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise PhotoKitUnavailableError("could not prepare the PhotoKit helper") from exc

            shutil.rmtree(_app_path(), ignore_errors=True)
            shutil.move(str(app), str(_app_path()))
        return _binary_path()


def _run_helper(args, *, build=False, timeout=120):
    binary = _ensure_helper() if build else _binary_path()
    if not binary.is_file():
        raise PhotoKitUnavailableError("the PhotoKit helper has not been prepared")
    try:
        result = subprocess.run(
            [str(binary), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PhotoKitTimeoutError("the PhotoKit helper timed out") from exc
    except OSError as exc:
        raise PhotoKitUnavailableError("the PhotoKit helper could not start") from exc
    if result.returncode == 3:
        raise PhotoKitTimeoutError("Apple Photos did not finish in time")
    if result.returncode == 6:
        raise PhotoKitPermissionError("denied")
    if result.returncode:
        raise PhotoKitError("the PhotoKit helper failed")
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PhotoKitError("the PhotoKit helper returned an invalid response") from exc


def status() -> dict:
    reason = _support_reason()
    if reason:
        return {
            "platform": sys.platform,
            "available": False,
            "authorization": "unavailable",
            "ready": False,
            "reason": reason,
        }
    if not _binary_path().is_file() or _built_digest() != _source_digest():
        return {
            "platform": sys.platform,
            "available": True,
            "authorization": "not_determined",
            "ready": False,
            "reason": "permission will be requested when you import",
        }
    try:
        state = str(_run_helper(["status"])["authorization"])
    except PhotoKitError as exc:
        return {
            "platform": sys.platform,
            "available": False,
            "authorization": "unavailable",
            "ready": False,
            "reason": str(exc),
        }
    reasons = {
        "not_determined": "permission will be requested when you import",
        "restricted": "Photos access is restricted by macOS",
        "denied": "allow Alles Photo Import in System Settings > Privacy & Security > Photos",
        "authorized": "ready",
        "limited": "ready with limited-library access",
    }
    return {
        "platform": sys.platform,
        "available": True,
        "authorization": state,
        "ready": state in _READY,
        "reason": reasons.get(state, "unknown Photos authorization state"),
    }


def ensure_authorized(timeout=75) -> str:
    payload = _run_helper(["authorize"], build=True, timeout=timeout)
    state = str(payload.get("authorization", "unknown"))
    if state not in _READY:
        raise PhotoKitPermissionError(state)
    return state


def _datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def iter_resources() -> list[PhotoKitResource]:
    rows = _run_helper(["list"], build=True, timeout=180)
    if not isinstance(rows, list):
        raise PhotoKitError("the PhotoKit helper returned an invalid resource list")
    resources = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            metadata = {"live_photo": bool(row.get("live_photo"))}
            if row.get("lat") is not None and row.get("lon") is not None:
                metadata["lat"] = round(float(row["lat"]), 6)
                metadata["lon"] = round(float(row["lon"]), 6)
            resources.append(
                PhotoKitResource(
                    source_id=str(row["source_id"]),
                    asset_id=str(row["asset_id"]),
                    kind=str(row["kind"]),
                    original_name=Path(str(row["original_name"])).name,
                    taken_at=_datetime(row.get("taken_at")),
                    modified_at=_datetime(row.get("modified_at")),
                    favorite=bool(row.get("favorite")),
                    hidden=bool(row.get("hidden")),
                    width=max(0, int(row.get("width") or 0)),
                    height=max(0, int(row.get("height") or 0)),
                    exif=metadata,
                    resource={"asset_id": str(row["asset_id"]), "kind": str(row["kind"])},
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return resources


def _stop_export_process():
    global _EXPORT_PROCESS
    process, _EXPORT_PROCESS = _EXPORT_PROCESS, None
    if process is None:
        return
    try:
        if process.stdin:
            process.stdin.close()
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def close_export_session():
    with _EXPORT_LOCK:
        _stop_export_process()


def _export_via_session(item: PhotoKitResource, path: Path, timeout: int):
    global _EXPORT_PROCESS
    if _EXPORT_PROCESS is None or _EXPORT_PROCESS.poll() is not None:
        binary = _ensure_helper()
        try:
            _EXPORT_PROCESS = subprocess.Popen(
                [str(binary), "serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise PhotoKitUnavailableError("the PhotoKit helper could not start") from exc
    process = _EXPORT_PROCESS
    request = json.dumps(
        {
            "asset_id": item.asset_id,
            "kind": item.kind,
            "destination": str(path),
            "timeout": max(1, int(timeout)),
        },
        separators=(",", ":"),
    )
    try:
        process.stdin.write(request + "\n")
        process.stdin.flush()
    except (AttributeError, BrokenPipeError, OSError) as exc:
        _stop_export_process()
        raise PhotoKitExportError("the PhotoKit export session stopped") from exc
    ready, _, _ = select.select([process.stdout], [], [], max(5, int(timeout) + 5))
    if not ready:
        _stop_export_process()
        raise PhotoKitTimeoutError("Apple Photos did not finish in time")
    line = process.stdout.readline()
    try:
        response = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        _stop_export_process()
        raise PhotoKitExportError(
            "the PhotoKit export session returned an invalid response"
        ) from exc
    if not isinstance(response, dict):
        _stop_export_process()
        raise PhotoKitExportError("the PhotoKit export session returned an invalid response")
    if not response.get("ok"):
        _stop_export_process()
        if response.get("error") == "timeout":
            raise PhotoKitTimeoutError("Apple Photos did not finish in time")
        raise PhotoKitExportError("Apple Photos could not export a media resource")


def export_resource(item: PhotoKitResource, destination, timeout=300) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    try:
        with _EXPORT_LOCK:
            _export_via_session(item, path, int(timeout))
    except PhotoKitError:
        path.unlink(missing_ok=True)
        raise
    if not path.is_file():
        raise PhotoKitExportError("Apple Photos did not create the requested media resource")
    return path
