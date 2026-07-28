"""Small, fail-closed S3-compatible client for encrypted Alles backups."""

from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import stat
import threading
import unicodedata
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, quote_from_bytes, unquote_to_bytes, urlencode, urlsplit

import httpx
from defusedxml import ElementTree as ET

from core.settings import data_dir
from services.backup_recovery import CHUNK_SIZE, DEFAULT_LIMITS
from services.config_secrets import load_secret_config, migrate_secret_config, save_secret_config
from services.recovery_crypto import HEADER_MAX_BYTES, MAGIC, _read_header

CONFIG_PATH: Path | None = None
CONFIG_NAME = "s3_backup.json"
CREDENTIALS_PURPOSE = "backup.s3.credentials"

# S3 single-request PUT and CopyObject are limited to 5 GB. Multipart upload is deliberately
# outside this first, fail-closed implementation.
MAX_ARTIFACT_BYTES = 5_000_000_000
MAX_LISTING_BYTES = 2 * 1024 * 1024
MAX_LISTED_ARTIFACTS = 10_000
MAX_LISTING_PAGES = 32
MAX_COPY_RESPONSE_BYTES = 128 * 1024
MAX_URL_BYTES = 4_096
MAX_CREDENTIALS_BYTES = 8 * 1024
MAX_PREFIX_BYTES = 900

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
CLIENT_LIMITS = httpx.Limits(max_connections=2, max_keepalive_connections=1)

_ARTIFACT_NAME = re.compile(r"^alles-backup-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.alles-backup$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REGION = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_PREFIX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._~/-]{0,1022}[A-Za-z0-9._~-])?$")
_ACCESS_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$")
_HEX = frozenset("0123456789abcdefABCDEF")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_HEADER_PREFIX_BYTES = len(MAGIC) + 4 + HEADER_MAX_BYTES
_LOCK = threading.RLock()


class S3Error(RuntimeError):
    """A fixed, credential-safe error suitable for a route response."""


class S3BusyError(S3Error):
    """Raised when another S3 config or backup operation owns the shared lock."""


class _S3TransportError(S3Error):
    """The request may have arrived, but no final response was received."""


def _config_path() -> Path:
    return CONFIG_PATH or data_dir() / CONFIG_NAME


def _has_control(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)


def _config_path_is_safe() -> bool:
    path = _config_path()
    try:
        is_junction = getattr(path, "is_junction", None)
        if path.is_symlink() or bool(is_junction and is_junction()):
            return False
        return not path.exists() or path.is_file()
    except OSError:
        return False


def _normalized_host(parsed) -> tuple[str, str, int, bool]:
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise S3Error("s3 endpoint host is invalid") from exc
    if not hostname or "%" in hostname or _has_control(hostname):
        raise S3Error("s3 endpoint host is invalid")
    literal = False
    try:
        address = ipaddress.ip_address(hostname)
        host = address.compressed.lower()
        rendered = f"[{host}]" if address.version == 6 else host
        literal = True
    except ValueError:
        try:
            host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise S3Error("s3 endpoint host is invalid") from exc
        labels = host.split(".")
        if (
            not host
            or len(host) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            raise S3Error("s3 endpoint host is invalid")
        rendered = host
    if port is not None and not 1 <= port <= 65535:
        raise S3Error("s3 endpoint port is invalid")
    effective_port = port or 443
    netloc = rendered if effective_port == 443 else f"{rendered}:{effective_port}"
    return host, netloc, effective_port, literal


def normalize_endpoint(value: str) -> str:
    """Return a canonical HTTPS S3 endpoint with no path, credentials, or query."""
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_URL_BYTES:
        raise S3Error("s3 endpoint is required")
    if value != value.strip() or _has_control(value):
        raise S3Error("s3 endpoint is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise S3Error("s3 endpoint is invalid") from exc
    if parsed.scheme.casefold() != "https":
        raise S3Error("s3 endpoint must use https")
    if parsed.username is not None or parsed.password is not None:
        raise S3Error("s3 endpoint cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise S3Error("s3 endpoint cannot contain a query or fragment")
    if parsed.path not in {"", "/"}:
        raise S3Error("s3 endpoint cannot contain a path")
    _host, netloc, _port, _literal = _normalized_host(parsed)
    return f"https://{netloc}"


def _clean_bucket(value) -> str:
    if not isinstance(value, str) or not _BUCKET.fullmatch(value):
        raise S3Error("s3 bucket is invalid")
    if ".." in value or ".-" in value or "-." in value:
        raise S3Error("s3 bucket is invalid")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise S3Error("s3 bucket is invalid")


def _clean_region(value) -> str:
    if not isinstance(value, str) or not _REGION.fullmatch(value):
        raise S3Error("s3 region is invalid")
    return value


def _clean_prefix(value) -> str:
    if value in {None, ""}:
        return ""
    if not isinstance(value, str) or not _PREFIX.fullmatch(value):
        raise S3Error("s3 prefix is invalid")
    if len(value.encode("utf-8")) > MAX_PREFIX_BYTES:
        raise S3Error("s3 prefix is invalid")
    if value.startswith("/") or value.endswith("/") or "//" in value:
        raise S3Error("s3 prefix is invalid")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise S3Error("s3 prefix is invalid")
    return value


def _clean_addressing(value) -> str:
    addressing = "path" if value in {None, ""} else value
    if addressing not in {"path", "virtual"}:
        raise S3Error("s3 addressing style is invalid")
    return addressing


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise S3Error("s3 credentials are invalid")
        result[key] = value
    return result


def _credentials_json(access_key_id: str, secret_access_key: str) -> str:
    if not isinstance(access_key_id, str) or not _ACCESS_KEY.fullmatch(access_key_id):
        raise S3Error("s3 credentials are invalid")
    if (
        not isinstance(secret_access_key, str)
        or not secret_access_key
        or len(secret_access_key.encode("utf-8")) > 1024
        or _has_control(secret_access_key)
    ):
        raise S3Error("s3 credentials are invalid")
    from services.secretstore import is_sealed

    if is_sealed(access_key_id) or is_sealed(secret_access_key):
        raise S3Error("s3 credentials use a reserved value prefix")
    return json.dumps(
        {"access_key_id": access_key_id, "secret_access_key": secret_access_key},
        separators=(",", ":"),
        sort_keys=True,
    )


def _parse_credentials(value) -> dict[str, str]:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_CREDENTIALS_BYTES
    ):
        raise S3Error("s3 credentials are invalid")
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_duplicate_keys)
    except S3Error:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise S3Error("s3 credentials are invalid") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"access_key_id", "secret_access_key"}:
        raise S3Error("s3 credentials are invalid")
    canonical = _credentials_json(parsed["access_key_id"], parsed["secret_access_key"])
    if not hmac.compare_digest(canonical, value):
        raise S3Error("s3 credentials are invalid")
    return parsed


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


