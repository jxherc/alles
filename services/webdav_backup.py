"""Small, fail-closed WebDAV client for encrypted Alles backup artifacts."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import stat
import threading
import unicodedata
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote_to_bytes, urljoin, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as ET

from core.settings import data_dir
from services.backup_recovery import CHUNK_SIZE, DEFAULT_LIMITS
from services.config_secrets import load_secret_config, migrate_secret_config, save_secret_config
from services.recovery_crypto import HEADER_MAX_BYTES, MAGIC, TAG_BYTES, _read_header

CONFIG_PATH: Path | None = None
CONFIG_NAME = "webdav_backup.json"
PASSWORD_PURPOSE = "backup.webdav.password"

MAX_URL_BYTES = 4096
MAX_USERNAME_BYTES = 1024
MAX_PASSWORD_BYTES = 16 * 1024
MAX_LISTING_BYTES = 2 * 1024 * 1024
MAX_LISTED_ARTIFACTS = 10_000
MAX_ARTIFACT_BYTES = DEFAULT_LIMITS.max_archive_bytes + HEADER_MAX_BYTES + TAG_BYTES + 64

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
CLIENT_LIMITS = httpx.Limits(max_connections=2, max_keepalive_connections=1)

_ARTIFACT_NAME = re.compile(r"^alles-backup-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.alles-backup$")
_TEMP_NAME = re.compile(r"^\.alles-upload-[0-9a-f]{32}\.partial$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$")
_HEX = frozenset("0123456789abcdefABCDEF")
_JOB_LOCK = threading.Lock()
_CONFIG_LOCK = threading.RLock()

_PROPFIND_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:getcontentlength/><d:getlastmodified/><d:getetag/></d:prop>
</d:propfind>
"""


class WebDAVError(RuntimeError):
    """A safe error that can be shown without exposing credentials or response bodies."""


class WebDAVBusyError(WebDAVError):
    """Raised when another WebDAV backup operation already owns the client lock."""


class _WebDAVTransportError(WebDAVError):
    """A request may have reached the server, but no final response was received."""


def _config_path() -> Path:
    return CONFIG_PATH or data_dir() / CONFIG_NAME


def _has_control(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)


def _check_percent_encoding(value: str) -> None:
    index = 0
    while index < len(value):
        if value[index] == "%":
            if (
                index + 2 >= len(value)
                or value[index + 1] not in _HEX
                or value[index + 2] not in _HEX
            ):
                raise WebDAVError("webdav collection url has invalid escaping")
            index += 3
            continue
        index += 1


def _decode_segment(raw: str) -> str:
    _check_percent_encoding(raw)
    try:
        decoded = unquote_to_bytes(raw).decode("utf-8")
    except UnicodeError as exc:
        raise WebDAVError("webdav collection url path is invalid") from exc
    if (
        decoded in {".", ".."}
        or not decoded
        or _has_control(decoded)
        or any(char in decoded for char in "/\\?%#")
    ):
        raise WebDAVError("webdav collection url path is unsafe")
    return decoded


def _normalized_path(path: str, *, collection: bool) -> str:
    if not path:
        return "/" if collection else ""
    if not path.startswith("/") or "\\" in path or _has_control(path):
        raise WebDAVError("webdav collection url path is unsafe")
    raw_segments = path.split("/")[1:]
    trailing = bool(raw_segments and raw_segments[-1] == "")
    if trailing:
        raw_segments.pop()
    if any(not segment for segment in raw_segments):
        raise WebDAVError("webdav collection url path is unsafe")
    decoded = [_decode_segment(segment) for segment in raw_segments]
    encoded = "/".join(quote(segment, safe="-._~!$&'()*+,;=:@") for segment in decoded)
    normalized = f"/{encoded}" if encoded else "/"
    if collection and not normalized.endswith("/"):
        normalized += "/"
    if not collection and trailing and normalized != "/":
        normalized += "/"
    return normalized


