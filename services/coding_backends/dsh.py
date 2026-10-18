"""Scoped client for the MIT-licensed DSH mobile bridge contract."""

import asyncio
import json
import os
from contextlib import aclosing
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from services.model_auth import is_loopback_url

_ALLOWED_METHODS = frozenset(
    {
        "host.describe",
        "workspace.list",
        "session.create",
        "session.list",
        "session.history",
        "session.prompt",
        "session.cancel",
    }
)


def dsh_installed() -> bool:
    """DeepSeek Harness app present for all users or only this one."""
    app = "DeepSeek Harness.app"
    return (Path("/Applications") / app).exists() or (Path.home() / "Applications" / app).exists()


class DshConfigurationError(ValueError):
    pass


class DshTransportError(RuntimeError):
    """The bridge outcome is unknown because no valid RPC result was received."""


class DshProtocolError(RuntimeError):
    """The bridge replied, but not with the documented RPC shape."""


class DshBusinessError(RuntimeError):
    """The bridge definitely rejected a request in a valid RPC envelope."""

    def __init__(self, code: str):
        self.code = str(code or "unknown").replace("-", "_")
        super().__init__(f"dsh_business_error_{self.code}")


def _validated_base_url(value: str) -> str:
    base_url = str(value or "").strip().rstrip("/")
    if not base_url:
        raise DshConfigurationError("dsh_bridge_unconfigured")
    parsed = urlsplit(base_url)
    if not is_loopback_url(base_url) or parsed.username or parsed.password:
        raise DshConfigurationError("dsh_bridge_must_use_authenticated_loopback")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise DshConfigurationError("dsh_bridge_url_invalid")
    return base_url


class _BridgeConnect(connect):
    def process_redirect(self, exc):
        # Keep the authenticated stream on the same explicitly paired destination.
        return exc


def _stream_frame(raw):
    try:
        frame = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DshProtocolError("dsh_bridge_invalid_event") from exc
    if (
        not isinstance(frame, dict)
        or frame.get("type") != "server-request"
        or not isinstance(frame.get("rpcId"), str)
        or not frame["rpcId"]
        or not isinstance(frame.get("payload"), dict)
        or not isinstance(frame.get("method"), str)
        or frame["method"] != frame["payload"].get("type")
    ):
        raise DshProtocolError("dsh_bridge_invalid_event")
    if frame["method"] == "stream/error":
        raise DshTransportError("dsh_bridge_stream_failed")
    return frame


def _answer_result(frame, *, outcome=None, answers=None, cancelled=False):
    payload = frame["payload"]
    session_id = payload["sessionId"]
    if frame["method"] == "approval/requested":
        if outcome not in {"allowed-once", "rejected"} or answers is not None or cancelled:
            raise ValueError("dsh_invalid_approval_response")
        approval_id = payload.get("approvalId")
        if not isinstance(approval_id, str) or not approval_id:
            raise DshProtocolError("dsh_bridge_invalid_approval")
        return {
            "ok": True,
            "value": {"sessionId": session_id, "approvalId": approval_id, "outcome": outcome},
        }
    if frame["method"] != "question/requested" or outcome is not None:
        raise ValueError("dsh_invalid_question_response")
    if cancelled:
        if answers is not None:
            raise ValueError("dsh_invalid_question_response")
        return {
            "ok": False,
            "error": {"code": "cancelled", "message": "cancelled by owner", "details": {}},
        }
    questions = payload.get("questions")
    if (
        not isinstance(questions, list)
        or not questions
        or any(not isinstance(question, dict) for question in questions)
    ):
        raise DshProtocolError("dsh_bridge_invalid_question")
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ValueError("dsh_invalid_question_response")
    clean = []
    for question, answer in zip(questions, answers, strict=True):
        if (
            not isinstance(answer, dict)
            or not question.get("id")
            or answer.get("id") != question["id"]
        ):
            raise ValueError("dsh_invalid_question_response")
        selected = answer.get("selected", [])
        custom = answer.get("custom")
        options = question.get("options") or []
        if not isinstance(options, list) or any(
            not isinstance(option, dict) or not isinstance(option.get("label"), str)
            for option in options
        ):
            raise DshProtocolError("dsh_bridge_invalid_question")
        labels = {option["label"] for option in options}
        if (
            not isinstance(selected, list)
            or any(not isinstance(label, str) or label not in labels for label in selected)
            or len(set(selected)) != len(selected)
            or (custom is not None and (not isinstance(custom, str) or not custom.strip()))
            or (not selected and custom is None)
            or (
                not question.get("multiSelect")
                and (len(selected) > 1 or (selected and custom is not None))
            )
        ):
            raise ValueError("dsh_invalid_question_response")
        clean.append(
            {
                "id": question["id"],
                "selected": selected,
                **({"custom": custom} if custom is not None else {}),
            }
        )
    return {"ok": True, "value": {"sessionId": session_id, "answer": {"answers": clean}}}


