import ipaddress
import os
import re
from urllib.parse import urlsplit

from core.settings import auth_enabled, load_settings


class AccessConfigError(ValueError):
    """The requested network exposure is not safe to start."""


_ACCESS_PROFILES = {"device", "lan", "public"}
_DEVICE_TRUSTED_HOSTS = ("localhost", "*.localhost", "127.0.0.1", "[::1]", "testserver")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def access_profile() -> str:
    """Return the selected user-facing access profile."""
    profile = os.environ.get("ALLES_ACCESS_PROFILE", "").strip().lower() or "device"
    if profile not in _ACCESS_PROFILES:
        choices = ", ".join(sorted(_ACCESS_PROFILES))
        raise AccessConfigError(f"unknown access profile {profile!r}; choose one of: {choices}")
    return profile


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _owner_password_ready() -> bool:
    if not auth_enabled():
        return False
    if os.environ.get("AUTH_PASSWORD", "").strip():
        return True
    return bool(load_settings().get("auth_password_hash"))


def cors_origins() -> tuple[str, ...]:
    """Return the exact browser origins allowed to read cross-origin responses."""
    raw = os.environ.get("ALLES_CORS_ORIGINS", "").strip()
    if not raw:
        return ()

    entries = raw.split(",")
    if any(not entry.strip() for entry in entries):
        raise AccessConfigError("ALLES_CORS_ORIGINS contains a blank origin")

    origins: list[str] = []
    for entry in entries:
        value = entry.strip()
        if value == "*" or "*" in value:
            raise AccessConfigError("wildcard CORS origins are not allowed")
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise AccessConfigError(f"invalid CORS origin {value!r}") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise AccessConfigError(f"invalid CORS origin {value!r}")

        normalized_host = host.lower()
        if ":" in normalized_host:
            normalized_host = f"[{normalized_host}]"
        normalized = f"{parsed.scheme.lower()}://{normalized_host}"
        if port is not None:
            normalized += f":{port}"
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def _valid_dns_name(host: str) -> bool:
    if len(host) > 253:
        return False
    labels = host.rstrip(".").split(".")
    return bool(labels) and all(_HOST_LABEL.fullmatch(label) for label in labels)


def _normalize_trusted_host(value: str) -> str:
    raw = value.strip().lower()
    if not raw or raw == "*" or "/" in raw or "@" in raw or "://" in raw:
        raise AccessConfigError(f"invalid trusted host {value!r}")

    wildcard = raw.startswith("*.")
    candidate = raw[2:] if wildcard else raw
    if "*" in candidate:
        raise AccessConfigError(f"invalid trusted host {value!r}")

    if candidate.startswith("[") and candidate.endswith("]"):
        try:
            address = ipaddress.ip_address(candidate[1:-1])
        except ValueError as exc:
            raise AccessConfigError(f"invalid trusted host {value!r}") from exc
        if wildcard:
            raise AccessConfigError(f"invalid trusted host {value!r}")
        return f"[{address.compressed}]"

    if ":" in candidate:
        raise AccessConfigError(f"invalid trusted host {value!r}; do not include a port")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        try:
            candidate = candidate.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise AccessConfigError(f"invalid trusted host {value!r}") from exc
        if not _valid_dns_name(candidate):
            raise AccessConfigError(f"invalid trusted host {value!r}")
        return f"*.{candidate}" if wildcard else candidate
    if wildcard:
        raise AccessConfigError(f"invalid trusted host {value!r}")
    return address.compressed


