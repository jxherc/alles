"""OpenAI Realtime WebRTC capability and server-side SDP negotiation."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from core.database import ModelEndpoint
from services.model_auth import provider_id_for

_RT = re.compile(r"realtime", re.I)
_OPENAI_REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"


def _is_official_openai_endpoint(base_url: str) -> bool:
    """Only allow credentials to leave through OpenAI's first-party API origin."""
    try:
        parsed = urlsplit(str(base_url or "").strip())
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.openai.com"
        and port in {None, 443}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path.rstrip("/") in {"", "/v1"}
    )


def find_realtime_endpoint(db):
    """(endpoint, model) for the first enabled endpoint with a realtime model, else (None, '')."""
    for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():  # noqa: E712
        for m in ep.models_list():
            if _RT.search(m or ""):
                return ep, m
    return None, ""


def find_webrtc_endpoint(db, *, endpoint_id: str = "", model: str = ""):
    """Return an authenticated first-party endpoint suitable for `/realtime/calls`."""
    for ep in db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).all():  # noqa: E712
        if endpoint_id and ep.id != endpoint_id:
            continue
        if provider_id_for(ep.base_url, ep.provider_id or "") != "openai":
            continue
        if not _is_official_openai_endpoint(ep.base_url):
            continue
        if not (ep.api_key or "").strip():
            continue
        for candidate in ep.models_list():
            if _RT.search(candidate or "") and (not model or candidate == model):
                return ep, candidate
    return None, ""


def status(db) -> dict:
    ep, model = find_webrtc_endpoint(db)
    if not ep:
        detected, _ = find_realtime_endpoint(db)
        reason = (
            "live voice needs an authenticated OpenAI API endpoint; compatible model names alone "
            "do not expose browser credentials"
            if detected
            else "no realtime-capable OpenAI model configured"
        )
        return {
            "available": False,
            "reason": reason,
            "model": "",
            "transport": "webrtc",
            "negotiation": "server_unified",
        }
    return {
        "available": True,
        "reason": "",
        "model": model,
        "transport": "webrtc",
        "negotiation": "server_unified",
    }


def session_config(model: str) -> dict:
    return {
        "type": "realtime",
        "model": model,
        "output_modalities": ["audio"],
        "instructions": (
            "You are Aide inside Alles. Speak briefly and naturally. Never claim a background "
            "task was started unless the start_background_task tool returns a run id. Ending the "
            "voice call never cancels a background task."
        ),
        "audio": {
            "input": {
                "transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": {
                    "type": "semantic_vad",
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {"voice": "marin"},
        },
        "tools": [
            {
                "type": "function",
                "name": "start_background_task",
                "description": (
                    "Start durable work that continues after this call ends. Use only when the "
                    "user clearly asks to start or continue a task."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string", "description": "The concrete work request"}
                    },
                    "required": ["request"],
                    "additionalProperties": False,
                },
            }
        ],
        "tool_choice": "auto",
    }


@dataclass(frozen=True)
class RealtimeTarget:
    endpoint_id: str
    model: str
    api_key: str = field(repr=False)


def prepare_offer(db, offer_sdp: str, *, endpoint_id: str, model: str) -> RealtimeTarget:
    if not offer_sdp.startswith("v=0") or len(offer_sdp) > 131_072:
        raise ValueError("invalid_realtime_offer")
    ep, selected = find_webrtc_endpoint(db, endpoint_id=endpoint_id, model=model)
    if not endpoint_id or not ep:
        raise ValueError("realtime_unavailable")
    return RealtimeTarget(ep.id, selected, ep.api_key)


async def negotiate_offer(target: RealtimeTarget, offer_sdp: str) -> str:
    """Use a validated snapshot so no database transaction spans the provider await."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _OPENAI_REALTIME_CALLS_URL,
                headers={"Authorization": f"Bearer {target.api_key}"},
                files={
                    "sdp": (None, offer_sdp, "application/sdp"),
                    "session": (
                        None,
                        json.dumps(session_config(target.model), separators=(",", ":")),
                        "application/json",
                    ),
                },
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("realtime provider request failed") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"realtime provider rejected the call ({response.status_code})")
    answer = response.text
    if not answer.startswith("v=0"):
        raise RuntimeError("realtime provider returned an invalid SDP answer")
    return answer