def _normalized_host(parsed) -> tuple[str, int]:
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise WebDAVError("webdav collection url host is invalid") from exc
    if not hostname or "%" in hostname or _has_control(hostname):
        raise WebDAVError("webdav collection url host is invalid")
    try:
        address = ipaddress.ip_address(hostname)
        host = address.compressed.lower()
        rendered = f"[{host}]" if address.version == 6 else host
    except ValueError:
        try:
            host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise WebDAVError("webdav collection url host is invalid") from exc
        labels = host.split(".")
        if (
            not host
            or len(host) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            raise WebDAVError("webdav collection url host is invalid")
        rendered = host
    if port is not None and not 1 <= port <= 65535:
        raise WebDAVError("webdav collection url port is invalid")
    effective_port = port or 443
    netloc = rendered if effective_port == 443 else f"{rendered}:{effective_port}"
    return netloc, effective_port


def normalize_collection_url(value: str) -> str:
    """Return one canonical HTTPS collection URL with a trailing slash."""
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_URL_BYTES:
        raise WebDAVError("webdav collection url is required")
    if value != value.strip() or _has_control(value):
        raise WebDAVError("webdav collection url is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise WebDAVError("webdav collection url is invalid") from exc
    if parsed.scheme.casefold() != "https":
        raise WebDAVError("webdav collection url must use https")
    if parsed.username is not None or parsed.password is not None:
        raise WebDAVError("webdav collection url cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise WebDAVError("webdav collection url cannot contain a query or fragment")
    netloc, _port = _normalized_host(parsed)
    path = _normalized_path(parsed.path, collection=True)
    return urlunsplit(("https", netloc, path, "", ""))


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    netloc, port = _normalized_host(parsed)
    host = netloc.rsplit(":", 1)[0] if not netloc.startswith("[") and ":" in netloc else netloc
    if host.startswith("["):
        host = host[1 : host.index("]")]
    return parsed.scheme.casefold(), host.casefold(), port


def _child_url(collection_url: str, name: str, *, temporary: bool = False) -> str:
    valid = _TEMP_NAME.fullmatch(name) if temporary else _is_artifact_name(name)
    if not valid:
        raise WebDAVError("webdav backup filename is invalid")
    base = normalize_collection_url(collection_url)
    parsed = urlsplit(base)
    child = urlunsplit((parsed.scheme, parsed.netloc, parsed.path + quote(name, safe=""), "", ""))
    if _origin(child) != _origin(base):
        raise WebDAVError("webdav backup address changed origin")
    return child


def generated_artifact_name(*, now: datetime | None = None, token: str | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise WebDAVError("webdav backup filename time is invalid")
    moment = moment.astimezone(UTC)
    suffix = token or uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[0-9a-f]{12}", suffix):
        raise WebDAVError("webdav backup filename token is invalid")
    return f"alles-backup-{moment.strftime('%Y%m%dT%H%M%SZ')}-{suffix}.alles-backup"


def _is_artifact_name(value: str) -> bool:
    if not isinstance(value, str) or not _ARTIFACT_NAME.fullmatch(value):
        return False
    try:
        datetime.strptime(value[13:29], "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def _config_path_is_safe() -> bool:
    path = _config_path()
    try:
        is_junction = getattr(path, "is_junction", None)
        if path.is_symlink() or bool(is_junction and is_junction()):
            return False
        return not path.exists() or path.is_file()
    except OSError:
        return False


def migrate_config() -> int:
    with _CONFIG_LOCK:
        if not _config_path_is_safe():
            raise WebDAVError("webdav backup configuration path is unsafe")
        return migrate_secret_config(_config_path(), PASSWORD_PURPOSE)


def _metadata(config: dict) -> dict:
    version = config.get("version", 1)
    if version != 1 or isinstance(version, bool):
        version = 1
    last_backup_at = config.get("last_backup_at", "")
    if not _is_timestamp(last_backup_at):
        last_backup_at = ""
    last_verified_at = config.get("last_verified_at", "")
    if not _is_timestamp(last_verified_at):
        last_verified_at = ""
    last_filename = config.get("last_filename", "")
    if last_filename != "" and not _is_artifact_name(last_filename):
        last_filename = ""
    last_bytes = config.get("last_bytes", 0)
    if (
        not isinstance(last_bytes, int)
        or isinstance(last_bytes, bool)
        or last_bytes < 0
        or last_bytes > MAX_ARTIFACT_BYTES
    ):
        last_bytes = 0
    last_sha256 = config.get("last_sha256", "")
    if not isinstance(last_sha256, str) or (last_sha256 and not _SHA256.fullmatch(last_sha256)):
        last_sha256 = ""
    return {
        "version": version,
        "last_backup_at": last_backup_at,
        "last_verified_at": last_verified_at,
        "last_filename": last_filename,
        "last_bytes": last_bytes,
        "last_sha256": last_sha256,
    }


def _is_timestamp(value) -> bool:
    if value == "":
        return True
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def load_config() -> dict:
    with _CONFIG_LOCK:
        migrate_config()
        stored = load_secret_config(_config_path(), PASSWORD_PURPOSE)
        return {
            "url": stored.get("url", "") if isinstance(stored.get("url", ""), str) else "",
            "username": (
                stored.get("username", "") if isinstance(stored.get("username", ""), str) else ""
            ),
            "password": (
                stored.get("password", "") if isinstance(stored.get("password", ""), str) else ""
            ),
            **_metadata(stored),
        }


def _clean_text(value, *, label: str, maximum: int, required: bool) -> str:
    if not isinstance(value, str):
        raise WebDAVError(f"webdav {label} is invalid")
    if required and not value:
        raise WebDAVError(f"webdav {label} is required")
    if len(value.encode("utf-8")) > maximum or _has_control(value):
        raise WebDAVError(f"webdav {label} is invalid")
    return value


def _validated_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise WebDAVError("webdav backup configuration is invalid")
    url = normalize_collection_url(config.get("url", ""))
    username = _clean_text(
        config.get("username", ""),
        label="username",
        maximum=MAX_USERNAME_BYTES,
        required=True,
    )
    password = _clean_text(
        config.get("password", ""),
        label="password",
        maximum=MAX_PASSWORD_BYTES,
        required=True,
    )
    return {"url": url, "username": username, "password": password, **_metadata(config)}


def save_config(config: dict, *, verified_at: str | None = None) -> dict:
    if not isinstance(config, dict):
        raise WebDAVError("webdav backup configuration is invalid")
    if config.get("url") == "":
        delete_config()
        return status()
    if not isinstance(config.get("url"), str):
        raise WebDAVError("webdav collection url is invalid")

    with _one_job(), _CONFIG_LOCK:
        current = load_config()
        candidate = dict(config)
        password = candidate.get("password", "")
        if isinstance(password, str) and password:
            from services.secretstore import is_sealed

            if is_sealed(password):
                raise WebDAVError("webdav password uses a reserved value prefix")
        if password == "":
            try:
                candidate_url = normalize_collection_url(candidate.get("url", ""))
            except WebDAVError:
                candidate_url = ""
            if (
                current.get("password")
                and candidate_url == current.get("url")
                and candidate.get("username") == current.get("username")
            ):
                candidate["password"] = current["password"]
        clean = _validated_config(candidate)
        same_connection = clean["url"] == current.get("url") and clean["username"] == current.get(
            "username"
        )
        metadata = _metadata(current if same_connection else {})
        if verified_at is not None:
            if not verified_at or not _is_timestamp(verified_at):
                raise WebDAVError("webdav verification time is invalid")
            metadata["last_verified_at"] = verified_at
        clean.update(metadata)
        save_secret_config(_config_path(), clean, PASSWORD_PURPOSE)
    return _masked_status(clean)


def delete_config() -> dict:
    from services.recovery_consistency import recovery_consistency_lock

    path = _config_path()
    with _one_job(), _CONFIG_LOCK, recovery_consistency_lock:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise WebDAVError("webdav backup configuration could not be removed") from exc
    return {
        "configured": False,
        "url": "",
        "username": "",
        "password_set": False,
        **_metadata({}),
    }


def _masked_status(config: dict) -> dict:
    return {
        "configured": bool(config.get("url") and config.get("username") and config.get("password")),
        "url": config.get("url", ""),
        "username": config.get("username", ""),
        "password_set": bool(config.get("password")),
        **_metadata(config),
    }


def status() -> dict:
    try:
        config = load_config()
        if config.get("url"):
            config = _validated_config(config)
        return _masked_status(config)
    except Exception:
        return {
            "configured": False,
            "url": "",
            "username": "",
            "password_set": False,
            **_metadata({}),
            "error": "webdav backup configuration could not be loaded",
        }


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _same_credentials(left: dict, right: dict) -> bool:
    return (
        left.get("url") == right.get("url")
        and left.get("username") == right.get("username")
        and isinstance(left.get("password"), str)
        and isinstance(right.get("password"), str)
        and hmac.compare_digest(left["password"], right["password"])
    )


def _record_status(config: dict, **updates) -> bool:
    """Update status metadata only if the saved credentials did not change mid-job."""
    with _CONFIG_LOCK:
        current = load_config()
        if not _same_credentials(current, config):
            return False
        clean = _validated_config(current)
        clean.update(_metadata({**current, **updates}))
        save_secret_config(_config_path(), clean, PASSWORD_PURPOSE)
        return True


def _new_client(config: dict) -> httpx.Client:
    return httpx.Client(
        auth=(config["username"], config["password"]),
        timeout=REQUEST_TIMEOUT,
        limits=CLIENT_LIMITS,
        follow_redirects=False,
        trust_env=False,
        verify=True,
    )


def _send(client: httpx.Client, method: str, url: str, *, headers=None, content=None):
    from services import net_guard

    try:
        net_guard.assert_safe_url(url)
    except Exception as exc:
        raise WebDAVError("webdav server address is blocked") from exc
    try:
        request = client.build_request(method, url, headers=headers or {}, content=content)
        response = client.send(request, stream=True)
    except WebDAVError:
        raise
    except httpx.TimeoutException as exc:
        raise _WebDAVTransportError("webdav request timed out") from exc
    except httpx.HTTPError as exc:
        raise _WebDAVTransportError("webdav request failed") from exc
    if 300 <= response.status_code < 400:
        response.close()
        raise WebDAVError("webdav redirects are not allowed")
    return response


def _require_status(response, accepted: set[int], action: str) -> None:
    if response.status_code in accepted:
        return
    code = response.status_code
    if code == 401:
        raise WebDAVError("webdav authentication failed")
    if code == 403:
        raise WebDAVError("webdav permission was denied")
    if code in {409, 412, 423}:
        raise WebDAVError(f"webdav {action} conflicted with remote state")
    raise WebDAVError(f"webdav {action} failed with status {code}")


@contextmanager
def _one_job():
    if not _JOB_LOCK.acquire(blocking=False):
        raise WebDAVBusyError("another webdav backup job is already running")
    try:
        yield
    finally:
        _JOB_LOCK.release()


def _active_config(config: dict | None = None) -> dict:
    try:
        return _validated_config(load_config() if config is None else config)
    except WebDAVError:
        raise
    except Exception as exc:
        raise WebDAVError("webdav credentials could not be loaded") from exc


def test_connection(config: dict | None = None) -> dict:
    with _one_job():
        clean = _active_config(config)
        with _new_client(clean) as client:
            response = _send(
                client,
                "PROPFIND",
                clean["url"],
                headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
                content=_PROPFIND_BODY,
            )
            with closing(response):
                _require_status(response, {200, 207}, "connection test")
        verified_at = _now()
        if config is None:
            _record_status(clean, last_verified_at=verified_at)
    return {"ok": True, "url": clean["url"], "verified_at": verified_at}


def _open_artifact(path: Path, maximum: int):
    source = Path(path).expanduser()
    if source.is_symlink():
        raise WebDAVError("encrypted backup cannot be a link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise WebDAVError("encrypted backup is not a regular file")
        if info.st_size <= len(MAGIC) or info.st_size > maximum:
            raise WebDAVError("encrypted backup size is invalid")
        handle = os.fdopen(fd, "rb")
        fd = None
        try:
            _read_header(handle, info.st_size, DEFAULT_LIMITS)
        except Exception:
            handle.close()
            raise WebDAVError("file is not an encrypted Alles backup")
        handle.seek(0)
        digest = hashlib.sha256()
        total = 0
        while chunk := handle.read(CHUNK_SIZE):
            total += len(chunk)
            if total > maximum:
                handle.close()
                raise WebDAVError("encrypted backup exceeds the configured size limit")
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if (
            total != info.st_size
            or after.st_size != info.st_size
            or after.st_mtime_ns != info.st_mtime_ns
        ):
            handle.close()
            raise WebDAVError("encrypted backup changed while it was being read")
        handle.seek(0)
        return handle, total, digest.hexdigest()
    except WebDAVError:
        raise
    except OSError as exc:
        raise WebDAVError("encrypted backup could not be read") from exc
    finally:
        if "fd" in locals() and fd is not None:
            os.close(fd)


def _file_stream(handle, expected_size: int):
    remaining = expected_size
    while remaining:
        chunk = handle.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise WebDAVError("encrypted backup changed during upload")
        remaining -= len(chunk)
        yield chunk
    if handle.read(1):
        raise WebDAVError("encrypted backup changed during upload")


def _content_length(response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    if len(raw) > 20 or not raw.isascii() or not raw.isdigit():
        raise WebDAVError("webdav response length is invalid")
    return int(raw)


def _response_chunks(response):
    """Yield a streamed response, while keeping MockTransport/preloaded responses testable."""
    if response.is_stream_consumed:
        yield response.content
        return
    yield from response.iter_raw()


def _hash_response(response, *, maximum: int, expected_size: int | None = None) -> tuple[int, str]:
    declared = _content_length(response)
    if declared is not None:
        if declared > maximum or (expected_size is not None and declared != expected_size):
            raise WebDAVError("webdav backup size verification failed")
    digest = hashlib.sha256()
    total = 0
    prefix = bytearray()
    try:
        for chunk in _response_chunks(response):
            total += len(chunk)
            if total > maximum or (expected_size is not None and total > expected_size):
                raise WebDAVError("webdav backup exceeds the configured size limit")
            if len(prefix) < len(MAGIC):
                prefix.extend(chunk[: len(MAGIC) - len(prefix)])
            digest.update(chunk)
    except WebDAVError:
        raise
    except httpx.HTTPError as exc:
        raise WebDAVError("webdav backup response failed") from exc
    if bytes(prefix) != MAGIC:
        raise WebDAVError("remote file is not an encrypted Alles backup")
    if expected_size is not None and total != expected_size:
        raise WebDAVError("webdav backup size verification failed")
    return total, digest.hexdigest()


def _delete_generated(
    client: httpx.Client,
    collection_url: str,
    name: str,
    *,
    temporary: bool,
) -> None:
    valid = _TEMP_NAME.fullmatch(name) if temporary else _is_artifact_name(name)
    if not valid:
        return
    try:
        url = _child_url(collection_url, name, temporary=temporary)
        response = _send(client, "DELETE", url)
        response.close()
    except Exception:
        pass


def _verify_remote_copy(
    client: httpx.Client,
    url: str,
    *,
    maximum: int,
    expected_size: int,
    expected_sha256: str,
) -> tuple[int, str] | None:
    """Reconcile a request whose response was lost without trusting server metadata."""
    try:
        response = _send(client, "GET", url, headers={"Accept-Encoding": "identity"})
        with closing(response):
            _require_status(response, {200}, "backup verification")
            size, checksum = _hash_response(
                response,
                maximum=maximum,
                expected_size=expected_size,
            )
        if not hmac.compare_digest(checksum, expected_sha256):
            return None
        return size, checksum
    except Exception:
        return None


def upload_artifact(
    artifact_path: Path,
    *,
    config: dict | None = None,
    maximum: int = MAX_ARTIFACT_BYTES,
) -> dict:
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or maximum > MAX_ARTIFACT_BYTES
    ):
        raise WebDAVError("webdav upload size limit is invalid")
    with _one_job():
        clean = _active_config(config)
        handle, size, checksum = _open_artifact(Path(artifact_path), maximum)
        final_name = generated_artifact_name()
        temp_name = f".alles-upload-{uuid.uuid4().hex}.partial"
        temp_url = _child_url(clean["url"], temp_name, temporary=True)
        final_url = _child_url(clean["url"], final_name)
        moved = False
        verified = False
        try:
            with _new_client(clean) as client:
                try:
                    response = _send(
                        client,
                        "PUT",
                        temp_url,
                        headers={
                            "If-None-Match": "*",
                            "Content-Type": "application/vnd.alles.backup",
                            "Content-Length": str(size),
                        },
                        content=_file_stream(handle, size),
                    )
                    with closing(response):
                        _require_status(response, {200, 201, 204}, "temporary upload")

                    from services import net_guard

                    try:
                        net_guard.assert_safe_url(final_url)
                    except Exception as exc:
                        raise WebDAVError("webdav server address is blocked") from exc
                    try:
                        response = _send(
                            client,
                            "MOVE",
                            temp_url,
                            headers={"Destination": final_url, "Overwrite": "F"},
                        )
                    except _WebDAVTransportError as exc:
                        reconciled = _verify_remote_copy(
                            client,
                            final_url,
                            maximum=maximum,
                            expected_size=size,
                            expected_sha256=checksum,
                        )
                        if reconciled is None:
                            raise WebDAVError(
                                "webdav backup move result is uncertain; "
                                "refresh remote backups before retrying"
                            ) from exc
                        remote_size, remote_checksum = reconciled
                        moved = True
                        verified = True
                    else:
                        with closing(response):
                            _require_status(response, {200, 201, 204}, "backup move")
                            moved = True

                    if not verified:
                        response = _send(
                            client,
                            "GET",
                            final_url,
                            headers={"Accept-Encoding": "identity"},
                        )
                        with closing(response):
                            _require_status(response, {200}, "backup verification")
                            remote_size, remote_checksum = _hash_response(
                                response,
                                maximum=maximum,
                                expected_size=size,
                            )
                        if not hmac.compare_digest(remote_checksum, checksum):
                            raise WebDAVError("webdav backup checksum verification failed")
                        verified = True
                finally:
                    if moved and not verified:
                        _delete_generated(
                            client,
                            clean["url"],
                            final_name,
                            temporary=False,
                        )
                    elif not moved:
                        _delete_generated(
                            client,
                            clean["url"],
                            temp_name,
                            temporary=True,
                        )
        finally:
            handle.close()
    completed_at = _now()
    status_warning = ""
    if config is None:
        try:
            recorded = _record_status(
                clean,
                last_backup_at=completed_at,
                last_verified_at=completed_at,
                last_filename=final_name,
                last_bytes=remote_size,
                last_sha256=remote_checksum,
            )
            if not recorded:
                status_warning = (
                    "backup uploaded and verified, but local webdav status could not be saved"
                )
        except Exception:
            status_warning = (
                "backup uploaded and verified, but local webdav status could not be saved"
            )
    return {
        "ok": True,
        "name": final_name,
        "size": remote_size,
        "sha256": remote_checksum,
        "completed_at": completed_at,
        "status_warning": status_warning,
    }


def _read_bounded(response, maximum: int) -> bytes:
    declared = _content_length(response)
    if declared is not None and declared > maximum:
        raise WebDAVError("webdav response is too large")
    chunks = []
    total = 0
    try:
        for chunk in _response_chunks(response):
            total += len(chunk)
            if total > maximum:
                raise WebDAVError("webdav response is too large")
            chunks.append(chunk)
    except WebDAVError:
        raise
    except httpx.HTTPError as exc:
        raise WebDAVError("webdav response failed") from exc
    return b"".join(chunks)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _successful_propstats(response_node):
    for child in response_node:
        if _local_name(child.tag) != "propstat":
            continue
        status_text = ""
        prop = None
        for item in child:
            name = _local_name(item.tag)
            if name == "status":
                status_text = (item.text or "").strip()
            elif name == "prop":
                prop = item
        if re.search(r"\s2[0-9]{2}(?:\s|$)", status_text) and prop is not None:
            yield prop


def _href_artifact_name(collection_url: str, href: str) -> str | None:
    if not href or len(href.encode("utf-8")) > MAX_URL_BYTES or _has_control(href):
        return None
    try:
        reference = urlsplit(href)
        if reference.query or reference.fragment:
            return None
        if reference.path:
            raw = reference.path.lstrip("/")
            raw_segments = raw.split("/")
            if any(segment and _decode_segment(segment) in {".", ".."} for segment in raw_segments):
                return None
        absolute = urljoin(collection_url, href)
        parsed = urlsplit(absolute)
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.scheme.casefold() != "https" or _origin(absolute) != _origin(collection_url):
            return None
        candidate_path = _normalized_path(parsed.path, collection=False)
        base_path = urlsplit(normalize_collection_url(collection_url)).path
        if not candidate_path.startswith(base_path):
            return None
        relative = candidate_path[len(base_path) :]
        if not relative or "/" in relative:
            return None
        name = _decode_segment(relative)
        if not _is_artifact_name(name):
            return None
        if _child_url(collection_url, name) != urlunsplit(
            ("https", urlsplit(normalize_collection_url(absolute)).netloc, candidate_path, "", "")
        ):
            return None
        return name
    except (ValueError, WebDAVError, UnicodeError):
        return None


def _parse_listing(collection_url: str, document: bytes) -> list[dict]:
    try:
        decoded = document.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WebDAVError("webdav listing xml encoding is invalid") from exc
    lowered = decoded.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise WebDAVError("webdav listing xml is unsafe")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise WebDAVError("webdav listing xml is invalid") from exc
    found: dict[str, dict] = {}
    for response_node in root.iter():
        if _local_name(response_node.tag) != "response":
            continue
        href = ""
        for child in response_node:
            if _local_name(child.tag) == "href":
                href = (child.text or "").strip()
                break
        name = _href_artifact_name(collection_url, href)
        if not name:
            continue
        item = {"name": name, "size": None, "modified": "", "etag": ""}
        for prop in _successful_propstats(response_node):
            for value in prop:
                key = _local_name(value.tag)
                text = (value.text or "").strip()
                if key == "getcontentlength" and text.isascii() and text.isdigit():
                    size = int(text)
                    if 0 <= size <= MAX_ARTIFACT_BYTES:
                        item["size"] = size
                elif key == "getlastmodified" and len(text) <= 256 and not _has_control(text):
                    item["modified"] = text
                elif key == "getetag" and len(text) <= 512 and not _has_control(text):
                    item["etag"] = text
        found[name] = item
        if len(found) > MAX_LISTED_ARTIFACTS:
            raise WebDAVError("webdav listing contains too many backups")
    return sorted(found.values(), key=lambda item: item["name"], reverse=True)


def list_artifacts(*, config: dict | None = None) -> list[dict]:
    with _one_job():
        clean = _active_config(config)
        with _new_client(clean) as client:
            response = _send(
                client,
                "PROPFIND",
                clean["url"],
                headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
                content=_PROPFIND_BODY,
            )
            with closing(response):
                _require_status(response, {207}, "backup listing")
                document = _read_bounded(response, MAX_LISTING_BYTES)
    return _parse_listing(clean["url"], document)


def _download_response(
    response,
    temp: Path,
    *,
    maximum: int,
    expected_size: int | None,
) -> tuple[int, str]:
    declared = _content_length(response)
    if declared is not None:
        if declared > maximum or (expected_size is not None and declared != expected_size):
            raise WebDAVError("webdav backup size verification failed")
    digest = hashlib.sha256()
    total = 0
    prefix = bytearray()
    try:
        with temp.open("xb") as handle:
            for chunk in _response_chunks(response):
                total += len(chunk)
                if total > maximum or (expected_size is not None and total > expected_size):
                    raise WebDAVError("webdav backup exceeds the configured size limit")
                if len(prefix) < len(MAGIC):
                    prefix.extend(chunk[: len(MAGIC) - len(prefix)])
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
    except WebDAVError:
        raise
    except (OSError, httpx.HTTPError) as exc:
        raise WebDAVError("webdav backup could not be downloaded") from exc
    if bytes(prefix) != MAGIC:
        raise WebDAVError("remote file is not an encrypted Alles backup")
    if expected_size is not None and total != expected_size:
        raise WebDAVError("webdav backup size verification failed")
    try:
        with temp.open("rb") as handle:
            _read_header(handle, total, DEFAULT_LIMITS)
    except Exception as exc:
        raise WebDAVError("remote file is not a valid encrypted Alles backup") from exc
    return total, digest.hexdigest()


def download_artifact(
    name: str,
    destination: Path,
    *,
    config: dict | None = None,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    maximum: int = MAX_ARTIFACT_BYTES,
) -> dict:
    if not _is_artifact_name(name or ""):
        raise WebDAVError("webdav backup filename is invalid")
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or maximum > MAX_ARTIFACT_BYTES
    ):
        raise WebDAVError("webdav download size limit is invalid")
    if expected_size is not None and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size <= 0
        or expected_size > maximum
    ):
        raise WebDAVError("webdav expected backup size is invalid")
    if expected_sha256 is not None and not _SHA256.fullmatch(expected_sha256):
        raise WebDAVError("webdav expected backup checksum is invalid")
    output = Path(destination).expanduser()
    if output.is_symlink():
        raise WebDAVError("webdav download destination cannot be a link")
    try:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise WebDAVError("webdav download destination could not be prepared") from exc
    temp = output.parent / f".{output.name}.{uuid.uuid4().hex}.partial"
    try:
        with _one_job():
            clean = _active_config(config)
            url = _child_url(clean["url"], name)
            with _new_client(clean) as client:
                response = _send(
                    client,
                    "GET",
                    url,
                    headers={"Accept-Encoding": "identity"},
                )
                with closing(response):
                    _require_status(response, {200}, "backup download")
                    size, checksum = _download_response(
                        response,
                        temp,
                        maximum=maximum,
                        expected_size=expected_size,
                    )
        if expected_sha256 is not None and not hmac.compare_digest(checksum, expected_sha256):
            raise WebDAVError("webdav backup checksum verification failed")
        os.replace(temp, output)
    except WebDAVError:
        temp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise WebDAVError("webdav backup could not be stored") from exc
    return {"ok": True, "name": name, "path": str(output), "size": size, "sha256": checksum}
