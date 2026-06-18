import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db
from core.settings import load_settings

router = APIRouter(prefix="/api")


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    s = load_settings()
    provider = s.get("stt_provider", "browser")

    if provider == "local":
        from services import stt_local

        if not stt_local.available():
            raise HTTPException(
                400, "local STT needs faster-whisper — run: pip install faster-whisper"
            )
        try:
            audio = await file.read()
            import asyncio

            text = await asyncio.to_thread(
                stt_local.transcribe,
                audio,
                s.get("stt_model", "base"),
                s.get("stt_language", ""),
            )
            return {"text": text}
        except Exception as e:
            raise HTTPException(500, f"local transcription failed: {e}")

    if provider == "whisper_api":
        key = s.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
        if not key:
            raise HTTPException(400, "openai_api_key not configured for whisper_api")
        try:
            import httpx

            audio = await file.read()
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (file.filename or "audio.webm", audio, file.content_type)},
                    data={"model": "whisper-1"},
                )
                if r.status_code >= 400:
                    raise HTTPException(502, f"whisper error: {r.text[:200]}")
                return {"text": r.json().get("text", "")}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, str(e))

    raise HTTPException(400, "use browser STT (Web Speech API)")


class TtsRequest(BaseModel):
    text: str
    voice: str = "alloy"


@router.post("/tts")
async def text_to_speech(body: TtsRequest):
    s = load_settings()
    provider = s.get("tts_provider", "browser")
    if provider != "openai":
        raise HTTPException(400, "use browser TTS (speechSynthesis)")

    key = s.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise HTTPException(400, "openai_api_key not configured")

    import httpx

    voice = body.voice or s.get("tts_voice", "alloy")
    text = body.text[:4096]

    async def _stream():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json={"model": "tts-1", "input": text, "voice": voice},
            ) as resp:
                async for chunk in resp.aiter_bytes(8192):
                    yield chunk

    return StreamingResponse(_stream(), media_type="audio/mpeg")


class AudioOverviewReq(BaseModel):
    session_id: str = ""
    doc_path: str = ""
    style: str = "summary"  # summary | podcast


@router.post("/audio-overview")
async def audio_overview(body: AudioOverviewReq, db: DbSession = Depends(get_db)):
    """turn a chat or a doc into a spoken-word script (segments the client plays
    through TTS). the model writes it; we clean it into ordered segments."""
    from core.database import ModelEndpoint, Session
    from services import audio_overview as ao

    # resolve the source material
    if body.session_id:
        s = db.get(Session, body.session_id)
        if not s:
            raise HTTPException(404, "session not found")
        parts = []
        for m in s.messages:
            if m.role in ("user", "assistant") and (m.content or "").strip():
                parts.append(f"{m.role}: {m.content.strip()}")
        source = "\n\n".join(parts)
    elif body.doc_path:
        from services import vault_md

        doc = vault_md.read(body.doc_path)
        if not doc.get("exists"):
            raise HTTPException(404, "doc not found")
        source = doc.get("content", "")
    else:
        raise HTTPException(400, "give a session_id or doc_path")

    if not (source or "").strip():
        raise HTTPException(400, "nothing to summarize")

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep or not ep.models_list():
        raise HTTPException(400, "no model endpoint configured")

    style = body.style if body.style in ("summary", "podcast") else "summary"
    segments = await ao.generate(source, style, ep.base_url, ep.api_key, ep.models_list()[0])
    return {"style": style, "segments": segments}
