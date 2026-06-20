import mimetypes
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import (
    Album,
    BookingPage,
    CalendarEvent,
    EventAttendee,
    Persona,
    PersonaDoc,
    Photo,
    Session,
    Share,
    VaultShare,
    get_db,
)
from services import files_store, photos_store, share, vault_md

router = APIRouter()


# ── legacy session share (unchanged, back-compat) ─────────────────────────────
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


# ── generic share/publish (1a) ────────────────────────────────────────────────
class ShareBody(BaseModel):
    kind: str
    ref: str
    level: str | None = "view"


class ShareRef(BaseModel):
    kind: str
    ref: str


@router.post("/api/share")
def create_share(body: ShareBody, db: DbSession = Depends(get_db)):
    try:
        s = share.mint(db, body.kind, body.ref, body.level or "view")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "token": s.token,
        "url": f"/s/{s.token}",
        "kind": s.kind,
        "ref": s.ref,
        "level": s.level,
    }


@router.get("/api/share")
def get_share(kind: str, ref: str, db: DbSession = Depends(get_db)):
    tok = share.token_for(db, kind, ref)
    return {"token": tok, "url": f"/s/{tok}" if tok else None}


@router.delete("/api/share")
def delete_share(body: ShareRef, db: DbSession = Depends(get_db)):
    return {"ok": share.revoke_ref(db, body.kind, body.ref)}


# ── public read-only viewer ───────────────────────────────────────────────────
def _not_found():
    return HTMLResponse(
        "<html><body style='font:14px/1.6 sans-serif;padding:2rem;background:#0a0a0a;color:#e8e6e3'>"
        "<h2>not found or link revoked</h2></body></html>",
        status_code=404,
    )


@router.get("/s/{token}", response_class=HTMLResponse)
def view_shared(token: str, db: DbSession = Depends(get_db)):
    sh = share.lookup(db, token)
    if sh:
        if sh.kind == "doc":
            doc = vault_md.read(sh.ref)
            if not doc.get("exists"):
                return _not_found()
            name = sh.ref.rsplit("/", 1)[-1].removesuffix(".md")
            body = share.md_to_html(doc["content"])
            # navigable site: link [[wikilinks]] to other published docs (3c)
            pubs = {}
            for s in db.query(Share).filter_by(kind="doc").all():
                pubs[s.ref.rsplit("/", 1)[-1].removesuffix(".md").lower()] = s.token
            body = _link_published(body, pubs)
            return HTMLResponse(_doc_html(name, body))
        if sh.kind == "file":
            try:
                p = files_store.abspath(sh.ref)
            except ValueError:
                return _not_found()
            if not p.exists() or not p.is_file():
                return _not_found()
            mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            disp = "attachment" if sh.level == "download" else "inline"
            return FileResponse(p, media_type=mt, filename=p.name, content_disposition_type=disp)
        if sh.kind == "folder":
            try:
                base = files_store.abspath(sh.ref)
            except ValueError:
                return _not_found()
            if not base.exists() or not base.is_dir():
                return _not_found()
            entries = []
            for fp in sorted(base.rglob("*")):
                if not fp.is_file():
                    continue
                rel = fp.relative_to(base)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                entries.append((str(rel).replace("\\", "/"), fp.stat().st_size))
            name = sh.ref.rstrip("/").rsplit("/", 1)[-1] or "files"
            return HTMLResponse(_folder_html(name, token, entries, sh.level))
        if sh.kind == "photo":
            ph = db.get(Photo, sh.ref)
            if not ph:
                return _not_found()
            p = photos_store.photos_dir() / ph.filename
            if not p.exists():
                return _not_found()
            mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return FileResponse(p, media_type=mt, content_disposition_type="inline")
        if sh.kind == "album":
            alb = db.get(Album, sh.ref)
            if not alb:
                return _not_found()
            photos = (
                db.query(Photo)
                .filter(
                    Photo.album_id == sh.ref,
                    Photo.deleted_at == None,  # noqa: E711
                    (Photo.hidden == False) | (Photo.hidden == None),  # noqa: E711,E712
                )
                .order_by(Photo.taken_at.desc())
                .all()
            )
            return HTMLResponse(_album_html(alb.name, token, photos))
        if sh.kind == "persona":  # 10d — a shareable custom-assistant bundle
            p = db.get(Persona, sh.ref)
            if not p:
                return _not_found()
            docs = db.query(PersonaDoc).filter(PersonaDoc.persona_id == p.id).all()
            return HTMLResponse(_doc_html(p.name, _persona_bundle_html(p, docs)))
        # contact/event share land here in their own stages (8/9)
        return _not_found()

    # fallback: legacy session share
    s = db.query(Session).filter_by(share_token=token).first()
    if not s:
        return _not_found()
    return HTMLResponse(_session_html(s))


