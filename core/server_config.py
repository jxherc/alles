import ipaddress
import os
from urllib.parse import urlsplit

from core.settings import auth_enabled, load_settings


class AccessConfigError(ValueError):
    """The requested network exposure is not safe to start."""


_ACCESS_PROFILES = {"device", "lan", "public"}


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


def bind_host() -> str:
    """Return a bind address only when the selected exposure is safe to start."""
    profile = access_profile()
    configured_host = os.environ.get("ALLES_HOST", "").strip()

    # A container listens on its internal interface. Host-side publishing remains a
    # separate, explicit operator choice and is loopback-only in the quick-start docs.
    if os.environ.get("ALLES_RUNTIME", "").strip().lower() == "container":
        if profile != "device":
            raise AccessConfigError(
                "container access is controlled by host port publishing; keep "
                "ALLES_ACCESS_PROFILE=device"
            )
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
        raise AccessConfigError(
            "the public access profile is not ready; HTTPS, trusted-host, and proxy "
            "checks must be configured first"
        )

    return configured_host or "0.0.0.0"