def _is_artifact_name(value: str) -> bool:
    if not isinstance(value, str) or not _ARTIFACT_NAME.fullmatch(value):
        return False
    try:
        datetime.strptime(value[13:29], "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def generated_artifact_name(*, now: datetime | None = None, token: str | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise S3Error("s3 backup filename time is invalid")
    moment = moment.astimezone(UTC)
    suffix = token or uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[0-9a-f]{12}", suffix):
        raise S3Error("s3 backup filename token is invalid")
    return f"alles-backup-{moment.strftime('%Y%m%dT%H%M%SZ')}-{suffix}.alles-backup"


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
    if last_filename and not _is_artifact_name(last_filename):
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


def migrate_config() -> int:
    with _LOCK:
        if not _config_path_is_safe():
            raise S3Error("s3 backup configuration path is unsafe")
        try:
            return migrate_secret_config(_config_path(), CREDENTIALS_PURPOSE, field="credentials")
        except Exception as exc:
            raise S3Error("s3 backup configuration could not be migrated") from exc


def load_config() -> dict:
    with _LOCK:
        try:
            migrate_config()
            stored = load_secret_config(_config_path(), CREDENTIALS_PURPOSE, field="credentials")
        except S3Error:
            raise
        except Exception as exc:
            raise S3Error("s3 backup configuration could not be loaded") from exc
        return {
            "endpoint": stored.get("endpoint", "")
            if isinstance(stored.get("endpoint", ""), str)
            else "",
            "region": stored.get("region", "") if isinstance(stored.get("region", ""), str) else "",
            "bucket": stored.get("bucket", "") if isinstance(stored.get("bucket", ""), str) else "",
            "prefix": stored.get("prefix", "") if isinstance(stored.get("prefix", ""), str) else "",
            "addressing_style": stored.get("addressing_style", "path")
            if isinstance(stored.get("addressing_style", "path"), str)
            else "path",
            "credentials": stored.get("credentials", "")
            if isinstance(stored.get("credentials", ""), str)
            else "",
            **_metadata(stored),
        }


def _identity(config: dict) -> tuple[str, str, str, str, str]:
    return (
        normalize_endpoint(config.get("endpoint", "")),
        _clean_region(config.get("region", "")),
        _clean_bucket(config.get("bucket", "")),
        _clean_prefix(config.get("prefix", "")),
        _clean_addressing(config.get("addressing_style", "path")),
    )


def _validated_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise S3Error("s3 backup configuration is invalid")
    endpoint, region, bucket, prefix, addressing = _identity(config)
    parsed = urlsplit(endpoint)
    _host, _netloc, _port, literal = _normalized_host(parsed)
    if addressing == "virtual" and (literal or "." in bucket):
        raise S3Error("s3 virtual addressing requires a dns-safe bucket")
    credentials = config.get("credentials", "")
    _parse_credentials(credentials)
    return {
        "endpoint": endpoint,
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
        "addressing_style": addressing,
        "credentials": credentials,
        **_metadata(config),
    }


def config_candidate(
    public_fields: dict,
    *,
    access_key_id: str = "",
    secret_access_key: str = "",
    current: dict | None = None,
) -> dict:
    """Build an internal config while enforcing all-or-nothing credential reuse."""
    if not isinstance(public_fields, dict):
        raise S3Error("s3 backup configuration is invalid")
    public = {
        "endpoint": public_fields.get("endpoint", ""),
        "region": public_fields.get("region", ""),
        "bucket": public_fields.get("bucket", ""),
        "prefix": public_fields.get("prefix", ""),
        "addressing_style": public_fields.get("addressing_style", "path"),
    }
    candidate_identity = _identity(public)
    if not isinstance(access_key_id, str) or not isinstance(secret_access_key, str):
        raise S3Error("s3 credentials are invalid")
    if bool(access_key_id) != bool(secret_access_key):
        raise S3Error("s3 access key and secret key must be provided together")
    if access_key_id and secret_access_key:
        credentials = _credentials_json(access_key_id, secret_access_key)
    else:
        saved = load_config() if current is None else current
        try:
            same_identity = _identity(saved) == candidate_identity
        except S3Error:
            same_identity = False
        credentials = saved.get("credentials", "") if same_identity else ""
        if not credentials:
            raise S3Error("s3 credentials are required")
        _parse_credentials(credentials)
    return _validated_config({**public, "credentials": credentials})


def _same_connection(left: dict, right: dict) -> bool:
    try:
        same_identity = _identity(left) == _identity(right)
    except S3Error:
        return False
    left_secret = left.get("credentials", "")
    right_secret = right.get("credentials", "")
    return (
        same_identity
        and isinstance(left_secret, str)
        and isinstance(right_secret, str)
        and hmac.compare_digest(left_secret, right_secret)
    )


def _masked_status(config: dict) -> dict:
    return {
        "configured": bool(
            config.get("endpoint")
            and config.get("region")
            and config.get("bucket")
            and config.get("credentials")
        ),
        "endpoint": config.get("endpoint", ""),
        "region": config.get("region", ""),
        "bucket": config.get("bucket", ""),
        "prefix": config.get("prefix", ""),
        "addressing_style": config.get("addressing_style", "path"),
        "credentials_set": bool(config.get("credentials")),
        **_metadata(config),
    }


def save_config(config: dict, *, verified_at: str | None = None) -> dict:
    if not isinstance(config, dict):
        raise S3Error("s3 backup configuration is invalid")
    if config.get("endpoint") == "":
        return delete_config()
    with _one_job():
        current = load_config()
        credentials = config.get("credentials", "")
        from services.secretstore import is_sealed

        if isinstance(credentials, str) and is_sealed(credentials):
            raise S3Error("s3 credentials use a reserved value prefix")
        clean = _validated_config(config)
        metadata = _metadata(current if _same_connection(current, clean) else {})
        if verified_at is not None:
            if not verified_at or not _is_timestamp(verified_at):
                raise S3Error("s3 verification time is invalid")
            metadata["last_verified_at"] = verified_at
        clean.update(metadata)
        try:
            save_secret_config(_config_path(), clean, CREDENTIALS_PURPOSE, field="credentials")
        except Exception as exc:
            raise S3Error("s3 backup configuration could not be saved") from exc
    return _masked_status(clean)


def delete_config() -> dict:
    from services.recovery_consistency import recovery_consistency_lock

    path = _config_path()
    with _one_job(), recovery_consistency_lock:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise S3Error("s3 backup configuration could not be removed") from exc
    return {
        "configured": False,
        "endpoint": "",
        "region": "",
        "bucket": "",
        "prefix": "",
        "addressing_style": "path",
        "credentials_set": False,
        **_metadata({}),
    }


def status() -> dict:
    try:
        config = load_config()
        if config.get("endpoint"):
            config = _validated_config(config)
        return _masked_status(config)
    except Exception:
        return {
            "configured": False,
            "endpoint": "",
            "region": "",
            "bucket": "",
            "prefix": "",
            "addressing_style": "path",
            "credentials_set": False,
            **_metadata({}),
            "error": "s3 backup configuration could not be loaded",
        }


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_status(config: dict, **updates) -> bool:
    with _LOCK:
        current = load_config()
        if not _same_connection(current, config):
            return False
        clean = _validated_config(current)
        clean.update(_metadata({**current, **updates}))
        save_secret_config(_config_path(), clean, CREDENTIALS_PURPOSE, field="credentials")
        return True


@contextmanager
def _one_job():
    if not _LOCK.acquire(blocking=False):
        raise S3BusyError("another s3 backup job is already running")
    try:
        yield
    finally:
        _LOCK.release()


def _active_config(config: dict | None = None) -> dict:
    try:
        return _validated_config(load_config() if config is None else config)
    except S3Error:
        raise
    except Exception as exc:
        raise S3Error("s3 credentials could not be loaded") from exc


def _new_client(_config: dict) -> httpx.Client:
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        limits=CLIENT_LIMITS,
        follow_redirects=False,
        trust_env=False,
        verify=True,
    )