@router.get("/s/{token}/{subpath:path}")
def view_shared_child(token: str, subpath: str, db: DbSession = Depends(get_db)):
    """serve a single resource inside a shared folder/album, confined to it (no traversal)."""
    sh = share.lookup(db, token)
    if not sh:
        return _not_found()
    if sh.kind == "album":
        ph = db.get(Photo, subpath)
        if not ph or ph.album_id != sh.ref or ph.deleted_at is not None or ph.hidden:
            return _not_found()
        p = photos_store.photos_dir() / ph.filename
        if not p.is_file():
            return _not_found()
        mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return FileResponse(p, media_type=mt, content_disposition_type="inline")
    if sh.kind != "folder":
        return _not_found()
    try:
        base = files_store.abspath(sh.ref)
        target = (base / subpath).resolve()
    except (ValueError, OSError):
        return _not_found()
    # must stay inside the shared folder
    if base != target and base not in target.parents:
        return _not_found()
    if not target.is_file():
        return _not_found()
    mt = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    disp = "attachment" if sh.level == "download" else "inline"
    return FileResponse(target, media_type=mt, filename=target.name, content_disposition_type=disp)


_RSVP_STATUSES = {"invited", "accepted", "declined", "tentative"}


class RsvpBody(BaseModel):
    status: str


@router.post("/rsvp/{token}")
def rsvp(token: str, body: RsvpBody, db: DbSession = Depends(get_db)):
    att = db.query(EventAttendee).filter(EventAttendee.token == token).first()
    if not att:
        raise HTTPException(404)
    if body.status not in _RSVP_STATUSES:
        raise HTTPException(400, "bad status")
    att.status = body.status
    db.commit()
    return {"ok": True, "status": att.status}


@router.get("/rsvp/{token}", response_class=HTMLResponse)
def rsvp_page(token: str, db: DbSession = Depends(get_db)):
    att = db.query(EventAttendee).filter(EventAttendee.token == token).first()
    if not att:
        return _not_found()
    ev = db.get(CalendarEvent, att.event_id)
    title = ev.title if ev else "event"
    when = ev.start_dt if ev else ""
    return HTMLResponse(_rsvp_html(token, title, when, att.status))


