"""Fail-closed Server authority policy and exact host-service controls."""

from __future__ import annotations

import difflib
import ipaddress
import json
import os
import platform
import re
import stat
import subprocess
import uuid
from pathlib import Path

from core.settings import data_dir

DEFAULT_POLICY = {"control_mode": "owned_only", "host_services": []}
CONTROL_MODES = frozenset({"owned_only", "allowlisted_host"})
MANAGERS = frozenset({"launchd", "systemd"})
CONFIRMATION_PHRASE = "allow host services"
MAX_HOST_SERVICES = 64
MAX_POLICY_BYTES = 32_768
_LAUNCHD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SYSTEMD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,246}\.service$")


class ServerPolicyError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def policy_path() -> Path:
    return data_dir() / "server-policy.json"


def _canonical(policy: dict) -> str:
    return json.dumps(policy, ensure_ascii=False, indent=2) + "\n"


def validate(value) -> dict:
    if not isinstance(value, dict):
        raise ServerPolicyError("invalid_policy", "policy must be one JSON object")
    if set(value) != {"control_mode", "host_services"}:
        raise ServerPolicyError(
            "invalid_policy_fields", "policy accepts only control_mode and host_services"
        )
    mode = value.get("control_mode")
    services = value.get("host_services")
    if mode not in CONTROL_MODES:
        raise ServerPolicyError(
            "invalid_control_mode", "control_mode must be owned_only or allowlisted_host"
        )
    if not isinstance(services, list) or len(services) > MAX_HOST_SERVICES:
        raise ServerPolicyError(
            "invalid_host_services", f"host_services must contain at most {MAX_HOST_SERVICES} items"
        )
    normalized = []
    seen = set()
    for item in services:
        if not isinstance(item, dict) or set(item) != {"manager", "id"}:
            raise ServerPolicyError(
                "invalid_host_service", "each host service needs only manager and id"
            )
        manager = item.get("manager")
        service_id = item.get("id")
        if manager not in MANAGERS or not isinstance(service_id, str):
            raise ServerPolicyError(
                "invalid_host_service", "manager must be launchd or systemd with an exact id"
            )
        pattern = _LAUNCHD_ID if manager == "launchd" else _SYSTEMD_ID
        if not pattern.fullmatch(service_id):
            raise ServerPolicyError(
                "invalid_host_service_id", f"invalid exact {manager} service identifier"
            )
        key = (manager, service_id)
        if key in seen:
            raise ServerPolicyError("duplicate_host_service", "duplicate host service identifier")
        seen.add(key)
        normalized.append({"manager": manager, "id": service_id})
    if mode == "owned_only" and normalized:
        raise ServerPolicyError(
            "owned_only_has_host_services", "owned_only policy must keep host_services empty"
        )
    normalized.sort(key=lambda item: (item["manager"], item["id"]))
    return {"control_mode": mode, "host_services": normalized}


def validate_text(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_POLICY_BYTES:
        raise ServerPolicyError("policy_too_large", "policy file is too large")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ServerPolicyError("invalid_policy_json", "policy is not valid JSON") from exc
    return validate(value)


def _safe_existing(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ServerPolicyError("policy_missing", "server policy file is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ServerPolicyError("unsafe_policy_file", "server policy must be a regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ServerPolicyError("unsafe_policy_owner", "server policy owner changed")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ServerPolicyError(
            "unsafe_policy_permissions", "server policy permissions must be owner-only"
        )
    if info.st_size > MAX_POLICY_BYTES:
        raise ServerPolicyError("policy_too_large", "server policy file is too large")
    return info


def read() -> dict:
    """Return the effective policy and fail closed on every unsafe file state."""
    path = policy_path()
    try:
        before = _safe_existing(path)
        raw = path.read_text("utf-8")
        after = _safe_existing(path)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise ServerPolicyError("policy_changed_during_read", "server policy changed during read")
        policy = validate_text(raw)
        return {
            "policy": policy,
            "canonical": _canonical(policy),
            "path": str(path),
            "valid": True,
            "error_code": "",
            "error": "",
        }
    except (OSError, UnicodeError, ServerPolicyError) as exc:
        code = exc.code if isinstance(exc, ServerPolicyError) else "policy_unreadable"
        return {
            "policy": dict(DEFAULT_POLICY),
            "canonical": _canonical(DEFAULT_POLICY),
            "path": str(path),
            "valid": False,
            "error_code": code,
            "error": str(exc),
        }


def diff(raw: str) -> dict:
    candidate = validate_text(raw)
    current = read()["policy"]
    lines = list(
        difflib.unified_diff(
            _canonical(current).splitlines(),
            _canonical(candidate).splitlines(),
            fromfile="effective",
            tofile="proposed",
            lineterm="",
        )
    )
    return {"policy": candidate, "canonical": _canonical(candidate), "diff": lines[:200]}


def save(raw: str) -> dict:
    candidate = validate_text(raw)
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        _safe_existing(path)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    encoded = _canonical(candidate).encode("utf-8")
    fd = None
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        path.chmod(0o600)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    result = read()
    if not result["valid"] or result["policy"] != candidate:
        raise ServerPolicyError("policy_write_failed", "saved policy could not be verified")
    return result


def is_loopback_client(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_allowed_host_service(manager: str, service_id: str) -> dict:
    current = read()
    if not current["valid"] or current["policy"]["control_mode"] != "allowlisted_host":
        raise ServerPolicyError("host_control_disabled", "host service control is not enabled")
    exact = {(
        item["manager"],
        item["id"],
    ) for item in current["policy"]["host_services"]}
    if (manager, service_id) not in exact:
        raise ServerPolicyError("host_service_not_allowed", "host service is not exactly allowlisted")
    return {"manager": manager, "id": service_id}


def _host_command(manager: str, service_id: str, action: str) -> list[str]:
    if action not in {"start", "stop", "restart"}:
        raise ServerPolicyError("invalid_host_action", "unsupported host service action")
    if manager == "launchd":
        if platform.system() != "Darwin":
            raise ServerPolicyError("manager_unavailable", "launchd is unavailable")
        target = f"gui/{os.getuid()}/{service_id}"
        if action == "start":
            return ["launchctl", "kickstart", target]
        if action == "restart":
            return ["launchctl", "kickstart", "-k", target]
        return ["launchctl", "kill", "SIGTERM", target]
    if platform.system() == "Windows":
        raise ServerPolicyError("manager_unavailable", "systemd is unavailable")
    return ["systemctl", "--user", action, service_id]


def control_host_service(manager: str, service_id: str, action: str) -> dict:
    exact = require_allowed_host_service(manager, service_id)
    command = _host_command(manager, service_id, action)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServerPolicyError("host_service_control_failed", "host service action failed") from exc
    if result.returncode != 0:
        raise ServerPolicyError("host_service_control_failed", "host service action failed")
    return {**exact, "action": action, "accepted": True}
