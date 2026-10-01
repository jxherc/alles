"""Fail-closed WebDAV transport for browsable Files storage locations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree as ET

from core.settings import data_dir
from services import internal_paths, storage_locations

MAX_LISTING_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
CLIENT_FACTORY = None

PROPFIND_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/>
<d:getlastmodified/><d:getetag/></d:prop></d:propfind>"""


class WebDAVLocationError(RuntimeError):
    pass


class WebDAVNotFoundError(WebDAVLocationError):
    pass


class WebDAVConflictError(WebDAVLocationError):
    def __init__(self, conflict_path: Path):
        self.conflict_path = conflict_path
        super().__init__(f"remote file changed; preserved at {conflict_path.name}")


def _credentials(row) -> dict:
    try:
        value = json.loads(row.secret or "{}")
    except (TypeError, ValueError) as exc:
        raise WebDAVLocationError("webdav credentials are invalid") from exc
    if not isinstance(value, dict):
        raise WebDAVLocationError("webdav credentials are invalid")
    username = value.get("username", "")
    password = value.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise WebDAVLocationError("webdav credentials are invalid")
    return {"username": username, "password": password}


def _client(row):
    credentials = _credentials(row)
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY(row, credentials)
    return httpx.Client(
        auth=(credentials["username"], credentials["password"]),
        timeout=TIMEOUT,
        follow_redirects=False,
        trust_env=False,
        verify=True,
    )


