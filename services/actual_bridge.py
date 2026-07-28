"""Bounded, serialized Python boundary for the pinned official Actual Node API."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

RESULT_PREFIX = "ALLES_ACTUAL_RESULT="
DEFAULT_TIMEOUT = 120
MAX_REQUEST_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_CALL_LOCK = threading.RLock()
_SECRET_KEYS = {"password", "session_token", "token", "secret", "authorization"}


class ActualBridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "actual_bridge_failed",
        details: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def integration_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "integrations" / "actual"


def package_json() -> Path:
    return integration_dir() / "package.json"


def lockfile() -> Path:
    return integration_dir() / "package-lock.json"


def bridge_script() -> Path:
    return integration_dir() / "bridge.mjs"


def _secrets(value) -> set[str]:
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_KEYS and isinstance(item, str) and item:
                found.add(item)
            found.update(_secrets(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_secrets(item))
    return found


def _redact(value: str, secrets: set[str]) -> str:
    text = str(value or "")
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(
        r"(?i)(password|token|secret|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        text,
    )
    return text[:800]


def _environment() -> dict[str, str]:
    allowed = ("PATH", "HOME", "TMPDIR", "NODE_EXTRA_CA_CERTS")
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def _run_bounded(command: list[str], payload: str, timeout: int) -> subprocess.CompletedProcess:
    """Run the real bridge without retaining unbounded third-party output in memory."""
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env=_environment(),
        )
        failure: list[BaseException] = []

        def communicate() -> None:
            try:
                process.communicate(input=payload.encode("utf-8"))
            except BaseException as exc:  # propagated on the calling thread below
                failure.append(exc)

        worker = threading.Thread(target=communicate, daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        too_large = False
        timed_out = False
        while worker.is_alive():
            worker.join(0.02)
            output_size = (
                os.fstat(stdout_file.fileno()).st_size + os.fstat(stderr_file.fileno()).st_size
            )
            if output_size > MAX_OUTPUT_BYTES:
                too_large = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
        if too_large or timed_out:
            try:
                process.kill()
            except OSError:
                pass
            worker.join(5)
        if too_large:
            raise ActualBridgeError(
                "Actual bridge output exceeded the safe limit",
                code="actual_bridge_too_large",
            )
        if timed_out:
            raise subprocess.TimeoutExpired(command, timeout)
        if failure:
            raise failure[0]
        output_size = (
            os.fstat(stdout_file.fileno()).st_size + os.fstat(stderr_file.fileno()).st_size
        )
        if output_size > MAX_OUTPUT_BYTES:
            raise ActualBridgeError(
                "Actual bridge output exceeded the safe limit",
                code="actual_bridge_too_large",
            )
        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout_file.read().decode("utf-8", errors="replace"),
            stderr_file.read().decode("utf-8", errors="replace"),
        )


def call(
    request: dict,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    runner=subprocess.run,
    script: Path | None = None,
    node: str = "node",
) -> dict:
    if not isinstance(request, dict) or not isinstance(request.get("command"), str):
        raise ActualBridgeError("Actual bridge request is invalid", code="actual_bridge_invalid")
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ActualBridgeError(
            "Actual bridge request is too large", code="actual_bridge_too_large"
        )
    target = (script or bridge_script()).resolve()
    if not target.is_file():
        raise ActualBridgeError("Actual bridge script is missing", code="actual_bridge_unavailable")
    secrets = _secrets(request)
    command = [node, str(target)]
    with _CALL_LOCK:
        try:
            bounded_timeout = max(1, min(int(timeout), 600))
            if runner is subprocess.run:
                result = _run_bounded(command, payload, bounded_timeout)
            else:
                result = runner(
                    command,
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=bounded_timeout,
                    check=False,
                    env=_environment(),
                )
        except ActualBridgeError:
            raise
        except subprocess.TimeoutExpired as exc:
            raise ActualBridgeError(
                "Actual bridge timed out and was stopped", code="actual_bridge_timeout"
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ActualBridgeError(
                "Actual bridge runtime is unavailable", code="actual_bridge_unavailable"
            ) from exc
    lines = [
        line[len(RESULT_PREFIX) :]
        for line in str(result.stdout or "").splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if not lines:
        # stderr belongs to third-party code and can contain URLs, paths,
        # response bodies, or identifiers which are not safe to surface.
        raise ActualBridgeError(
            "Actual bridge returned no structured result", code="actual_bridge_protocol"
        )
    try:
        response = json.loads(lines[-1])
    except (TypeError, ValueError) as exc:
        raise ActualBridgeError(
            "Actual bridge returned invalid structured data", code="actual_bridge_protocol"
        ) from exc
    if not isinstance(response, dict) or not response.get("ok"):
        error = response.get("error") if isinstance(response, dict) else {}
        code = (
            str(error.get("code") or "actual_bridge_failed")
            if isinstance(error, dict)
            else "actual_bridge_failed"
        )
        message = (
            str(error.get("message") or "Actual bridge failed")
            if isinstance(error, dict)
            else "Actual bridge failed"
        )
        details = {}
        if code in {
            "actual_stage_cleanup_required",
            "actual_stage_reconciliation_required",
        }:
            staged_budget = error.get("staged_budget") if isinstance(error, dict) else None
            budget_id = (
                str(staged_budget.get("budget_id") or "") if isinstance(staged_budget, dict) else ""
            )
            sync_id = (
                str(staged_budget.get("sync_id") or "") if isinstance(staged_budget, dict) else ""
            )
            if (
                not budget_id
                or len(budget_id) > 512
                or len(sync_id) > 512
                or any(ord(char) < 32 for char in budget_id + sync_id)
            ):
                raise ActualBridgeError(
                    "Actual bridge returned invalid staged-budget identity",
                    code="actual_bridge_protocol",
                )
            details["staged_budget"] = {"budget_id": budget_id, "sync_id": sync_id}
        raise ActualBridgeError(_redact(message, secrets), code=code, details=details)
    data = response.get("data")
    if not isinstance(data, dict):
        raise ActualBridgeError(
            "Actual bridge result payload is invalid", code="actual_bridge_protocol"
        )
    return data