def trusted_hosts() -> tuple[str, ...]:
    """Return allowed Host header names for the selected access profile."""
    raw = os.environ.get("ALLES_TRUSTED_HOSTS", "").strip()
    if not raw:
        if access_profile() == "device":
            return _DEVICE_TRUSTED_HOSTS
        if access_profile() == "public":
            raise AccessConfigError("public access requires ALLES_TRUSTED_HOSTS")
        return ()

    entries = raw.split(",")
    if any(not entry.strip() for entry in entries):
        raise AccessConfigError("ALLES_TRUSTED_HOSTS contains a blank trusted host")
    hosts: list[str] = []
    for entry in entries:
        host = _normalize_trusted_host(entry)
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def forwarded_allow_ips() -> tuple[str, ...]:
    """Return exact proxy IP addresses or CIDRs trusted to set forwarded headers."""
    raw = os.environ.get("ALLES_FORWARDED_ALLOW_IPS", "").strip()
    if not raw:
        if access_profile() == "public":
            raise AccessConfigError("public access requires ALLES_FORWARDED_ALLOW_IPS")
        return ()

    entries = raw.split(",")
    if any(not entry.strip() for entry in entries):
        raise AccessConfigError("ALLES_FORWARDED_ALLOW_IPS contains a blank forwarded proxy")
    networks: list[str] = []
    for entry in entries:
        value = entry.strip()
        if value == "*":
            raise AccessConfigError("wildcard forwarded proxy trust is not allowed")
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise AccessConfigError(f"invalid forwarded proxy address {value!r}") from exc
        if network.prefixlen == 0:
            raise AccessConfigError("a forwarded proxy cannot use an everywhere CIDR")
        normalized = str(network.network_address)
        if "/" in value:
            normalized = network.with_prefixlen
        if normalized not in networks:
            networks.append(normalized)
    return tuple(networks)


def public_origin() -> str:
    """Validate and return the external HTTPS origin for public access."""
    raw = os.environ.get("ALLES_PUBLIC_URL", "").strip()
    if not raw:
        raise AccessConfigError("public access requires ALLES_PUBLIC_URL")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise AccessConfigError("ALLES_PUBLIC_URL must be a valid HTTPS origin") from exc
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise AccessConfigError("ALLES_PUBLIC_URL must be an HTTPS origin without a path")
    normalized_host = host.lower()
    shown_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    origin = f"https://{shown_host}"
    if port is not None:
        origin += f":{port}"

    hosts = trusted_hosts()
    exact_host = _normalize_trusted_host(shown_host)
    if exact_host not in hosts:
        raise AccessConfigError("the public URL host must appear in ALLES_TRUSTED_HOSTS")
    base_domain = (
        os.environ.get("BASE_DOMAIN", "").strip().lower()
        or str(load_settings().get("base_domain", "")).strip().lower()
    )
    if not base_domain or base_domain == "localhost":
        raise AccessConfigError("public access requires BASE_DOMAIN")
    if _normalize_trusted_host(base_domain) != exact_host:
        raise AccessConfigError("BASE_DOMAIN must match the ALLES_PUBLIC_URL host")
    if f"*.{exact_host}" not in hosts:
        raise AccessConfigError("public access requires the app subdomain trusted-host pattern")
    return origin


def bind_host() -> str:
    """Return a bind address only when the selected exposure is safe to start."""
    profile = access_profile()
    configured_host = os.environ.get("ALLES_HOST", "").strip()

    container = os.environ.get("ALLES_RUNTIME", "").strip().lower() == "container"
    # A device-only container listens inside its own network namespace. The quick
    # start publishes that internal port to host loopback only.
    if container and profile == "device":
        return configured_host or "0.0.0.0"

    if profile == "device":
        host = configured_host or "127.0.0.1"
        if not _is_loopback(host):
            if not os.environ.get("ALLES_ACCESS_PROFILE", "").strip():
                raise AccessConfigError(
                    "a non-loopback ALLES_HOST also needs an explicit "
                    "ALLES_ACCESS_PROFILE"
                )
            raise AccessConfigError("the device access profile accepts loopback hosts only")
        return host

    if not _owner_password_ready():
        raise AccessConfigError(
            f"the {profile} access profile requires an enabled owner password"
        )

    if profile == "public":
        public_origin()
        forwarded_allow_ips()

    return configured_host or "0.0.0.0"


def validate_access_config() -> None:
    """Validate the complete access policy even when an external ASGI runner starts Alles."""
    bind_host()
    cors_origins()
    trusted_hosts()
