import asyncio
import hmac
import os
import shutil
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from core.api_errors import ApiError
from core.auth import require_recent_owner
from core.settings import data_dir
from services import webdav_backup
from services.backup_recovery import (
    CHUNK_SIZE,
    DEFAULT_LIMITS,
    ArchiveLimits,
    RecoveryError,
    create_recovery_archive,
    discard_staged_recovery,
    get_staged_recovery,
    stage_recovery_archive,
    staging_root,
)
from services.recovery_crypto import (
    decrypt_recovery_container,
    encrypt_recovery_archive,
    is_encrypted_recovery,
    load_or_create_recovery_key,
    load_recovery_key,
    parse_recovery_key,
    recovery_key_path,
)

router = APIRouter(prefix="/api")

DATA_DIR: Path | None = None
BACKUP_LIMITS: ArchiveLimits = DEFAULT_LIMITS
_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60
_WEBDAV_RUN_LOCK = threading.Lock()


class _UploadTooLarge(RecoveryError):
    pass


class WebDAVConfigBody(BaseModel):
    url: str
    username: str
    password: str = ""


def _data_dir() -> Path:
    return DATA_DIR or data_dir()


def _require_same_origin(request: Request) -> None:
    """Keep private backup bytes away from cross-site browser requests.

    This matters even in local mode, where normal API authentication can be off.
    """
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site == "cross-site":
        raise HTTPException(403, "cross-site backup requests are not allowed")

    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    host = request.headers.get("host", "")
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != host.casefold():
        raise HTTPException(403, "cross-site backup requests are not allowed")


def _sweep_old_temp(directory: Path) -> None:
    """Remove abandoned export/upload temp items left by a crashed process."""
    try:
        children = list(directory.iterdir()) if directory.is_dir() else []
    except OSError:
        return
    cutoff = time.time() - _TEMP_MAX_AGE_SECONDS
    for child in children:
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            continue


def _create_encrypted_backup(
    root: Path,
    archive: Path,
    *,
    include_photos: bool = False,
) -> Path:
    """Create the same verified encrypted artifact for download or a remote target."""
    plaintext = archive.parent / f".{archive.name}.{uuid.uuid4().hex}.zip"
    try:
        recovery_key = load_or_create_recovery_key(root)
        create_recovery_archive(
            root,
            plaintext,
            include_photos=include_photos,
            expected_recovery_key=recovery_key,
            limits=BACKUP_LIMITS,
        )
        try:
            plaintext.chmod(0o600)
        except OSError:
            pass
        encrypt_recovery_archive(
            plaintext,
            archive,
            recovery_key,
            limits=BACKUP_LIMITS,
        )
        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    finally:
        try:
            plaintext.unlink(missing_ok=True)
        except OSError as exc:
            archive.unlink(missing_ok=True)
            raise RecoveryError("temporary plaintext backup could not be removed") from exc


def _stage_stored_backup(
    root: Path,
    incoming: Path,
    *,
    recovery_key: bytes | None = None,
):
    """Decrypt when needed, stage, and bind the inner key to the encrypted container."""
    decrypted = incoming.parent / f"{uuid.uuid4().hex}.zip"
    encrypted = is_encrypted_recovery(incoming)
    key = recovery_key
    try:
        archive_to_stage = incoming
        if encrypted:
            key = key or load_recovery_key(recovery_key_path(root))
            decrypt_recovery_container(
                incoming,
                decrypted,
                key,
                limits=BACKUP_LIMITS,
            )
            archive_to_stage = decrypted
        staged = stage_recovery_archive(
            archive_to_stage,
            root,
            limits=BACKUP_LIMITS,
        )
        if encrypted:
            try:
                restored_key = load_recovery_key(staged.data_dir / "recovery.key")
                if not hmac.compare_digest(restored_key, key):
                    raise RecoveryError(
                        "backup recovery key does not match its encrypted container"
                    )
            except RecoveryError:
                discard_staged_recovery(root, staged.restore_id)
                raise
        return staged
    finally:
        try:
            decrypted.unlink(missing_ok=True)
        except OSError:
            pass