def _check_percent_encoding(value: str) -> None:
    index = 0
    while index < len(value):
        if value[index] == "%":
            if (
                index + 2 >= len(value)
                or value[index + 1] not in _HEX
                or value[index + 2] not in _HEX
            ):
                raise S3Error("s3 request address is invalid")
            index += 3
            continue
        index += 1


def _aws_encode(value: str) -> str:
    return quote(value, safe="-_.~", encoding="utf-8", errors="strict")


def _canonical_uri(path: str) -> str:
    _check_percent_encoding(path)
    try:
        raw = unquote_to_bytes(path)
    except Exception as exc:
        raise S3Error("s3 request address is invalid") from exc
    return quote_from_bytes(raw, safe="/-_.~") or "/"


def _canonical_query(query: str) -> str:
    _check_percent_encoding(query)
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False)
    except ValueError as exc:
        raise S3Error("s3 request address is invalid") from exc
    encoded = sorted((_aws_encode(key), _aws_encode(value)) for key, value in pairs)
    return "&".join(f"{key}={value}" for key, value in encoded)


def _normalized_header_value(value) -> str:
    text = str(value).strip()
    if _has_control(text):
        raise S3Error("s3 request header is invalid")
    return " ".join(text.split())


def _sign_request(
    method: str,
    url: str,
    headers: dict | None,
    payload_hash: str,
    credentials: dict[str, str],
    region: str,
    *,
    now: datetime | None = None,
    service: str = "s3",
    include_content_sha256: bool = True,
) -> dict[str, str]:
    """Return SigV4 headers. The optional service flag exists for AWS test vectors."""
    if not _SHA256.fullmatch(payload_hash):
        raise S3Error("s3 request checksum is invalid")
    if not isinstance(method, str) or not re.fullmatch(r"[A-Z]+", method):
        raise S3Error("s3 request method is invalid")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
        raise S3Error("s3 request address is invalid")
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        raise S3Error("s3 request time is invalid")
    moment = moment.astimezone(UTC)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")
    clean_headers = {
        str(key).lower(): _normalized_header_value(value) for key, value in (headers or {}).items()
    }
    clean_headers["host"] = parsed.netloc.lower()
    clean_headers["x-amz-date"] = amz_date
    if include_content_sha256:
        clean_headers["x-amz-content-sha256"] = payload_hash
    canonical_headers = "".join(f"{key}:{clean_headers[key]}\n" for key in sorted(clean_headers))
    signed_headers = ";".join(sorted(clean_headers))
    canonical_request = "\n".join(
        (
            method,
            _canonical_uri(parsed.path),
            _canonical_query(parsed.query),
            canonical_headers,
            signed_headers,
            payload_hash,
        )
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    secret = credentials["secret_access_key"].encode("utf-8")
    date_key = hmac.new(b"AWS4" + secret, date_stamp.encode("ascii"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("ascii"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode("ascii"), hashlib.sha256).digest()
    signing_key = hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    clean_headers["authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={credentials['access_key_id']}/{scope},"
        f"SignedHeaders={signed_headers},Signature={signature}"
    )
    return {key.title(): value for key, value in clean_headers.items()}


def _send(
    client: httpx.Client,
    config: dict,
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    content=None,
    payload_hash: str = _EMPTY_SHA256,
):
    from services import net_guard

    try:
        net_guard.assert_safe_url(url)
    except Exception as exc:
        raise S3Error("s3 server address is blocked") from exc
    signed = _sign_request(
        method,
        url,
        headers,
        payload_hash,
        _parse_credentials(config["credentials"]),
        config["region"],
    )
    try:
        request = client.build_request(method, url, headers=signed, content=content)
        response = client.send(request, stream=True)
    except httpx.TimeoutException as exc:
        raise _S3TransportError("s3 request timed out") from exc
    except httpx.HTTPError as exc:
        raise _S3TransportError("s3 request failed") from exc
    if 300 <= response.status_code < 400:
        response.close()
        raise S3Error("s3 redirects are not allowed")
    return response


def _require_status(response, accepted: set[int], action: str) -> None:
    if response.status_code in accepted:
        return
    code = response.status_code
    if code in {401, 403}:
        raise S3Error("s3 authentication or permission check failed")
    if code in {409, 412}:
        raise S3Error(f"s3 {action} conflicted with remote state")
    raise S3Error(f"s3 {action} failed with status {code}")


def _key_prefix(config: dict) -> str:
    prefix = config["prefix"]
    return f"{prefix}/" if prefix else ""


def _object_key(config: dict, name: str) -> str:
    return f"{_key_prefix(config)}{name}"


def _object_url(config: dict, key: str) -> str:
    if (
        not isinstance(key, str)
        or not key
        or len(key.encode("utf-8")) > 1024
        or _has_control(key)
        or key.startswith("/")
    ):
        raise S3Error("s3 object key is invalid")
    encoded_key = quote(key, safe="/-_.~", encoding="utf-8", errors="strict")
    endpoint = urlsplit(config["endpoint"])
    if config["addressing_style"] == "path":
        return f"{config['endpoint']}/{config['bucket']}/{encoded_key}"
    return f"https://{config['bucket']}.{endpoint.netloc}/{encoded_key}"


def _bucket_url(config: dict, query: list[tuple[str, str]]) -> str:
    endpoint = urlsplit(config["endpoint"])
    if config["addressing_style"] == "path":
        base = f"{config['endpoint']}/{config['bucket']}"
    else:
        base = f"https://{config['bucket']}.{endpoint.netloc}/"
    encoded = urlencode(query, doseq=True, quote_via=quote, safe="-_.~")
    return f"{base}?{encoded}"


def _copy_source(config: dict, source_key: str) -> str:
    return quote(f"/{config['bucket']}/{source_key}", safe="/-_.~")


def _response_chunks(response):
    if response.is_stream_consumed:
        yield response.content
        return
    yield from response.iter_raw()


def _content_length(response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    if len(raw) > 20 or not raw.isascii() or not raw.isdigit():
        raise S3Error("s3 response length is invalid")
    return int(raw)


def _read_bounded(response, maximum: int) -> bytes:
    declared = _content_length(response)
    if declared is not None and declared > maximum:
        raise S3Error("s3 response is too large")
    chunks = []
    total = 0
    try:
        for chunk in _response_chunks(response):
            total += len(chunk)
            if total > maximum:
                raise S3Error("s3 response is too large")
            chunks.append(chunk)
    except S3Error:
        raise
    except httpx.HTTPError as exc:
        raise S3Error("s3 response failed") from exc
    return b"".join(chunks)


def _xml_root(document: bytes, action: str):
    try:
        decoded = document.decode("utf-8-sig")
    except UnicodeError as exc:
        raise S3Error(f"s3 {action} response encoding is invalid") from exc
    lowered = decoded.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise S3Error(f"s3 {action} response is unsafe")
    try:
        return ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise S3Error(f"s3 {action} response is invalid") from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_etag(value) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or not value.isascii()
        or any(not 0x21 <= ord(char) <= 0x7E for char in value)
    ):
        raise S3Error("s3 object identifier is invalid")
    if value == "*" or any(char in value for char in "\r\n,"):
        raise S3Error("s3 object identifier is invalid")
    return value


def _put(
    client: httpx.Client,
    config: dict,
    key: str,
    content,
    size: int,
    checksum: str,
) -> str:
    response = _send(
        client,
        config,
        "PUT",
        _object_url(config, key),
        headers={
            "Content-Type": "application/vnd.alles.backup",
            "Content-Length": str(size),
            "If-None-Match": "*",
        },
        content=content,
        payload_hash=checksum,
    )
    with closing(response):
        _require_status(response, {200}, "temporary upload")
        return _safe_etag(response.headers.get("etag"))


def _parse_copy_response(response) -> str:
    _require_status(response, {200}, "backup copy")
    try:
        document = _read_bounded(response, MAX_COPY_RESPONSE_BYTES)
        root = _xml_root(document, "backup copy")
    except S3Error as exc:
        raise _S3TransportError("s3 backup copy response could not be verified") from exc
    if _local_name(root.tag) == "Error":
        raise S3Error("s3 backup copy failed")
    if _local_name(root.tag) != "CopyObjectResult":
        raise _S3TransportError("s3 backup copy response could not be verified")
    etags = [node for node in root if _local_name(node.tag) == "ETag"]
    if len(etags) != 1:
        raise _S3TransportError("s3 backup copy response could not be verified")
    try:
        return _safe_etag((etags[0].text or "").strip())
    except S3Error as exc:
        raise _S3TransportError("s3 backup copy response could not be verified") from exc


def _copy(
    client: httpx.Client,
    config: dict,
    source_key: str,
    destination_key: str,
    source_etag: str,
) -> str:
    response = _send(
        client,
        config,
        "PUT",
        _object_url(config, destination_key),
        headers={
            "Content-Length": "0",
            "If-None-Match": "*",
            "x-amz-copy-source": _copy_source(config, source_key),
            "x-amz-copy-source-if-match": _safe_etag(source_etag),
        },
        content=b"",
    )
    with closing(response):
        return _parse_copy_response(response)


def _delete_key(client: httpx.Client, config: dict, key: str) -> None:
    try:
        response = _send(
            client,
            config,
            "DELETE",
            _object_url(config, key),
            headers={"Content-Length": "0"},
            content=b"",
        )
        response.close()
    except Exception:
        pass


def _file_stream(handle, expected_size: int):
    remaining = expected_size
    while remaining:
        chunk = handle.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise S3Error("encrypted backup changed during upload")
        remaining -= len(chunk)
        yield chunk
    if handle.read(1):
        raise S3Error("encrypted backup changed during upload")


def _open_artifact(path: Path, maximum: int):
    source = Path(path).expanduser()
    if source.is_symlink():
        raise S3Error("encrypted backup cannot be a link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = None
    try:
        fd = os.open(source, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise S3Error("encrypted backup is not a regular file")
        if info.st_size <= len(MAGIC) or info.st_size > maximum:
            raise S3Error("encrypted backup size is invalid")
        handle = os.fdopen(fd, "rb")
        fd = None
        try:
            _read_header(handle, info.st_size, DEFAULT_LIMITS)
        except Exception:
            handle.close()
            raise S3Error("file is not an encrypted Alles backup")
        handle.seek(0)
        digest = hashlib.sha256()
        total = 0
        while chunk := handle.read(CHUNK_SIZE):
            total += len(chunk)
            if total > maximum:
                handle.close()
                raise S3Error("encrypted backup exceeds the single-request size limit")
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if (
            total != info.st_size
            or after.st_size != info.st_size
            or after.st_mtime_ns != info.st_mtime_ns
        ):
            handle.close()
            raise S3Error("encrypted backup changed while it was being read")
        handle.seek(0)
        return handle, total, digest.hexdigest()
    except S3Error:
        raise
    except OSError as exc:
        raise S3Error("encrypted backup could not be read") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _validate_container_prefix(prefix: bytes, total: int) -> None:
    try:
        _read_header(io.BytesIO(prefix), total, DEFAULT_LIMITS)
    except Exception as exc:
        raise S3Error("remote file is not a valid encrypted Alles backup") from exc


def _hash_response(
    response,
    *,
    maximum: int,
    expected_size: int | None = None,
) -> tuple[int, str]:
    declared = _content_length(response)
    if declared is not None and (
        declared > maximum or (expected_size is not None and declared != expected_size)
    ):
        raise S3Error("s3 backup size verification failed")
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    try:
        for chunk in _response_chunks(response):
            total += len(chunk)
            if total > maximum or (expected_size is not None and total > expected_size):
                raise S3Error("s3 backup exceeds the single-request size limit")
            if len(prefix) < _HEADER_PREFIX_BYTES:
                prefix.extend(chunk[: _HEADER_PREFIX_BYTES - len(prefix)])
            digest.update(chunk)
    except S3Error:
        raise
    except httpx.HTTPError as exc:
        raise S3Error("s3 backup response failed") from exc
    if expected_size is not None and total != expected_size:
        raise S3Error("s3 backup size verification failed")
    _validate_container_prefix(bytes(prefix), total)
    return total, digest.hexdigest()


def _verify_remote(
    client: httpx.Client,
    config: dict,
    key: str,
    *,
    expected_size: int,
    expected_sha256: str,
) -> tuple[int, str] | None:
    try:
        response = _send(
            client,
            config,
            "GET",
            _object_url(config, key),
            headers={"Accept-Encoding": "identity"},
        )
        with closing(response):
            _require_status(response, {200}, "backup verification")
            size, checksum = _hash_response(
                response,
                maximum=MAX_ARTIFACT_BYTES,
                expected_size=expected_size,
            )
        if not hmac.compare_digest(checksum, expected_sha256):
            return None
        return size, checksum
    except Exception:
        return None


def _verify_test_object(
    client: httpx.Client,
    config: dict,
    key: str,
    expected: bytes,
) -> None:
    response = _send(
        client,
        config,
        "GET",
        _object_url(config, key),
        headers={"Accept-Encoding": "identity"},
    )
    with closing(response):
        _require_status(response, {200}, "connection test read")
        body = _read_bounded(response, len(expected) + 1)
    if not hmac.compare_digest(body, expected):
        raise S3Error("s3 connection test read did not match")


def _require_destination_precondition(
    client: httpx.Client,
    config: dict,
    source_key: str,
    destination_key: str,
    source_etag: str,
) -> None:
    response = _send(
        client,
        config,
        "PUT",
        _object_url(config, destination_key),
        headers={
            "Content-Length": "0",
            "If-None-Match": "*",
            "x-amz-copy-source": _copy_source(config, source_key),
            "x-amz-copy-source-if-match": _safe_etag(source_etag),
        },
        content=b"",
    )
    with closing(response):
        if response.status_code in {409, 412}:
            return
        if response.status_code == 200:
            _parse_copy_response(response)
            raise S3Error("s3 destination overwrite protection is not supported")
        _require_status(response, {409, 412}, "overwrite protection check")


def test_connection(config: dict | None = None) -> dict:
    with _one_job():
        clean = _active_config(config)
        marker = uuid.uuid4().hex
        source_key = _object_key(clean, f".alles-connection-{marker}.partial")
        destination_key = _object_key(clean, f".alles-connection-{marker}.probe")
        payload = os.urandom(32)
        checksum = hashlib.sha256(payload).hexdigest()
        with _new_client(clean) as client:
            try:
                source_etag = _put(client, clean, source_key, payload, len(payload), checksum)
                _copy(client, clean, source_key, destination_key, source_etag)
                _verify_test_object(client, clean, destination_key, payload)
                _require_destination_precondition(
                    client, clean, source_key, destination_key, source_etag
                )
            finally:
                _delete_key(client, clean, destination_key)
                _delete_key(client, clean, source_key)
    verified_at = _now()
    if config is None:
        _record_status(clean, last_verified_at=verified_at)
    return {"ok": True, "verified_at": verified_at}


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
        raise S3Error("s3 upload size limit is invalid")
    recovered_response = False
    with _one_job():
        clean = _active_config(config)
        handle, size, checksum = _open_artifact(Path(artifact_path), maximum)
        final_name = generated_artifact_name()
        source_key = _object_key(clean, f".alles-upload-{uuid.uuid4().hex}.partial")
        final_key = _object_key(clean, final_name)
        copied = False
        verified = False
        uncertain = False
        try:
            with _new_client(clean) as client:
                try:
                    source_etag = _put(
                        client,
                        clean,
                        source_key,
                        _file_stream(handle, size),
                        size,
                        checksum,
                    )
                    try:
                        _copy(client, clean, source_key, final_key, source_etag)
                        copied = True
                    except _S3TransportError as exc:
                        reconciled = _verify_remote(
                            client,
                            clean,
                            final_key,
                            expected_size=size,
                            expected_sha256=checksum,
                        )
                        if reconciled is None:
                            uncertain = True
                            raise S3Error(
                                "s3 backup result is uncertain; refresh remote backups before retrying"
                            ) from exc
                        remote_size, remote_checksum = reconciled
                        copied = True
                        verified = True
                        recovered_response = True
                    if not verified:
                        response = _send(
                            client,
                            clean,
                            "GET",
                            _object_url(clean, final_key),
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
                            raise S3Error("s3 backup checksum verification failed")
                        verified = True
                finally:
                    _delete_key(client, clean, source_key)
                    if copied and not verified and not uncertain:
                        _delete_key(client, clean, final_key)
        finally:
            handle.close()
    completed_at = _now()
    status_warning = (
        "backup upload response was interrupted; the remote backup was fully verified"
        if recovered_response
        else ""
    )
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
                    "backup uploaded and verified, but local s3 status could not be saved"
                )
        except Exception:
            status_warning = "backup uploaded and verified, but local s3 status could not be saved"
    return {
        "ok": True,
        "name": final_name,
        "size": remote_size,
        "sha256": remote_checksum,
        "completed_at": completed_at,
        "status_warning": status_warning,
    }


def _decode_list_key(value: str) -> str:
    _check_percent_encoding(value)
    try:
        return unquote_to_bytes(value).decode("utf-8")
    except UnicodeError as exc:
        raise S3Error("s3 backup listing key is invalid") from exc


def _direct_text(root, name: str) -> str | None:
    matches = [child for child in root if _local_name(child.tag) == name]
    if len(matches) > 1:
        raise S3Error("s3 backup listing response is invalid")
    return (matches[0].text or "") if matches else None


def _parse_listing_page(config: dict, document: bytes) -> tuple[list[dict], bool, str]:
    root = _xml_root(document, "backup listing")
    if _local_name(root.tag) != "ListBucketResult":
        raise S3Error("s3 backup listing response is invalid")
    if (_direct_text(root, "EncodingType") or "").strip() != "url":
        raise S3Error("s3 backup listing encoding is invalid")
    truncated_text = (_direct_text(root, "IsTruncated") or "").strip().lower()
    if truncated_text not in {"true", "false"}:
        raise S3Error("s3 backup listing pagination is invalid")
    truncated = truncated_text == "true"
    token = (_direct_text(root, "NextContinuationToken") or "").strip()
    if truncated and (not token or len(token.encode("utf-8")) > 4096 or _has_control(token)):
        raise S3Error("s3 backup listing pagination is invalid")
    if not truncated:
        token = ""
    expected_prefix = _key_prefix(config)
    items = []
    for contents in (child for child in root if _local_name(child.tag) == "Contents"):
        key_text = _direct_text(contents, "Key")
        size_text = (_direct_text(contents, "Size") or "").strip()
        modified = (_direct_text(contents, "LastModified") or "").strip()
        etag = (_direct_text(contents, "ETag") or "").strip()
        if key_text is None:
            raise S3Error("s3 backup listing response is invalid")
        key = _decode_list_key(key_text.strip())
        if not key.startswith(expected_prefix):
            continue
        name = key[len(expected_prefix) :]
        if "/" in name or not _is_artifact_name(name):
            continue
        if not size_text.isascii() or not size_text.isdigit():
            raise S3Error("s3 backup listing size is invalid")
        size = int(size_text)
        if size <= len(MAGIC) or size > MAX_ARTIFACT_BYTES:
            continue
        if (
            len(modified) > 256
            or _has_control(modified)
            or (modified and not _is_timestamp(modified))
        ):
            raise S3Error("s3 backup listing time is invalid")
        item_etag = _safe_etag(etag)
        items.append({"name": name, "size": size, "modified": modified, "etag": item_etag})
    return items, truncated, token


def list_artifacts(*, config: dict | None = None) -> list[dict]:
    with _one_job():
        clean = _active_config(config)
        found: dict[str, dict] = {}
        seen_tokens: set[str] = set()
        token = ""
        with _new_client(clean) as client:
            for _page in range(MAX_LISTING_PAGES):
                query = [
                    ("list-type", "2"),
                    ("encoding-type", "url"),
                    ("delimiter", "/"),
                    ("max-keys", "1000"),
                    ("prefix", f"{_key_prefix(clean)}alles-backup-"),
                ]
                if token:
                    query.append(("continuation-token", token))
                response = _send(
                    client,
                    clean,
                    "GET",
                    _bucket_url(clean, query),
                    headers={"Accept-Encoding": "identity"},
                )
                with closing(response):
                    _require_status(response, {200}, "backup listing")
                    document = _read_bounded(response, MAX_LISTING_BYTES)
                items, truncated, next_token = _parse_listing_page(clean, document)
                for item in items:
                    found[item["name"]] = item
                    if len(found) > MAX_LISTED_ARTIFACTS:
                        raise S3Error("s3 listing contains too many backups")
                if not truncated:
                    break
                if next_token in seen_tokens:
                    raise S3Error("s3 backup listing pagination repeated")
                seen_tokens.add(next_token)
                token = next_token
            else:
                raise S3Error("s3 backup listing has too many pages")
    return sorted(found.values(), key=lambda item: item["name"], reverse=True)


def _download_response(
    response,
    temp: Path,
    *,
    maximum: int,
    expected_size: int | None,
) -> tuple[int, str]:
    declared = _content_length(response)
    if declared is not None and (
        declared > maximum or (expected_size is not None and declared != expected_size)
    ):
        raise S3Error("s3 backup size verification failed")
    digest = hashlib.sha256()
    total = 0
    try:
        with temp.open("xb") as handle:
            for chunk in _response_chunks(response):
                total += len(chunk)
                if total > maximum or (expected_size is not None and total > expected_size):
                    raise S3Error("s3 backup exceeds the single-request size limit")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
    except S3Error:
        raise
    except (OSError, httpx.HTTPError) as exc:
        raise S3Error("s3 backup could not be downloaded") from exc
    if expected_size is not None and total != expected_size:
        raise S3Error("s3 backup size verification failed")
    try:
        with temp.open("rb") as handle:
            _read_header(handle, total, DEFAULT_LIMITS)
    except Exception as exc:
        raise S3Error("remote file is not a valid encrypted Alles backup") from exc
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
        raise S3Error("s3 backup filename is invalid")
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or maximum > MAX_ARTIFACT_BYTES
    ):
        raise S3Error("s3 download size limit is invalid")
    if expected_size is not None and (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size <= 0
        or expected_size > maximum
    ):
        raise S3Error("s3 expected backup size is invalid")
    if expected_sha256 is not None and not _SHA256.fullmatch(expected_sha256):
        raise S3Error("s3 expected backup checksum is invalid")
    output = Path(destination).expanduser()
    if output.is_symlink():
        raise S3Error("s3 download destination cannot be a link")
    try:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise S3Error("s3 download destination could not be prepared") from exc
    temp = output.parent / f".{output.name}.{uuid.uuid4().hex}.partial"
    try:
        with _one_job():
            clean = _active_config(config)
            key = _object_key(clean, name)
            with _new_client(clean) as client:
                response = _send(
                    client,
                    clean,
                    "GET",
                    _object_url(clean, key),
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
            raise S3Error("s3 backup checksum verification failed")
        os.replace(temp, output)
    except S3Error:
        temp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise S3Error("s3 backup could not be stored") from exc
    return {"ok": True, "name": name, "path": str(output), "size": size, "sha256": checksum}