class DshBackend:
    def __init__(self, *, base_url: str = "", token: str = ""):
        self.base_url = (base_url or os.getenv("ALLES_DSH_BRIDGE_URL", "")).strip().rstrip("/")
        self.token = token or os.getenv("ALLES_DSH_BRIDGE_TOKEN", "")

    def _validate(self) -> None:
        _validated_base_url(self.base_url)
        if not self.token:
            raise DshConfigurationError("dsh_bridge_unconfigured")

    def capability(self) -> dict:
        installed = dsh_installed()
        try:
            self._validate()
            configured = True
            reason = "configured; availability has not been checked"
        except DshConfigurationError:
            configured = False
            reason = (
                "DeepSeek Harness is installed but its scoped bridge is not connected"
                if installed
                else "DeepSeek Harness and its scoped bridge are not connected"
            )
        return {
            "backend": "deepseek-harness",
            "installed": installed,
            "configured": configured,
            "available": False,
            "reason": reason,
            "credential_location": "encrypted_database" if configured else "none",
        }

    async def _call(self, method: str, payload: dict | None = None) -> dict:
        self._validate()
        if method not in _ALLOWED_METHODS:
            raise ValueError("dsh_method_not_allowed")
        url = f"{self.base_url}/mobile/api/proxy/{quote(method, safe='.')}"
        rpc_id = str(uuid4())
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={
                        "type": "client-request",
                        "rpcId": rpc_id,
                        "method": method,
                        "payload": payload or {},
                    },
                )
        except httpx.HTTPError as exc:
            raise DshTransportError("dsh_bridge_request_failed") from exc
        if response.status_code >= 400:
            raise DshTransportError(f"dsh_bridge_error_{response.status_code}")
        try:
            envelope = response.json()
        except ValueError as exc:
            raise DshProtocolError("dsh_bridge_invalid_response") from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("type") != "server-response"
            or envelope.get("rpcId") != rpc_id
            or not isinstance(envelope.get("result"), dict)
        ):
            raise DshProtocolError("dsh_bridge_invalid_response")
        result = envelope["result"]
        if result.get("ok") is not True:
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            raise DshBusinessError(str(error.get("code") or "unknown"))
        value = result.get("value")
        if not isinstance(value, dict):
            raise DshProtocolError("dsh_bridge_invalid_response")
        return value

    async def health(self) -> dict:
        host = await self._call("host.describe")
        return {**self.capability(), "available": True, "reason": "", "host": host}

    async def list_workspaces(self) -> dict:
        return await self._call("workspace.list")

    async def list_sessions(self) -> dict:
        return await self._call("session.list")

    async def session_history(self, session_id: str, *, max_messages: int = 50) -> dict:
        return await self._call(
            "session.history",
            {"sessionId": str(session_id), "maxMessages": int(max_messages)},
        )

    async def create_session(self, *, workspace_id: str, session_id: str) -> dict:
        return await self._call(
            "session.create",
            {"workspaceId": str(workspace_id), "sessionId": str(session_id)},
        )

    async def prompt_session(self, *, session_id: str, prompt: str) -> dict:
        return await self._call(
            "session.prompt",
            {
                "sessionId": str(session_id),
                "mode": "queue",
                "content": [{"type": "text", "text": str(prompt)}],
            },
        )

    async def cancel_session(self, session_id: str) -> dict:
        return await self._call("session.cancel", {"sessionId": str(session_id)})

    async def live_events(self, session_id: str):
        """Read only the selected session's mux; credentials never reach the browser."""
        self._validate()
        url = self.base_url.replace("http", "ws", 1) + "/mobile/api/proxy/events.mux"
        try:
            async with _BridgeConnect(
                url,
                additional_headers={"Authorization": f"Bearer {self.token}"},
                proxy=None,
                open_timeout=10,
                close_timeout=2,
                max_size=1_048_576,
            ) as stream:
                async for raw in stream:
                    frame = _stream_frame(raw)
                    if frame["payload"].get("sessionId") == session_id:
                        yield frame
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise DshTransportError("dsh_bridge_stream_unavailable") from exc

    async def respond(
        self, session_id: str, rpc_id: str, *, outcome=None, answers=None, cancelled=False
    ):
        self._validate()
        pending = None
        # Reconnection replays stable pending ids. Verify ownership against the host,
        # not a browser-supplied session or approval id; never resend after uncertainty.
        try:
            async with asyncio.timeout(5), aclosing(self.live_events(session_id)) as events:
                async for frame in events:
                    if frame["rpcId"] == rpc_id and frame["method"] in {
                        "approval/requested",
                        "question/requested",
                    }:
                        pending = frame
                        break
        except TimeoutError as exc:
            raise DshTransportError("dsh_pending_request_not_observed") from exc
        if pending is None:
            raise DshTransportError("dsh_pending_request_not_observed")
        result = _answer_result(pending, outcome=outcome, answers=answers, cancelled=cancelled)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(
                    self.base_url + "/mobile/api/proxy/respond",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"type": "client-response", "rpcId": rpc_id, "result": result},
                )
        except httpx.HTTPError as exc:
            raise DshTransportError("dsh_response_outcome_unknown") from exc
        if response.status_code >= 400:
            raise DshTransportError("dsh_response_outcome_unknown")
        try:
            receipt = response.json()
        except ValueError as exc:
            raise DshProtocolError("dsh_bridge_invalid_receipt") from exc
        if not isinstance(receipt, dict) or type(receipt.get("accepted")) is not bool:
            raise DshProtocolError("dsh_bridge_invalid_receipt")
        if receipt["accepted"]:
            return {"accepted": True}
        if receipt.get("reason") not in {"not-pending", "bad-response"}:
            raise DshProtocolError("dsh_bridge_invalid_receipt")
        return {"accepted": False, "reason": receipt["reason"]}

    @classmethod
    async def claim_pairing(cls, *, base_url: str, code: str) -> tuple["DshBackend", dict]:
        """Claim a one-time pairing only after the owner explicitly submits its code."""
        clean_base = _validated_base_url(base_url)
        if not str(code).isdigit() or len(str(code)) != 8:
            raise DshConfigurationError("dsh_pairing_code_invalid")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                payload_response = await client.get(f"{clean_base}/mobile/api/pair/payload")
                if payload_response.status_code >= 400:
                    raise DshTransportError(
                        f"dsh_pairing_payload_error_{payload_response.status_code}"
                    )
                payload = payload_response.json()
                sid = payload.get("sid") if isinstance(payload, dict) else None
                if not isinstance(sid, str) or not sid:
                    raise DshProtocolError("dsh_pairing_payload_invalid")
                claim = await client.post(
                    f"{clean_base}/mobile/api/pair/claim",
                    json={"sid": sid, "code": str(code)},
                )
        except (DshTransportError, DshProtocolError):
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise DshTransportError("dsh_pairing_request_failed") from exc
        if claim.status_code >= 400:
            if claim.status_code in (403, 410, 429):
                raise DshBusinessError(f"pairing_{claim.status_code}")
            raise DshTransportError(f"dsh_pairing_claim_error_{claim.status_code}")
        try:
            body = claim.json()
        except ValueError as exc:
            raise DshProtocolError("dsh_pairing_claim_invalid") from exc
        token = body.get("token") if isinstance(body, dict) and body.get("ok") is True else None
        if not isinstance(token, str) or not token:
            raise DshProtocolError("dsh_pairing_claim_invalid")
        return cls(base_url=clean_base, token=token), payload