def _rsvp_html(token, title, when, status):
    btn = lambda s, label: (  # noqa: E731
        f'<button class="rb{" sel" if status == s else ""}" onclick="rs(\'{s}\')">{label}</button>'
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RSVP — {_esc(title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
  .card{{max-width:420px;padding:2rem;text-align:center}}
  h1{{font-size:1.1rem;margin-bottom:.3rem}} .when{{color:#6e6e6e;font-size:.8rem;margin-bottom:1.4rem}}
  .rb{{background:#161616;color:#e8e6e3;border:1px solid #2a2a2a;border-radius:3px;padding:.5rem .9rem;margin:.2rem;cursor:pointer;font-size:.8rem}}
  .rb.sel{{border-color:#818cf8;color:#818cf8}} .rb:hover{{background:#222}}
  #msg{{margin-top:1rem;color:#4ade80;font-size:.8rem;min-height:1.2em}}
</style></head><body>
<div class="card">
  <h1>{_esc(title)}</h1><div class="when">{_esc(when)}</div>
  <div>{btn("accepted", "Yes")}{btn("tentative", "Maybe")}{btn("declined", "No")}</div>
  <div id="msg"></div>
</div>
<script>
async function rs(s){{
  const r = await fetch('/rsvp/{token}', {{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{status:s}})}});
  if(r.ok){{ document.querySelectorAll('.rb').forEach(b=>b.classList.remove('sel'));
    event.target.classList.add('sel'); document.getElementById('msg').textContent='response saved — thanks!'; }}
}}
</script></body></html>"""


@router.get("/book/{token}/slots")
def book_slots(token: str, date: str, db: DbSession = Depends(get_db)):
    from routes.calendar import compute_booking_slots

    page = db.query(BookingPage).filter(BookingPage.token == token).first()
    if not page:
        raise HTTPException(404)
    return {"slots": compute_booking_slots(db, page, date)}


class BookBody(BaseModel):
    date: str
    time: str
    name: str = ""
    email: str = ""


@router.post("/book/{token}")
def book(token: str, body: BookBody, db: DbSession = Depends(get_db)):
    from routes.calendar import compute_booking_slots

    page = db.query(BookingPage).filter(BookingPage.token == token).first()
    if not page:
        raise HTTPException(404)
    start = f"{body.date}T{body.time}:00" if len(body.time) == 5 else f"{body.date}T{body.time}"
    want = f"{body.date}T{body.time}"[:16]
    slots = compute_booking_slots(db, page, body.date)
    if not any(s["start"][:16] == want for s in slots):
        raise HTTPException(409, "that time isn't available")
    from datetime import datetime, timedelta

    end = (datetime.fromisoformat(start) + timedelta(minutes=page.duration_min)).isoformat()
    ev = CalendarEvent(
        title=f"{page.title}: {body.name}".strip(": "),
        start_dt=start,
        end_dt=end,
        calendar_id=page.calendar_id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    db.add(EventAttendee(event_id=ev.id, name=body.name, email=body.email, status="accepted"))
    db.commit()
    return {"ok": True, "event_id": ev.id, "start": start, "end": end}


@router.get("/book/{token}", response_class=HTMLResponse)
def book_page(token: str, db: DbSession = Depends(get_db)):
    page = db.query(BookingPage).filter(BookingPage.token == token).first()
    if not page:
        return _not_found()
    return HTMLResponse(_book_html(token, page.title, page.days_ahead))


def _book_html(token, title, days_ahead):
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh}}
  .wrap{{max-width:560px;margin:0 auto;padding:2rem}}
  h1{{font-size:1.1rem;margin-bottom:1rem}}
  label{{display:block;font-size:.72rem;color:#6e6e6e;margin:.6rem 0 .2rem}}
  input,select{{width:100%;background:#161616;color:#e8e6e3;border:1px solid #2a2a2a;border-radius:3px;padding:.45rem;font-size:.85rem}}
  #slots{{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.4rem}}
  .slot{{background:#161616;border:1px solid #2a2a2a;border-radius:3px;padding:.35rem .6rem;cursor:pointer;font-size:.78rem}}
  .slot.sel{{border-color:#818cf8;color:#818cf8}} .slot:hover{{background:#222}}
  button.go{{margin-top:1rem;background:#818cf8;color:#0a0a0a;border:none;border-radius:3px;padding:.5rem 1rem;cursor:pointer;font-size:.82rem}}
  #msg{{margin-top:1rem;color:#4ade80;font-size:.82rem;min-height:1.2em}}
</style></head><body>
<div class="wrap">
  <h1>{_esc(title)}</h1>
  <label>date</label><input type="date" id="date">
  <div id="slots"></div>
  <label>your name</label><input id="name">
  <label>your email</label><input id="email" type="email">
  <button class="go" onclick="submit()">book</button>
  <div id="msg"></div>
</div>
<script>
const token = '{token}';
let picked = null;
const dEl = document.getElementById('date');
const today = new Date(); dEl.value = today.toISOString().slice(0,10);
dEl.min = dEl.value;
dEl.addEventListener('change', loadSlots);
async function loadSlots(){{
  picked = null;
  const r = await fetch(`/book/${{token}}/slots?date=${{dEl.value}}`).then(r=>r.json()).catch(()=>({{slots:[]}}));
  const box = document.getElementById('slots');
  box.innerHTML = r.slots.length ? '' : '<span style="color:#6e6e6e;font-size:.78rem">no free times that day</span>';
  for (const s of r.slots){{
    const b = document.createElement('div'); b.className='slot'; b.textContent = s.start.slice(11,16);
    b.onclick = () => {{ document.querySelectorAll('.slot').forEach(x=>x.classList.remove('sel')); b.classList.add('sel'); picked = s.start.slice(11,16); }};
    box.appendChild(b);
  }}
}}
async function submit(){{
  if(!picked){{ document.getElementById('msg').style.color='#f87171'; document.getElementById('msg').textContent='pick a time first'; return; }}
  const r = await fetch(`/book/${{token}}`, {{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{date:dEl.value,time:picked,name:document.getElementById('name').value,email:document.getElementById('email').value}})}});
  const m = document.getElementById('msg');
  if(r.ok){{ m.style.color='#4ade80'; m.textContent='booked! see you then.'; loadSlots(); }}
  else {{ m.style.color='#f87171'; m.textContent='that time just got taken — pick another'; loadSlots(); }}
}}
loadSlots();
</script></body></html>"""


_NOSTORE = {"Cache-Control": "no-store, max-age=0"}


@router.get("/sv/{token}/data")
def vault_share_data(token: str, db: DbSession = Depends(get_db)):
    from fastapi.responses import JSONResponse

    sh = db.query(VaultShare).filter(VaultShare.token == token).first()
    if not sh:
        raise HTTPException(404)
    return JSONResponse({"blob": sh.blob}, headers=_NOSTORE)


@router.get("/sv/{token}", response_class=HTMLResponse)
def vault_share_page(token: str, db: DbSession = Depends(get_db)):
    sh = db.query(VaultShare).filter(VaultShare.token == token).first()
    if not sh:
        return _not_found()
    return HTMLResponse(_vshare_html(token), headers=_NOSTORE)


def _vshare_html(token):
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>shared item</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
  .card{{max-width:460px;width:90%;padding:1.5rem;border:1px solid #1e1e1e;border-radius:4px}}
  h1{{font-size:1rem;margin-bottom:1rem}}
  .row{{display:flex;justify-content:space-between;gap:1rem;padding:.5rem 0;border-bottom:1px solid #161616;font-size:.85rem}}
  .k{{color:#6e6e6e}} .v{{font-family:monospace;word-break:break-all;text-align:right}}
  .badge{{font-size:.62rem;color:#818cf8;border:1px solid #818cf8;border-radius:2px;padding:.1rem .35rem}}
  .err{{color:#f87171;font-size:.85rem}}
</style></head><body>
<div class="card">
  <h1 id="title">shared item <span class="badge">read-only</span></h1>
  <div id="body"><div class="err" id="err" style="display:none">could not decrypt — the link may be incomplete</div></div>
</div>
<script>
const token = '{token}';
function b64ToBytes(b64){{ const s = atob(b64.replace(/-/g,'+').replace(/_/g,'/')); const a = new Uint8Array(s.length); for(let i=0;i<s.length;i++) a[i]=s.charCodeAt(i); return a; }}
async function go(){{
  const keyB64 = location.hash.slice(1);
  if(!keyB64){{ document.getElementById('err').style.display='block'; return; }}
  try{{
    const d = await fetch(`/sv/${{token}}/data`).then(r=>r.json());
    const blob = b64ToBytes(d.blob);
    const iv = blob.slice(0,12), ct = blob.slice(12);
    const key = await crypto.subtle.importKey('raw', b64ToBytes(keyB64), 'AES-GCM', false, ['decrypt']);
    const pt = await crypto.subtle.decrypt({{name:'AES-GCM', iv}}, key, ct);
    const obj = JSON.parse(new TextDecoder().decode(pt));
    document.getElementById('title').firstChild.textContent = (obj.name || 'shared item') + ' ';
    const rows = Object.entries(obj.fields||{{}}).filter(([k,v])=>v).map(([k,v])=>
      `<div class="row"><span class="k">${{k}}</span><span class="v">${{String(v).replace(/</g,'&lt;')}}</span></div>`).join('');
    document.getElementById('body').innerHTML = rows || '<div class="k">(empty)</div>';
  }} catch(e) {{ document.getElementById('err').style.display='block'; }}
}}
go();
</script></body></html>"""


def _fmt_sz(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024 / 1024 / 1024:.1f} GB"


def _folder_html(title, token, entries, level):
    rows = (
        "".join(
            f'<li><a href="/s/{token}/{quote(rel)}">{_esc(rel)}</a>'
            f'<span class="sz">{_fmt_sz(sz)}</span></li>'
            for rel, sz in entries
        )
        or '<li class="empty">empty folder</li>'
    )
    badge = "download" if level == "download" else "read-only"
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh}}
  .header{{padding:1rem 1.5rem;border-bottom:1px solid #1e1e1e;display:flex;align-items:center;gap:0.75rem}}
  .brand{{font-size:0.8rem;color:#6e6e6e}}
  .title{{font-size:0.95rem;font-weight:500}}
  .badge{{font-size:0.65rem;color:#818cf8;border:1px solid #818cf8;border-radius:2px;padding:0.1rem 0.35rem}}
  .wrap{{max-width:760px;margin:0 auto;padding:1.5rem}}
  ul{{list-style:none}}
  li{{display:flex;justify-content:space-between;align-items:center;padding:0.45rem 0.2rem;border-bottom:1px solid #1a1a1a}}
  li.empty{{color:#6e6e6e;justify-content:flex-start}}
  a{{color:#818cf8;text-decoration:none;word-break:break-all}} a:hover{{text-decoration:underline}}
  .sz{{font-size:0.68rem;color:#6e6e6e;white-space:nowrap;margin-left:1rem}}
</style>
</head><body>
<div class="header">
  <span class="brand">alles</span>
  <span class="title">{_esc(title)}</span>
  <span class="badge">{badge}</span>
</div>
<div class="wrap"><ul>{rows}</ul></div>
</body></html>"""


def _album_html(title, token, photos):
    cells = (
        "".join(
            f'<a class="cell" href="/s/{token}/{p.id}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="/s/{token}/{p.id}" alt="{_esc(p.caption or "")}"></a>'
            for p in photos
        )
        or '<p class="empty">this album is empty</p>'
    )
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh}}
  .header{{padding:1rem 1.5rem;border-bottom:1px solid #1e1e1e;display:flex;align-items:center;gap:0.75rem}}
  .brand{{font-size:0.8rem;color:#6e6e6e}}
  .title{{font-size:0.95rem;font-weight:500}}
  .badge{{font-size:0.65rem;color:#818cf8;border:1px solid #818cf8;border-radius:2px;padding:0.1rem 0.35rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:4px;padding:1.5rem;max-width:1100px;margin:0 auto}}
  .cell{{aspect-ratio:1;overflow:hidden;border-radius:3px;background:#161616;display:block}}
  .cell img{{width:100%;height:100%;object-fit:cover;display:block}}
  .empty{{color:#6e6e6e;padding:2.5rem;text-align:center}}
</style>
</head><body>
<div class="header">
  <span class="brand">alles</span>
  <span class="title">{_esc(title)}</span>
  <span class="badge">read-only</span>
</div>
<div class="grid">{cells}</div>
</body></html>"""


def _persona_bundle_html(p, docs):
    """a public, read-only assistant bundle — copy the prompt to recreate it in your own aide (10d)."""
    parts = [f"<h1>{_esc(p.emoji)} {_esc(p.name)}</h1>"]
    if p.model:
        parts.append(f"<p><strong>model:</strong> {_esc(p.model)}</p>")
    parts.append(
        "<h2>system prompt</h2><pre><code>" + _esc(p.system_prompt or "") + "</code></pre>"
    )
    if p.initial_message:
        parts.append("<h2>opening message</h2><p>" + _esc(p.initial_message) + "</p>")
    if docs:
        items = "".join(f"<li>{_esc(d.title)}</li>" for d in docs)
        parts.append(f"<h2>knowledge files</h2><ul>{items}</ul>")
    parts.append(
        "<p style='color:#6e6e6e;margin-top:1.5rem'>Copy this into a new persona in your own "
        "aide to use this assistant.</p>"
    )
    return "".join(parts)


def _doc_html(title, body_html):
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0a0a;color:#e8e6e3;font-family:Inter,-apple-system,sans-serif;min-height:100vh}}
  .header{{padding:1rem 1.5rem;border-bottom:1px solid #1e1e1e;display:flex;align-items:center;gap:0.75rem}}
  .brand{{font-size:0.8rem;color:#6e6e6e}}
  .title{{font-size:0.95rem;font-weight:500}}
  .badge{{font-size:0.65rem;color:#818cf8;border:1px solid #818cf8;border-radius:2px;padding:0.1rem 0.35rem}}
  .doc{{max-width:760px;margin:0 auto;padding:2rem 1.5rem;line-height:1.7}}
  .doc h1,.doc h2,.doc h3{{margin:1.2rem 0 0.6rem}} .doc p{{margin:0.6rem 0}}
  .doc ul,.doc ol{{margin:0.6rem 0 0.6rem 1.4rem}} .doc a{{color:#818cf8}}
  .doc code{{background:#141414;padding:0.1rem 0.3rem;border-radius:2px}}
  .doc pre{{background:#141414;padding:0.8rem;border-radius:3px;overflow:auto}}
  .doc pre code{{background:none;padding:0}}
  @media print{{.no-print{{display:none}}}}
</style>
</head><body>
<div class="header no-print">
  <span class="brand">alles</span>
  <span class="title">{_esc(title)}</span>
  <span class="badge">read-only</span>
</div>
<div class="doc">{body_html}</div>
</body></html>"""


def _session_html(s):
    msgs = [m for m in s.messages if m.role in ("user", "assistant")]
    rows = ""
    for m in msgs:
        role_label = "you" if m.role == "user" else s.model or "aide"
        bg = "#141414" if m.role == "assistant" else "transparent"
        rows += f"""<div style="padding:1rem 1.5rem;background:{bg};border-bottom:1px solid #1e1e1e">
            <div style="font-size:0.7rem;color:#6e6e6e;margin-bottom:0.4rem;text-transform:lowercase">{role_label}</div>
            <div style="white-space:pre-wrap;font-size:0.875rem;line-height:1.6">{_esc(m.content)}</div>
        </div>"""
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(s.name or "aide session")}</title>
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
  <span class="title">{_esc(s.name or "untitled")}</span>
  <span class="badge">read-only</span>
  <button onclick="window.print()" style="margin-left:auto;background:none;border:1px solid #2e2e2e;color:#e8e6e3;padding:0.25rem 0.75rem;cursor:pointer;font-size:0.72rem;border-radius:2px">print</button>
</div>
<div>{rows if rows else '<div style="padding:2rem;color:#6e6e6e">no messages</div>'}</div>
</body></html>"""


def _link_published(html, pubs):
    """rewrite [[name]] → a link to that doc's public page if published, else plain text."""

    def repl(m):
        name = m.group(1).strip()
        alias = (m.group(2) or name).strip()
        tok = pubs.get(name.lower())
        return f'<a href="/s/{tok}">{_esc(alias)}</a>' if tok else _esc(alias)

    return re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", repl, html)


def _esc(s=""):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
