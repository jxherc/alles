from fastapi import APIRouter, HTTPException

from services import notify

router = APIRouter(prefix="/api/notify")


@router.get("/status")
def status():
    return {"configured": notify.configured()}


@router.post("/test")
async def test():
    """send a test ping to whatever channels are configured."""
    if not notify.configured():
        raise HTTPException(400, "no notification channel configured (settings → notifications)")
    res = await notify.send("alles test notification — you're wired up.")
    return {"ok": True, "sent": res}
