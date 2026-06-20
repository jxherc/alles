"""11a — macOS-native integration endpoints. Guarded: off-darwin they report unavailable /
fail loud (503) rather than pretending. On the Mac mini they pull from Calendar/Reminders."""

from fastapi import APIRouter, HTTPException

from services import macos_bridge as mb

router = APIRouter(prefix="/api/macos")


@router.get("/status")
def macos_status():
    return mb.capabilities()


@router.post("/calendar")
def macos_calendar():
    if not mb.is_mac():
        raise HTTPException(503, "macOS only — runs on the Mac mini")
    try:
        return {"events": mb.export_calendar()}
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/reminders")
def macos_reminders():
    if not mb.is_mac():
        raise HTTPException(503, "macOS only — runs on the Mac mini")
    try:
        return {"reminders": mb.export_reminders()}
    except Exception as e:
        raise HTTPException(502, str(e))
