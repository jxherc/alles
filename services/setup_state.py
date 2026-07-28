"""Server-owned, resumable first-run state and validation."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.settings import auth_enabled, load_settings, save_settings

VERSION = 1
STEPS = ("basics", "access", "files", "ai_search", "protection")
_REGION = re.compile(r"^(?:[A-Z]{2}|[0-9]{3})$")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class SetupStateError(ValueError):
    pass


def _visible_defaults() -> tuple[Path, Path]:
    root = Path.home() / "Alles"
    try:
        from services.native_install import current_layout

        native = current_layout()
    except Exception:
        native = None
    if native is not None:
        return native.vault_default, native.files_default
    return root / "Vault", root / "Files"


def _stored() -> dict:
    raw = load_settings().get("setup_state")
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return {
            "version": VERSION,
            "completed_steps": [],
            "completed": False,
            "dismissed": False,
            "files_companion_pending": False,
        }
    steps = raw.get("completed_steps")
    clean_steps = [step for step in STEPS if isinstance(steps, list) and step in steps]
    return {
        "version": VERSION,
        "completed_steps": clean_steps,
        "completed": bool(raw.get("completed")),
        "dismissed": bool(raw.get("dismissed")),
        "files_companion_pending": bool(raw.get("files_companion_pending")),
    }


def public_state() -> dict:
    state = _stored()
    settings = load_settings()
    vault_default, files_default = _visible_defaults()
    next_step = (
        "files"
        if state["files_companion_pending"]
        else next((step for step in STEPS if step not in state["completed_steps"]), "done")
    )
    return {
        **state,
        "next_step": next_step,
        "steps": list(STEPS),
        "keep_vault_inside_alles": bool(settings.get("keep_vault_inside_alles", True)),
        "vault_preview": str(Path(settings.get("vault_dir") or vault_default).expanduser()),
        "files_preview": str(Path(settings.get("files_dir") or files_default).expanduser()),
        "access_profile": str(settings.get("access_profile") or "device"),
        "public_url": str(settings.get("public_url") or ""),
        "base_domain": str(settings.get("base_domain") or ""),
        "trusted_hosts": str(settings.get("trusted_hosts") or ""),
        "forwarded_allow_ips": str(settings.get("forwarded_allow_ips") or ""),
        "language": str(settings.get("language") or "en"),
        "region": str(settings.get("region") or ""),
        "timezone": str(settings.get("timezone") or ""),
        "username": str(settings.get("username") or ""),
        "search_provider": str(settings.get("search_provider") or "duckduckgo"),
        "searxng_url": str(settings.get("searxng_url") or ""),
        "automatic_backup_enabled": bool(settings.get("automatic_backup_enabled", False)),
        "automatic_backup_dir": str(
            Path(
                settings.get("automatic_backup_dir") or (Path.home() / "Alles" / "Backups")
            ).expanduser()
        ),
        "automatic_backup_last_success": str(settings.get("automatic_backup_last_success") or ""),
        "automatic_backup_last_error": str(settings.get("automatic_backup_last_error") or ""),
    }


def _save_state(state: dict) -> dict:
    save_settings({"setup_state": state})
    return public_state()


def _mark_step(step: str) -> dict:
    state = _stored()
    state["completed"] = False
    if step not in state["completed_steps"]:
        state["completed_steps"].append(step)
    state["completed_steps"] = [name for name in STEPS if name in state["completed_steps"]]
    return _save_state(state)


def _mark_files_step(*, companion_reviewed: bool) -> dict:
    state = _stored()
    state["completed"] = False
    if "files" not in state["completed_steps"]:
        state["completed_steps"].append("files")
    state["completed_steps"] = [name for name in STEPS if name in state["completed_steps"]]
    state["files_companion_pending"] = not companion_reviewed
    return _save_state(state)


def _text(values: dict, key: str, *, maximum: int = 500) -> str:
    value = values.get(key, "")
    if not isinstance(value, str):
        raise SetupStateError(f"{key} must be text")
    value = value.strip()
    if len(value) > maximum:
        raise SetupStateError(f"{key} is too long")
    return value


def _save_basics(values: dict) -> None:
    username = _text(values, "username", maximum=120)
    language = _text(values, "language", maximum=20).lower() or "en"
    if language != "en":
        raise SetupStateError("English is the only reviewed language")
    region = _text(values, "region", maximum=3).upper()
    if region and not _REGION.fullmatch(region):
        raise SetupStateError("region must be a two-letter or three-digit code")
    timezone = _text(values, "timezone", maximum=120)
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SetupStateError("timezone must be a valid IANA name") from exc
    save_settings(
        {"username": username, "language": language, "region": region, "timezone": timezone}
    )


def _valid_public(values: dict) -> dict:
    origin = _text(values, "public_url", maximum=500)
    base_domain = _text(values, "base_domain", maximum=253).lower().rstrip(".")
    trusted = _text(values, "trusted_hosts", maximum=1000)
    proxies = _text(values, "forwarded_allow_ips", maximum=1000)
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise SetupStateError("public access needs a valid HTTPS origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SetupStateError("public access needs an HTTPS origin without a path")
    host = parsed.hostname.lower().rstrip(".")
    labels = host.split(".")
    if "*" in host or len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise SetupStateError("public access needs a concrete DNS host")
    if not base_domain or base_domain != host:
        raise SetupStateError("base domain must match the public URL host")
    trusted_values = [item.strip().lower() for item in trusted.split(",") if item.strip()]
    required_hosts = {host, f"*.{host}"}
    if not required_hosts.issubset(trusted_values):
        raise SetupStateError("trusted hosts must include the public host and its app subdomains")
    if any(value not in required_hosts for value in trusted_values):
        raise SetupStateError("trusted hosts cannot include unrelated or broad host patterns")
    proxy_values = [item.strip() for item in proxies.split(",") if item.strip()]
    if not proxy_values:
        raise SetupStateError("public access needs at least one exact trusted proxy")
    networks = []
    for value in proxy_values:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise SetupStateError("trusted proxies must be IP addresses or CIDRs") from exc
        if network.prefixlen == 0:
            raise SetupStateError("trusted proxies cannot cover every address")
        networks.append(network)
    for version in (4, 6):
        family = [network for network in networks if network.version == version]
        if family and any(
            network.prefixlen == 0 for network in ipaddress.collapse_addresses(family)
        ):
            raise SetupStateError("trusted proxies cannot collectively cover every address")
    return {
        "access_profile": "public",
        "public_url": origin if port is not None else f"https://{host}",
        "base_domain": base_domain,
        "trusted_hosts": ",".join(trusted_values),
        "forwarded_allow_ips": ",".join(proxy_values),
    }


def _save_access(values: dict) -> None:
    profile = _text(values, "profile", maximum=20).lower()
    if profile not in {"device", "lan", "public"}:
        raise SetupStateError("access profile must be device, lan, or public")
    if profile in {"lan", "public"} and not auth_enabled():
        raise SetupStateError("LAN and public access need an enabled owner password")
    if profile == "public":
        patch = _valid_public(values)
    else:
        patch = {
            "access_profile": profile,
            "public_url": "",
            "base_domain": "",
            "trusted_hosts": "",
            "forwarded_allow_ips": "",
        }
    save_settings(patch)


def _safe_folder(raw: str, *, create: bool) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SetupStateError("Vault and Files paths must be absolute")
    if path == Path(path.anchor):
        raise SetupStateError("the filesystem root cannot be a Vault or Files path")
    if path.is_symlink():
        raise SetupStateError("Vault and Files paths cannot be symlinks")
    if path.exists() and not path.is_dir():
        raise SetupStateError("Vault and Files paths must be folders")
    if not path.exists():
        if not create:
            raise SetupStateError("the selected existing folder does not exist")
        try:
            path.mkdir(parents=True, mode=0o700)
        except OSError as exc:
            raise SetupStateError("the selected folder could not be created") from exc
    return path.resolve()


def _save_files(values: dict) -> None:
    keep = values.get("keep_vault_inside_alles")
    if not isinstance(keep, bool):
        raise SetupStateError("vault placement choice is required")
    vault_raw = _text(values, "vault_path", maximum=2048)
    files_raw = _text(values, "files_path", maximum=2048)
    if not vault_raw or not files_raw:
        raise SetupStateError("Vault and Files paths are required")
    vault = _safe_folder(vault_raw, create=keep)
    files = _safe_folder(files_raw, create=keep)
    if vault == files or vault in files.parents or files in vault.parents:
        raise SetupStateError(
            "Vault and Files need separate folders that do not contain each other"
        )
    if keep and vault.parent != files.parent:
        raise SetupStateError("inside-Alles Vault and Files paths need the same Alles folder")
    save_settings(
        {
            "keep_vault_inside_alles": keep,
            "vault_dir": str(vault),
            "files_dir": str(files),
        }
    )


def _save_ai_search(values: dict) -> None:
    provider = _text(values, "search_provider", maximum=40).lower() or "duckduckgo"
    if provider not in {
        "duckduckgo",
        "searxng",
        "tavily",
        "brave",
        "google_pse",
        "serper",
        "disabled",
    }:
        raise SetupStateError("search provider is not supported")
    patch = {"search_provider": provider}
    if provider == "searxng":
        raw = _text(values, "searxng_url", maximum=500).rstrip("/")
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as exc:
            raise SetupStateError("SearXNG needs a valid URL") from exc
        host = (parsed.hostname or "").lower()
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        if (
            not raw
            or parsed.scheme not in ({"http", "https"} if loopback else {"https"})
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise SetupStateError("SearXNG needs HTTPS, except on localhost")
        authority = f"[{host}]" if ":" in host else host
        patch["searxng_url"] = (
            raw if port is not None else f"{parsed.scheme}://{authority}{parsed.path}"
        )
    save_settings(patch)


def _save_protection(values: dict) -> None:
    automatic = values.get("automatic_backup_enabled", False)
    if not isinstance(automatic, bool):
        raise SetupStateError("automatic backup choice is required")
    backup_dir = _text(values, "automatic_backup_dir", maximum=2048)
    if automatic and not backup_dir:
        raise SetupStateError("automatic backups need a destination folder")
    if backup_dir:
        destination = _safe_folder(backup_dir, create=True)
    else:
        destination = Path.home() / "Alles" / "Backups"
    save_settings(
        {
            "automatic_backup_enabled": automatic,
            "automatic_backup_dir": str(destination),
        }
    )


def save_step(step: str, values: dict) -> dict:
    if step not in STEPS or not isinstance(values, dict):
        raise SetupStateError("unknown setup step")
    companion_reviewed = values.get("companion_reviewed", False)
    if step == "files" and not isinstance(companion_reviewed, bool):
        raise SetupStateError("companion review state must be true or false")
    handlers = {
        "basics": _save_basics,
        "access": _save_access,
        "files": _save_files,
        "ai_search": _save_ai_search,
        "protection": _save_protection,
    }
    handlers[step](values)
    if step == "files":
        return _mark_files_step(companion_reviewed=companion_reviewed)
    return _mark_step(step)


def dismiss() -> dict:
    state = _stored()
    state["dismissed"] = True
    return _save_state(state)


def resume() -> dict:
    state = _stored()
    state["dismissed"] = False
    return _save_state(state)


def complete() -> dict:
    state = _stored()
    if state["files_companion_pending"]:
        raise SetupStateError("review the optional Obsidian companion choice first")
    missing = [step for step in STEPS if step not in state["completed_steps"]]
    if missing:
        raise SetupStateError(f"finish these setup steps first: {', '.join(missing)}")
    if load_settings().get("access_profile") in {"lan", "public"} and not auth_enabled():
        raise SetupStateError("LAN and public access need an enabled owner password")
    state["completed"] = True
    state["dismissed"] = False
    return _save_state(state)
