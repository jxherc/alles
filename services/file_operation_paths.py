"""path validation and canonical remote identities shared by Files operations.

claims and their lifecycle stay with file_operations; these functions only
normalize names and backend identities and have no persistence side effects.
"""

from __future__ import annotations

import ipaddress
import unicodedata
from urllib.parse import unquote, urlsplit

from services import storage_locations


class FileOperationError(RuntimeError):
    pass


def normalize_item_path(value: str) -> str:
    try:
        path = storage_locations.normalize_path(value)
    except ValueError as exc:
        raise FileOperationError(str(exc)) from exc
    if not path:
        raise FileOperationError("path required")
    return path


def _canonical_remote_claim_path(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        for part in unicodedata.normalize("NFC", str(value or "")).split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
    return "/".join(parts)


def _webdav_source_claim_identity(location, path: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(str(location.endpoint or "").strip())
        scheme = parsed.scheme.casefold()
        raw_host = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(raw_host)
            host = address.compressed.casefold()
            rendered_host = f"[{host}]" if address.version == 6 else host
        except ValueError:
            host = raw_host.encode("idna").decode("ascii").removesuffix(".").casefold()
            rendered_host = host
        port = parsed.port
        if port is None:
            port = {"http": 80, "https": 443}.get(scheme)
        endpoint_path = unquote(parsed.path, errors="strict").replace("\\", "/")
    except (UnicodeError, ValueError) as exc:
        raise FileOperationError("webdav source claim identity is invalid") from exc
    if scheme not in {"http", "https"} or not host or port is None or not 1 <= port <= 65535:
        raise FileOperationError("webdav source claim identity is invalid")
    scope = f"webdav:{scheme}://{rendered_host}:{port}"
    effective_path = _canonical_remote_claim_path(
        endpoint_path,
        str(location.prefix or ""),
        path,
    )
    return scope, effective_path


def _s3_source_claim_identity(location, path: str) -> tuple[str, str]:
    from services import s3_backup

    try:
        endpoint = s3_backup.normalize_endpoint(str(location.endpoint or ""))
        bucket = s3_backup._clean_bucket(str(location.bucket or ""))
    except s3_backup.S3Error as exc:
        raise FileOperationError("s3 source claim identity is invalid") from exc
    scope = f"s3:{endpoint}/{bucket}"
    effective_path = _canonical_remote_claim_path(str(location.prefix or ""), path)
    return scope, effective_path