def _staged_response(staged) -> dict:
    return {
        "ok": True,
        "status": "staged",
        "restore_id": staged.restore_id,
        "requires_offline_apply": True,
        "apply_command": f"alles restore apply {staged.restore_id}",
        "files": staged.manifest["totals"]["files"],
        "bytes": staged.manifest["totals"]["bytes"],
        "excluded_locations": [
            item["role"] for item in staged.manifest["locations"] if not item["included"]
        ],
        "message": "backup verified and staged; live data was not changed",
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _webdav_error(exc: Exception, *, status_code: int = 502) -> ApiError:
    if isinstance(exc, webdav_backup.WebDAVBusyError):
        return ApiError(409, "webdav_backup_busy", str(exc))
    return ApiError(status_code, "webdav_backup_failed", str(exc))


async def _stream_upload_to_path(
    upload: UploadFile,
    destination: Path,
    *,
    limits: ArchiveLimits,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    total = 0
    try:
        with destination.open("xb") as handle:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > limits.max_archive_bytes:
                    raise _UploadTooLarge("backup upload exceeds the configured size limit")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            destination.chmod(0o600)
        except OSError:
            pass
    except RecoveryError:
        raise
    except OSError as exc:
        raise RecoveryError("could not store the backup upload safely") from exc
    return total


@router.get("/backup", dependencies=[Depends(require_recent_owner)])
def export_backup(request: Request, include_photos: bool = False):
    _require_same_origin(request)
    root = _data_dir().expanduser().resolve()
    export_parent = staging_root(root) / "exports"
    export_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _sweep_old_temp(export_parent)
    export_dir = Path(tempfile.mkdtemp(prefix="export-", dir=export_parent))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"alles-backup-{timestamp}.alles-backup"
    archive = export_dir / filename
    try:
        _create_encrypted_backup(
            root,
            archive,
            include_photos=include_photos,
        )
    except RecoveryError as exc:
        shutil.rmtree(export_dir, ignore_errors=True)
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(export_dir, ignore_errors=True)
        raise HTTPException(500, "backup creation failed") from exc

    return FileResponse(
        archive,
        media_type="application/vnd.alles.backup",
        filename=filename,
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(shutil.rmtree, export_dir, ignore_errors=True),
    )


@router.get("/backup/recovery-key", dependencies=[Depends(require_recent_owner)])
def export_recovery_key(request: Request):
    _require_same_origin(request)
    root = _data_dir().expanduser().resolve()
    try:
        load_or_create_recovery_key(root)
    except RecoveryError as exc:
        raise HTTPException(500, str(exc)) from exc
    return FileResponse(
        recovery_key_path(root),
        media_type="text/plain; charset=utf-8",
        filename="alles-recovery-key.txt",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/backup/webdav")
def webdav_status(request: Request):
    _require_same_origin(request)
    return webdav_backup.status()


@router.put("/backup/webdav", dependencies=[Depends(require_recent_owner)])
def configure_webdav(request: Request, body: WebDAVConfigBody):
    _require_same_origin(request)
    try:
        candidate = {
            "url": body.url,
            "username": body.username,
            "password": body.password,
        }
        if not body.password:
            current = webdav_backup.load_config()
            normalized = webdav_backup.normalize_collection_url(body.url)
            if normalized == current.get("url") and body.username == current.get("username"):
                candidate["password"] = current.get("password", "")
        verified = webdav_backup.test_connection(candidate)
        saved = webdav_backup.save_config(candidate, verified_at=verified["verified_at"])
        return {"ok": True, **saved}
    except webdav_backup.WebDAVError as exc:
        raise _webdav_error(exc, status_code=400) from exc
    except Exception as exc:
        raise ApiError(
            500, "webdav_config_save_failed", "webdav settings could not be saved"
        ) from exc


@router.delete("/backup/webdav", dependencies=[Depends(require_recent_owner)])
def disconnect_webdav(request: Request):
    _require_same_origin(request)
    try:
        webdav_backup.delete_config()
    except webdav_backup.WebDAVError as exc:
        raise _webdav_error(exc, status_code=400) from exc
    except Exception as exc:
        raise ApiError(
            500,
            "webdav_config_delete_failed",
            "webdav settings could not be removed",
        ) from exc
    return {"ok": True, **webdav_backup.status()}


@router.post("/backup/webdav/run", dependencies=[Depends(require_recent_owner)])
def run_webdav_backup(request: Request, include_photos: bool = False):
    _require_same_origin(request)
    if not _WEBDAV_RUN_LOCK.acquire(blocking=False):
        raise ApiError(409, "webdav_backup_busy", "another webdav backup job is already running")
    export_dir: Path | None = None
    try:
        root = _data_dir().expanduser().resolve()
        export_parent = staging_root(root) / "exports"
        export_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _sweep_old_temp(export_parent)
        export_dir = Path(tempfile.mkdtemp(prefix="webdav-", dir=export_parent))
        artifact = export_dir / "encrypted.alles-backup"
        _create_encrypted_backup(root, artifact, include_photos=include_photos)
        result = webdav_backup.upload_artifact(artifact)
        current_status = webdav_backup.status()
        completed_at = (
            result.get("completed_at") or current_status.get("last_backup_at") or _utc_now()
        )
        verified_at = (
            result.get("completed_at") or current_status.get("last_verified_at") or completed_at
        )
        return {
            "ok": True,
            "filename": result["name"],
            "bytes": result["size"],
            "sha256": result["sha256"],
            "last_backup_at": completed_at,
            "last_verified_at": verified_at,
            "status_warning": result.get("status_warning", ""),
        }
    except webdav_backup.WebDAVError as exc:
        raise _webdav_error(exc) from exc
    except RecoveryError as exc:
        raise ApiError(500, "backup_creation_failed", str(exc)) from exc
    except Exception as exc:
        raise ApiError(500, "backup_creation_failed", "backup creation failed") from exc
    finally:
        if export_dir is not None:
            shutil.rmtree(export_dir, ignore_errors=True)
        _WEBDAV_RUN_LOCK.release()


@router.get("/backup/webdav/backups")
def list_webdav_backups(request: Request):
    _require_same_origin(request)
    try:
        backups = webdav_backup.list_artifacts()
    except webdav_backup.WebDAVError as exc:
        raise _webdav_error(exc) from exc
    return {
        "backups": [
            {
                "filename": item["name"],
                "bytes": item.get("size"),
                "modified_at": item.get("modified", ""),
            }
            for item in backups
        ]
    }


@router.post(
    "/backup/webdav/restore",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_recent_owner)],
)
async def restore_webdav_backup(
    request: Request,
    filename: str = Form(...),
    recovery_key: UploadFile | None = File(None),
):
    _require_same_origin(request)
    root = _data_dir().expanduser().resolve()
    incoming_dir = staging_root(root) / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _sweep_old_temp(incoming_dir)
    incoming = incoming_dir / f"{uuid.uuid4().hex}.alles-backup"
    try:
        items = await asyncio.to_thread(webdav_backup.list_artifacts)
        selected = next((item for item in items if item.get("name") == filename), None)
        if selected is None:
            raise webdav_backup.WebDAVError("webdav backup was not found")
        expected_size = selected.get("size")
        await asyncio.to_thread(
            webdav_backup.download_artifact,
            filename,
            incoming,
            expected_size=expected_size if isinstance(expected_size, int) else None,
        )
        key = None
        if recovery_key is not None:
            key_document = await recovery_key.read(4097)
            if len(key_document) > 4096:
                raise RecoveryError("uploaded recovery key file is too large")
            key = parse_recovery_key(key_document)
        staged = await asyncio.to_thread(
            _stage_stored_backup,
            root,
            incoming,
            recovery_key=key,
        )
    except webdav_backup.WebDAVError as exc:
        raise _webdav_error(exc) from exc
    except RecoveryError as exc:
        raise ApiError(400, "backup_validation_failed", str(exc)) from exc
    except Exception as exc:
        raise ApiError(400, "backup_validation_failed", "backup validation failed") from exc
    finally:
        try:
            incoming.unlink(missing_ok=True)
        except OSError:
            pass
    return _staged_response(staged)


@router.post(
    "/backup/restore",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_recent_owner)],
)
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    recovery_key: UploadFile | None = File(None),
):
    _require_same_origin(request)
    root = _data_dir().expanduser().resolve()
    incoming_dir = staging_root(root) / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _sweep_old_temp(incoming_dir)
    incoming = incoming_dir / f"{uuid.uuid4().hex}.partial"

    try:
        size = await _stream_upload_to_path(file, incoming, limits=BACKUP_LIMITS)
        if size == 0:
            raise RecoveryError("backup upload is empty")
        encrypted_upload = is_encrypted_recovery(incoming)
        key = None
        if encrypted_upload:
            if recovery_key is not None:
                key_document = await recovery_key.read(4097)
                if len(key_document) > 4096:
                    raise RecoveryError("uploaded recovery key file is too large")
                key = parse_recovery_key(key_document)
            else:
                key = load_recovery_key(recovery_key_path(root))
        staged = await asyncio.to_thread(
            _stage_stored_backup,
            root,
            incoming,
            recovery_key=key,
        )
    except _UploadTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except RecoveryError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "backup validation failed") from exc
    finally:
        try:
            incoming.unlink(missing_ok=True)
        except OSError:
            pass

    return _staged_response(staged)


@router.get("/backup/restores/{restore_id}")
def restore_status(request: Request, restore_id: str):
    _require_same_origin(request)
    try:
        staged = get_staged_recovery(_data_dir(), restore_id)
    except RecoveryError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "ok": True,
        "status": staged.state,
        "restore_id": staged.restore_id,
        "files": staged.manifest["totals"]["files"],
        "bytes": staged.manifest["totals"]["bytes"],
        "requires_offline_apply": True,
    }


@router.delete("/backup/restores/{restore_id}", dependencies=[Depends(require_recent_owner)])
def cancel_restore(request: Request, restore_id: str):
    _require_same_origin(request)
    try:
        discard_staged_recovery(_data_dir(), restore_id)
    except RecoveryError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "status": "cancelled", "restore_id": restore_id}
