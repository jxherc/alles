"""appearance API — GET the effective theme object, PUT a new one. persists under
settings['appearance'] and keeps legacy theme/accent in sync."""

from fastapi import APIRouter, Request

from core.settings import load_settings, save_settings
from services.appearance import effective, normalize, to_legacy

router = APIRouter(prefix="/api")


@router.get("/appearance")
def get_appearance():
    s = load_settings()
    a = effective(s)
    # _stored = an appearance object is actually saved (vs. synthesized from legacy/defaults).
    # the client only lets the server overwrite its local cache when this is true, so a
    # fire-and-forget PUT that hasn't landed yet can't clobber a freshly-set local theme.
    a["_stored"] = bool(isinstance(s.get("appearance"), dict) and s.get("appearance"))
    return a


@router.put("/appearance")
async def put_appearance(request: Request):
    body = await request.json()
    appearance = normalize(body if isinstance(body, dict) else {})
    theme, accent = to_legacy(appearance)
    save_settings({"appearance": appearance, "theme": theme, "accent": accent})
    return appearance