def _base(row) -> str:
    endpoint = str(row.endpoint or "").strip()
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise WebDAVLocationError("webdav endpoint is invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise WebDAVLocationError("webdav endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WebDAVLocationError("webdav endpoint is invalid")
    try:
        prefix = storage_locations.normalize_path(str(getattr(row, "prefix", "") or ""))
    except ValueError as exc:
        raise WebDAVLocationError("webdav prefix is invalid") from exc
    encoded_prefix = "/".join(quote(part, safe="-._~") for part in prefix.split("/") if part)
    path = parsed.path.rstrip("/") + "/"
    if encoded_prefix:
        path += encoded_prefix + "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _url(row, path: str = "", *, collection: bool = False) -> str:
    normalized = storage_locations.normalize_path(path)
    encoded = "/".join(quote(part, safe="-._~") for part in normalized.split("/") if part)
    base = _base(row)
    result = base + encoded
    if collection and not result.endswith("/"):
        result += "/"
    return result


def _same_origin(left: str, right: str) -> bool:
    def canonical_origin(value: str):
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        try:
            port = parsed.port
        except ValueError:
            return None
        if port is None:
            port = {"http": 80, "https": 443}.get(scheme)
        hostname = parsed.hostname.casefold() if parsed.hostname else None
        return scheme, hostname, port

    origin = canonical_origin(left)
    return origin is not None and origin == canonical_origin(right)


def _send(client, method: str, url: str, **kwargs):
    from services import net_guard

    try:
        requested = urlsplit(url)
        if requested.scheme == "http" and requested.hostname in {"127.0.0.1", "localhost", "::1"}:
            parsed, addresses = net_guard.resolve_loopback_url(url)
        else:
            parsed, addresses = net_guard.resolve_safe_url(url)
    except Exception as exc:
        raise WebDAVLocationError("webdav server address is blocked") from exc
    source_host = parsed.hostname or ""
    try:
        ascii_host = source_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise WebDAVLocationError("webdav server address is blocked") from exc
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if parsed.port:
        host_header = f"{host_header}:{parsed.port}"
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["host"] = host_header
    content_factory = kwargs.pop("content_factory", None)
    content = kwargs.pop("content", None)
    last_error = None
    for address in addresses:
        request_kwargs = dict(kwargs)
        if content_factory is not None:
            request_kwargs["content"] = content_factory()
        elif content is not None:
            request_kwargs["content"] = content
        request = client.build_request(
            method,
            net_guard._bound_url(parsed, address),
            headers=headers,
            extensions={"sni_hostname": ascii_host.encode("ascii")},
            **request_kwargs,
        )
        try:
            response = client.send(request, stream=True)
            break
        except httpx.TransportError as exc:
            last_error = exc
    else:
        if isinstance(last_error, httpx.TimeoutException):
            raise WebDAVLocationError("webdav request timed out") from last_error
        raise WebDAVLocationError("webdav request failed") from last_error
    if 300 <= response.status_code < 400:
        response.close()
        raise WebDAVLocationError("webdav redirects are not allowed")
    return response


def _require(response, accepted: set[int], action: str) -> None:
    if response.status_code in accepted:
        return
    if response.status_code == 404:
        raise WebDAVNotFoundError(f"webdav {action} failed with status 404")
    if response.status_code in {401, 403}:
        raise WebDAVLocationError("webdav authentication or permission check failed")
    if response.status_code in {409, 412, 423}:
        raise WebDAVLocationError(f"webdav {action} conflicted with remote state")
    if response.status_code == 507:
        raise WebDAVLocationError("webdav storage is full")
    raise WebDAVLocationError(f"webdav {action} failed with status {response.status_code}")


def _bounded(response, maximum: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > maximum:
        raise WebDAVLocationError("webdav response is too large")
    body = bytearray()
    for chunk in response.iter_bytes(CHUNK_SIZE):
        body.extend(chunk)
        if len(body) > maximum:
            raise WebDAVLocationError("webdav response is too large")
    return bytes(body)


def _partial_paths(target: Path) -> tuple[Path, Path]:
    partial = internal_paths.artifact_sibling(target, "download", suffix=".partial")
    identity = internal_paths.artifact_sibling(target, "download", suffix=".json")
    return partial, identity


def _discard_partial(partial: Path, identity_path: Path) -> None:
    partial.unlink(missing_ok=True)
    identity_path.unlink(missing_ok=True)


def _load_partial_identity(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_chunks(path: Path):
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            yield chunk


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_listing(
    row,
    document: bytes,
    requested_path: str,
    *,
    include_requested: bool = False,
) -> list[dict]:
    try:
        decoded = document.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WebDAVLocationError("webdav listing encoding is invalid") from exc
    lowered = decoded.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise WebDAVLocationError("webdav listing is unsafe")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise WebDAVLocationError("webdav listing is invalid") from exc
    base = _base(row)
    base_path = urlsplit(base).path
    requested = storage_locations.normalize_path(requested_path)
    found = {}
    for response_node in root.iter():
        if _local_name(response_node.tag) != "response":
            continue
        href = next(
            (
                (child.text or "").strip()
                for child in response_node
                if _local_name(child.tag) == "href"
            ),
            "",
        )
        absolute = urljoin(base, href)
        if not href or not _same_origin(base, absolute):
            continue
        remote_path = unquote(urlsplit(absolute).path)
        if not remote_path.startswith(unquote(base_path)):
            continue
        try:
            relative = storage_locations.normalize_path(remote_path[len(unquote(base_path)) :])
        except ValueError:
            continue
        if relative == requested and not include_requested:
            continue
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        if relative != requested and parent != requested:
            continue
        item = {
            "name": relative.rsplit("/", 1)[-1],
            "path": relative,
            "normalized_path": relative,
            "type": "file",
            "size": None,
            "mtime": "",
            "etag": "",
        }
        for propstat in response_node:
            if _local_name(propstat.tag) != "propstat":
                continue
            status = next(
                ((child.text or "") for child in propstat if _local_name(child.tag) == "status"),
                "",
            )
            if not re.search(r"\s2\d\d(?:\s|$)", status):
                continue
            prop = next((child for child in propstat if _local_name(child.tag) == "prop"), None)
            if prop is None:
                continue
            for value in prop:
                name = _local_name(value.tag)
                text = (value.text or "").strip()
                if name == "resourcetype" and any(
                    _local_name(child.tag) == "collection" for child in value
                ):
                    item["type"] = "dir"
                elif name == "getcontentlength" and text.isdigit():
                    item["size"] = int(text)
                elif name == "getlastmodified":
                    item["mtime"] = text[:256]
                elif name == "getetag":
                    item["etag"] = text[:512]
        if item["type"] == "dir" and item["size"] is None:
            item["size"] = 0
        found[relative] = item
    return sorted(found.values(), key=lambda item: (item["type"] != "dir", item["name"].lower()))


def capabilities(row) -> dict:
    with _client(row) as client:
        options = _send(client, "OPTIONS", _base(row))
        with closing(options):
            _require(options, {200, 204}, "capability check")
            allow = {
                value.strip().upper()
                for value in options.headers.get("allow", "").split(",")
                if value.strip()
            }
            dav = options.headers.get("dav", "")
            ranges = options.headers.get("accept-ranges", "").lower() == "bytes"
        probe_recovered = _recover_etag_probe(client, row)
        listing = _send(
            client,
            "PROPFIND",
            _base(row),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=PROPFIND_BODY,
        )
        with closing(listing):
            _require(listing, {207}, "listing")
            items = _parse_listing(
                row,
                _bounded(listing, MAX_LISTING_BYTES),
                "",
                include_requested=True,
            )
        supports_etag = any(_is_strong_etag(item.get("etag")) for item in items)
        has_child = any(item.get("path") for item in items)
        if (
            row.access == "managed"
            and not supports_etag
            and not has_child
            and probe_recovered
            and {"PUT", "DELETE"}.issubset(allow)
        ):
            supports_etag = _probe_empty_collection_etags(client, row)
    return {
        "ok": True,
        "state": "ready",
        # OPTIONS on a collection only describes that collection. Child resources
        # can legally support PUT or DELETE even when the root omits those verbs.
        "writable": row.access == "managed",
        "supports_etag": supports_etag,
        "supports_ranges": ranges,
        "supports_copy": "COPY" in allow,
        "supports_move": "MOVE" in allow,
        "dav": dav[:128],
    }


def _is_strong_etag(value: object) -> bool:
    etag = str(value or "").strip()
    return len(etag) >= 2 and etag.startswith('"') and etag.endswith('"')


def _probe_journal_path(row) -> Path:
    identity = hashlib.sha256(f"{row.id}\0{_base(row)}".encode("utf-8")).hexdigest()
    return data_dir() / "webdav-probes" / f"{identity}.json"


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_probe_journal(row, *, path: str, marker: bytes) -> None:
    journal = _probe_journal_path(row)
    journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{journal.name}.", suffix=".tmp", dir=journal.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "endpoint": _base(row), "path": path, "marker": marker.hex()},
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, journal)
        _sync_directory(journal.parent)
    finally:
        temp.unlink(missing_ok=True)


def _clear_probe_journal(row) -> None:
    journal = _probe_journal_path(row)
    journal.unlink(missing_ok=True)
    if journal.parent.exists():
        _sync_directory(journal.parent)


def _read_probe_journal(row) -> tuple[str, bytes] | None:
    journal = _probe_journal_path(row)
    try:
        value = json.loads(journal.read_text("utf-8"))
        path = str(value["path"])
        marker = bytes.fromhex(str(value["marker"]))
    except FileNotFoundError:
        return None
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WebDAVLocationError("webdav capability probe recovery state is invalid") from exc
    if (
        value.get("version") != 1
        or value.get("endpoint") != _base(row)
        or not re.fullmatch(r"\.alles-etag-probe-[0-9a-f]{32}", path)
        or len(marker) != 32
    ):
        raise WebDAVLocationError("webdav capability probe recovery state is invalid")
    return path, marker


def _recover_etag_probe(client, row) -> bool:
    """Remove one journaled probe when its exact remote identity becomes provable."""
    pending = _read_probe_journal(row)
    if pending is None:
        return True
    path, marker = pending
    target = _url(row, path)
    response = _send(
        client,
        "PROPFIND",
        target,
        headers={"Depth": "0", "Content-Type": "application/xml"},
        content=PROPFIND_BODY,
    )
    with closing(response):
        if response.status_code == 404:
            _clear_probe_journal(row)
            return True
        if response.status_code != 207:
            return False
        items = _parse_listing(
            row,
            _bounded(response, MAX_LISTING_BYTES),
            path,
            include_requested=True,
        )
    etag = next((str(item.get("etag") or "") for item in items if item.get("path") == path), "")
    if not _is_strong_etag(etag):
        return False
    response = _send(client, "GET", target, headers={"If-Match": etag})
    with closing(response):
        if response.status_code in {404, 412}:
            _clear_probe_journal(row)
            return True
        if response.status_code != 200 or _bounded(response, len(marker) + 1) != marker:
            _clear_probe_journal(row)
            return True
    response = _send(client, "DELETE", target, headers={"If-Match": etag})
    with closing(response):
        if response.status_code not in {200, 204, 404, 412}:
            return False
    _clear_probe_journal(row)
    return True


def _probe_empty_collection_etags(client, row) -> bool:
    """Prove conditional writes on one owned temporary resource, then remove it."""
    path = f".alles-etag-probe-{uuid.uuid4().hex}"
    target = _url(row, path)
    marker = os.urandom(32)
    created = False
    etag = ""
    _write_probe_journal(row, path=path, marker=marker)
    try:
        response = _send(
            client,
            "PUT",
            target,
            headers={"Content-Length": str(len(marker)), "If-None-Match": "*"},
            content=marker,
        )
        with closing(response):
            if response.status_code != 201:
                _clear_probe_journal(row)
                return False
            created = True
            etag = response.headers.get("etag", "")[:512]
        response = _send(
            client,
            "PUT",
            target,
            headers={"Content-Length": "1", "If-None-Match": "*"},
            content=b"1",
        )
        with closing(response):
            if response.status_code != 412:
                return False
        if not _is_strong_etag(etag):
            response = _send(
                client,
                "PROPFIND",
                target,
                headers={"Depth": "0", "Content-Type": "application/xml"},
                content=PROPFIND_BODY,
            )
            with closing(response):
                if response.status_code != 207:
                    return False
                probe_items = _parse_listing(
                    row,
                    _bounded(response, MAX_LISTING_BYTES),
                    path,
                    include_requested=True,
                )
            etag = next(
                (str(item.get("etag") or "") for item in probe_items if item.get("path") == path),
                "",
            )
        if not _is_strong_etag(etag):
            return False
        response = _send(
            client,
            "PUT",
            target,
            headers={"Content-Length": "1", "If-Match": '"alles-invalid-etag"'},
            content=b"1",
        )
        with closing(response):
            return response.status_code == 412
    finally:
        if created and _is_strong_etag(etag):
            response = _send(client, "DELETE", target, headers={"If-Match": etag})
            with closing(response):
                if response.status_code not in {200, 204, 404, 412}:
                    raise WebDAVLocationError("webdav capability probe could not be removed")
            _clear_probe_journal(row)


def _mutation_capabilities(row, *, require_etag: bool = True) -> dict:
    if row.access != "managed":
        raise WebDAVLocationError("webdav server does not allow managed writes")
    if require_etag:
        supported = capabilities(row)
        if not supported.get("supports_etag"):
            raise WebDAVLocationError(
                "managed WebDAV writes require stable ETags before remote data is changed"
            )
    return {"writable": True, "requires_target_etag": require_etag}


def listdir(row, path: str = "") -> dict:
    normalized = storage_locations.normalize_path(path)
    with _client(row) as client:
        response = _send(
            client,
            "PROPFIND",
            _url(row, normalized, collection=True),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=PROPFIND_BODY,
        )
        with closing(response):
            _require(response, {207}, "listing")
            items = _parse_listing(row, _bounded(response, MAX_LISTING_BYTES), normalized)
    return {"path": normalized, "items": items}


def read_prefix(
    row,
    path: str,
    limit: int,
    *,
    expected_etag: str,
    expected_size: int,
) -> dict:
    """Read an identity-bound prefix without relaxing full-download checks."""
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise WebDAVLocationError("path required")
    if not expected_etag:
        raise WebDAVLocationError("a verified ETag is required before previewing")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or not 0 <= expected_size <= MAX_FILE_BYTES
    ):
        raise WebDAVLocationError("webdav file size is invalid")
    if not isinstance(limit, int) or limit <= 0:
        raise WebDAVLocationError("webdav preview limit is invalid")
    if expected_size == 0:
        headers = {"Accept-Encoding": "identity", "If-Match": expected_etag}
        with _client(row) as client:
            response = _send(client, "GET", _url(row, normalized), headers=headers)
            with closing(response):
                if response.status_code == 412:
                    raise WebDAVLocationError("remote file changed")
                _require(response, {200}, "empty preview")
                etag = response.headers.get("etag", "")[:512]
                if etag != expected_etag:
                    raise WebDAVLocationError("remote file changed")
                declared = response.headers.get("content-length", "")
                if declared and (not declared.isdigit() or int(declared) != 0):
                    raise WebDAVLocationError("webdav empty preview did not match")
                if _bounded(response, 0):
                    raise WebDAVLocationError("webdav empty preview did not match")
        return {"content": b"", "size": 0, "etag": etag}
    prefix_size = min(limit, expected_size)
    headers = {
        "Accept-Encoding": "identity",
        "If-Match": expected_etag,
        "Range": f"bytes=0-{prefix_size - 1}",
    }
    with _client(row) as client:
        response = _send(client, "GET", _url(row, normalized), headers=headers)
        with closing(response):
            if response.status_code == 200:
                raise WebDAVLocationError("webdav server ignored the preview range")
            if response.status_code == 412:
                raise WebDAVLocationError("remote file changed")
            _require(response, {206}, "preview")
            etag = response.headers.get("etag", "")[:512]
            if etag != expected_etag:
                raise WebDAVLocationError("remote file changed")
            match = re.fullmatch(
                r"bytes\s+(\d+)-(\d+)/(\d+)",
                response.headers.get("content-range", "").strip(),
                flags=re.IGNORECASE,
            )
            if match is None:
                raise WebDAVLocationError("webdav preview range is invalid")
            range_start, range_end, range_total = (int(value) for value in match.groups())
            if range_start != 0 or range_end != prefix_size - 1 or range_total != expected_size:
                raise WebDAVLocationError("webdav preview range did not match")
            declared = response.headers.get("content-length", "")
            if declared and (not declared.isdigit() or int(declared) != prefix_size):
                raise WebDAVLocationError("webdav preview range did not match")
            content = _bounded(response, prefix_size)
            if len(content) != prefix_size:
                raise WebDAVLocationError("webdav preview range did not match")
    return {"content": content, "size": expected_size, "etag": etag}


def download(
    row,
    path: str,
    destination: Path,
    *,
    expected_etag: str = "",
    expected_size: int | None = None,
    resume: bool = False,
    max_bytes: int | None = None,
) -> dict:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise WebDAVLocationError("path required")
    if expected_size is not None:
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or not 0 <= expected_size <= MAX_FILE_BYTES
        ):
            raise WebDAVLocationError("webdav file size is invalid")
    if max_bytes is not None and expected_size is not None and expected_size > max_bytes:
        raise WebDAVLocationError("webdav file is too large")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial, identity_path = _partial_paths(target)
    if not resume:
        _discard_partial(partial, identity_path)
    start = 0
    if resume and partial.is_file():
        identity = _load_partial_identity(identity_path)
        safe_identity = (
            bool(expected_etag)
            and identity.get("etag") == expected_etag
            and (expected_size is None or identity.get("size") == expected_size)
        )
        partial_size = partial.stat().st_size
        if safe_identity and expected_size is not None and partial_size == expected_size:
            # The identity is written before streaming starts, so size alone cannot
            # prove a crash-surviving partial contains the complete remote object.
            # Re-read the ETag-bound object instead of promoting unverified bytes.
            _discard_partial(partial, identity_path)
        elif (
            not safe_identity
            or partial_size == 0
            or (expected_size is not None and partial_size > expected_size)
        ):
            _discard_partial(partial, identity_path)
        elif capabilities(row).get("supports_ranges"):
            start = partial_size
        else:
            _discard_partial(partial, identity_path)
    headers = {"Accept-Encoding": "identity"}
    if start:
        headers["Range"] = f"bytes={start}-"
    if expected_etag:
        headers["If-Match"] = expected_etag
    digest = hashlib.sha256()
    if start:
        with partial.open("rb") as prior:
            for chunk in iter(lambda: prior.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    with _client(row) as client:
        response = _send(client, "GET", _url(row, normalized), headers=headers)
        if start and response.status_code != 206:
            response.close()
            start = 0
            digest = hashlib.sha256()
            _discard_partial(partial, identity_path)
            response = _send(
                client,
                "GET",
                _url(row, normalized),
                headers={key: value for key, value in headers.items() if key != "Range"},
            )
        with closing(response):
            _require(response, {200, 206}, "download")
            etag = response.headers.get("etag", "")[:512]
            if expected_etag and etag != expected_etag:
                raise WebDAVLocationError("remote file changed")
            declared_raw = response.headers.get("content-length", "")
            declared = int(declared_raw) if declared_raw.isdigit() else None
            if response.status_code == 206:
                match = re.fullmatch(
                    r"bytes\s+(\d+)-(\d+)/(\d+)",
                    response.headers.get("content-range", "").strip(),
                    flags=re.IGNORECASE,
                )
                if not match:
                    raise WebDAVLocationError("webdav download range is invalid")
                range_start, range_end, range_total = (int(value) for value in match.groups())
                if (
                    range_start != start
                    or range_end < range_start
                    or range_end + 1 != range_total
                    or (declared is not None and declared != range_end - range_start + 1)
                    or (expected_size is not None and range_total != expected_size)
                ):
                    raise WebDAVLocationError("webdav download range did not match")
                expected_size = range_total
            elif declared is not None and expected_size is not None and declared != expected_size:
                raise WebDAVLocationError("webdav download size did not match")
            identity_path.write_text(
                json.dumps(
                    {"etag": etag or expected_etag, "size": expected_size},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            mode = "ab" if start else "xb"
            total = start
            try:
                with partial.open(mode) as handle:
                    for chunk in response.iter_bytes(CHUNK_SIZE):
                        total += len(chunk)
                        if total > MAX_FILE_BYTES or (max_bytes is not None and total > max_bytes):
                            raise WebDAVLocationError("webdav file is too large")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if not resume:
                    _discard_partial(partial, identity_path)
                raise
    if expected_size is not None and total != expected_size:
        if not resume:
            _discard_partial(partial, identity_path)
        raise WebDAVLocationError("webdav download size did not match")
    partial.replace(target)
    identity_path.unlink(missing_ok=True)
    return {"size": total, "checksum": digest.hexdigest(), "etag": etag or expected_etag}


def _conflict_path(row, path: str) -> Path:
    root = data_dir() / "storage-conflicts" / row.id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return internal_paths.bounded_named_child(
        root,
        Path(path).name or "remote-file",
        prefix=uuid.uuid4().hex[:12],
    )


def _preserve_incoming_conflict(incoming: Path, conflict: Path, checksum: str) -> None:
    digest = hashlib.sha256()
    try:
        with incoming.open("rb") as source, conflict.open("xb") as destination:
            for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if digest.hexdigest() != checksum:
            raise WebDAVLocationError("incoming conflict copy could not be verified")
    except Exception:
        conflict.unlink(missing_ok=True)
        raise


def upload(row, path: str, source: Path, *, expected_etag: str = "") -> dict:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise WebDAVLocationError("path required")
    if row.access != "managed":
        raise WebDAVLocationError("storage location is read-only")
    _mutation_capabilities(row, require_etag=True)
    incoming = Path(source)
    if incoming.is_symlink() or not incoming.is_file():
        raise WebDAVLocationError("upload source is invalid")
    size = incoming.stat().st_size
    if size > MAX_FILE_BYTES:
        raise WebDAVLocationError("webdav file is too large")
    digest = hashlib.sha256()
    with incoming.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    checksum = digest.hexdigest()
    headers = {
        "Content-Length": str(size),
        "If-Match" if expected_etag else "If-None-Match": expected_etag or "*",
    }
    with _client(row) as client:
        response = _send(
            client,
            "PUT",
            _url(row, normalized),
            headers=headers,
            content_factory=lambda: _file_chunks(incoming),
        )
        with closing(response):
            if response.status_code == 412:
                conflict = _conflict_path(row, normalized)
                try:
                    _preserve_incoming_conflict(incoming, conflict, checksum)
                except Exception:
                    conflict.unlink(missing_ok=True)
                    raise WebDAVLocationError("incoming file changed and could not be preserved")
                raise WebDAVConflictError(conflict)
            _require(response, {200, 204} if expected_etag else {201}, "upload")
            etag = response.headers.get("etag", "")[:512]
    verify_root = data_dir() / "storage-conflicts" / row.id
    verify_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    verify = internal_paths.bounded_named_child(
        verify_root,
        "verify",
        prefix=uuid.uuid4().hex[:12],
    )
    try:
        remote = download(
            row,
            normalized,
            verify,
            expected_etag=etag,
            expected_size=size,
        )
        if remote["size"] != size or remote["checksum"] != checksum:
            raise WebDAVLocationError("uploaded file could not be verified")
        etag = etag or remote["etag"]
    finally:
        verify.unlink(missing_ok=True)
    return {"size": size, "checksum": checksum, "etag": etag}


def mkdir(row, path: str) -> dict:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise WebDAVLocationError("path required")
    if row.access != "managed":
        raise WebDAVLocationError("storage location is read-only")
    _mutation_capabilities(row, require_etag=False)
    with _client(row) as client:
        response = _send(client, "MKCOL", _url(row, normalized, collection=True))
        with closing(response):
            _require(response, {201, 204}, "create folder")
    return {"path": normalized, "type": "dir"}


def delete(row, path: str, *, expected_etag: str = "") -> None:
    normalized = storage_locations.normalize_path(path)
    if not normalized:
        raise WebDAVLocationError("path required")
    if row.access != "managed":
        raise WebDAVLocationError("storage location is read-only")
    if not expected_etag:
        raise WebDAVLocationError("a verified ETag is required before deleting")
    _mutation_capabilities(row, require_etag=False)
    headers = {"If-Match": expected_etag}
    with _client(row) as client:
        response = _send(client, "DELETE", _url(row, normalized), headers=headers)
        with closing(response):
            _require(response, {200, 204}, "delete")


def copy_or_move(
    row,
    source_path: str,
    destination_path: str,
    *,
    move: bool = False,
    expected_etag: str = "",
) -> dict:
    source = storage_locations.normalize_path(source_path)
    destination = storage_locations.normalize_path(destination_path)
    if not source or not destination:
        raise WebDAVLocationError("source and destination paths are required")
    if row.access != "managed":
        raise WebDAVLocationError("storage location is read-only")
    if move and not expected_etag:
        raise WebDAVLocationError("a verified ETag is required before moving")
    _mutation_capabilities(row, require_etag=False)
    method = "MOVE" if move else "COPY"
    headers = {
        "Destination": _url(row, destination),
        "Overwrite": "F",
    }
    if move or expected_etag:
        headers["If-Match"] = expected_etag
    with _client(row) as client:
        response = _send(client, method, _url(row, source), headers=headers)
        with closing(response):
            _require(response, {201, 204}, method.lower())
    return {"path": destination, "source": source, "moved": move}
