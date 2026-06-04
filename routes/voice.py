import io, os
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.settings import load_settings

router = APIRouter(prefix="/api")


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    s = load_settings()
    provider = s.get("stt_provider", "browser")

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
    else:
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
    text  = body.text[:4096]

    async def _stream():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST",
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json={"model": "tts-1", "input": text, "voice": voice},
            ) as resp:
                async for chunk in resp.aiter_bytes(8192):
                    yield chunk

    return StreamingResponse(_stream(), media_type="audio/mpeg")
