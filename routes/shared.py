import uuid, json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Session

router = APIRouter()


@router.post("/api/sessions/{sid}/share")
def generate_share_link(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, sid)
    if not s or s.archived:
        raise HTTPException(404, "session not found")
    if not s.share_token:
        s.share_token = str(uuid.uuid4()).replace("-", "")
        db.commit()
    return {"token": s.share_token, "url": f"/s/{s.share_token}"}


@router.delete("/api/sessions/{sid}/share")
def revoke_share_link(sid: str, db: DbSession = Depends(get_db)):
    s = db.get(Session, sid)
    if not s:
        raise HTTPException(404)
    s.share_token = None
    db.commit()
    return {"ok": True}


@router.get("/s/{token}", response_class=HTMLResponse)
def view_shared_session(token: str, db: DbSession = Depends(get_db)):
    s = db.query(Session).filter_by(share_token=token).first()
    if not s:
        return HTMLResponse("<html><body style='font:14px/1.6 sans-serif;padding:2rem;background:#0a0a0a;color:#e8e6e3'>"
                            "<h2>session not found or link revoked</h2></body></html>", status_code=404)
    msgs = [m for m in s.messages if m.role in ("user", "assistant")]
    rows = ""
    for m in msgs:
        role_label = "you" if m.role == "user" else s.model or "aide"
        bg = "#141414" if m.role == "assistant" else "transparent"
        rows += f"""<div style="padding:1rem 1.5rem;background:{bg};border-bottom:1px solid #1e1e1e">
            <div style="font-size:0.7rem;color:#6e6e6e;margin-bottom:0.4rem;text-transform:lowercase">{role_label}</div>
            <div style="white-space:pre-wrap;font-size:0.875rem;line-height:1.6">{_esc(m.content)}</div>
        </div>"""
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(s.name or 'aide session')}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh}}
  .header{{padding:1rem 1.5rem;border-bottom:1px solid #1e1e1e;display:flex;align-items:center;gap:0.75rem}}
  .brand{{font-size:0.8rem;color:#6e6e6e}}
  .title{{font-size:0.95rem;font-weight:500}}
  .badge{{font-size:0.65rem;color:#818cf8;border:1px solid #818cf8;border-radius:2px;padding:0.1rem 0.35rem}}
  @media print{{.no-print{{display:none}}}}
</style>
</head><body>
<div class="header no-print">
  <span class="brand">aide</span>
  <span class="title">{_esc(s.name or 'untitled')}</span>
  <span class="badge">read-only</span>
  <button onclick="window.print()" style="margin-left:auto;background:none;border:1px solid #2e2e2e;color:#e8e6e3;padding:0.25rem 0.75rem;cursor:pointer;font-size:0.72rem;border-radius:2px">print</button>
</div>
<div>{rows if rows else '<div style="padding:2rem;color:#6e6e6e">no messages</div>'}</div>
</body></html>""")


def _esc(s=""):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
