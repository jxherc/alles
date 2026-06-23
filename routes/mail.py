import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import MailAccount, MailDraft, get_db
from services import mail as mailsvc
from services import mail_oauth

router = APIRouter(prefix="/api/mail")


def _draft_fmt(d: MailDraft) -> dict:
    return {
        "id": d.id,
        "account_id": d.account_id,
        "to": d.to,
        "cc": d.cc,
        "bcc": d.bcc,
        "subject": d.subject,
        "body": d.body,
        "in_reply_to": d.in_reply_to,
        "references": d.references,
        "updated_at": d.updated_at.isoformat() if d.updated_at else "",
    }


class DraftBody(BaseModel):
    id: str = ""
    account_id: str = ""
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    body: str = ""
    in_reply_to: str = ""
    references: str = ""


@router.post("/drafts")
def save_draft(body: DraftBody, db: DbSession = Depends(get_db)):
    d = db.get(MailDraft, body.id) if body.id else None
    if not d:
        d = MailDraft()
        db.add(d)
    for f in ("account_id", "to", "cc", "bcc", "subject", "body", "in_reply_to", "references"):
        setattr(d, f, getattr(body, f))
    db.commit()
    db.refresh(d)
    return _draft_fmt(d)


@router.get("/recipients")
def recipients(q: str = "", limit: int = 12, db: DbSession = Depends(get_db)):
    """address-autocomplete source (4d): distinct correspondents from the mail cache,
    optionally filtered by a substring. names are kept so the picker can show 'Name <addr>'."""
    import re

    from core.database import CachedMessage

    seen, out = set(), []
    ql = (q or "").strip().lower()
    rows = (
        db.query(CachedMessage.sender)
        .filter(CachedMessage.sender != "")
        .order_by(CachedMessage.date_ts.desc())
        .limit(2000)
        .all()
    )
    for (sender,) in rows:
        m = re.search(r"([^<>\s]+@[^<>\s]+)", sender or "")
        if not m:
            continue
        addr = m.group(1).strip().strip(",;")
        name = re.sub(r"<[^>]*>", "", sender).strip().strip('"').strip()
        key = addr.lower()
        if key in seen:
            continue
        if ql and ql not in key and ql not in name.lower():
            continue
        seen.add(key)
        out.append({"email": addr, "name": name if name and name.lower() != key else ""})
        if len(out) >= max(1, min(limit, 50)):
            break
    return {"recipients": out}


@router.get("/drafts")
def list_drafts(account_id: str = "", db: DbSession = Depends(get_db)):
    q = db.query(MailDraft)
    if account_id:
        q = q.filter(MailDraft.account_id == account_id)
    return [_draft_fmt(d) for d in q.order_by(MailDraft.updated_at.desc()).all()]


@router.get("/drafts/{did}")
def get_draft(did: str, db: DbSession = Depends(get_db)):
    d = db.get(MailDraft, did)
    if not d:
        raise HTTPException(404, "draft not found")
    return _draft_fmt(d)


@router.delete("/drafts/{did}")
def delete_draft(did: str, db: DbSession = Depends(get_db)):
    d = db.get(MailDraft, did)
    if d:
        db.delete(d)
        db.commit()
    return {"ok": True}


def _acct_dict(a: MailAccount) -> dict:
    return {
        "id": a.id,
        "imap_host": a.imap_host,
        "imap_port": a.imap_port,
        "smtp_host": a.smtp_host,
        "smtp_port": a.smtp_port,
        "username": a.username,
        "password": a.password,
        "email": a.email,
        "use_ssl": a.use_ssl,
        "auth_type": a.auth_type,
        "oauth_access_token": a.oauth_access_token,
        "oauth_refresh_token": a.oauth_refresh_token,
        "oauth_expires_at": a.oauth_expires_at,
    }


def _fmt(a: MailAccount) -> dict:  # never leaks the password or tokens
    return {
        "id": a.id,
        "name": a.name,
        "email": a.email,
        "imap_host": a.imap_host,
        "imap_port": a.imap_port,
        "smtp_host": a.smtp_host,
        "smtp_port": a.smtp_port,
        "username": a.username,
        "use_ssl": a.use_ssl,
        "auth_type": a.auth_type,
        "oauth_provider": a.oauth_provider,
    }


def _get(db, aid) -> MailAccount:
    a = db.get(MailAccount, aid)
    if not a:
        raise HTTPException(404, "account not found")
    return a


@router.get("/accounts")
def accounts(db: DbSession = Depends(get_db)):
    return [_fmt(a) for a in db.query(MailAccount).order_by(MailAccount.created_at).all()]


class AcctBody(BaseModel):
    name: str = ""
    email: str = ""
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    use_ssl: bool = True


@router.post("/accounts")
def add_account(body: AcctBody, db: DbSession = Depends(get_db)):
    a = MailAccount(**body.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    mailsvc.clear_cache()
    return _fmt(a)


@router.patch("/accounts/{aid}")
def patch_account(aid: str, body: AcctBody, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    data = body.model_dump()
    if not data.get("password"):
        data.pop("password")  # keep the existing password if the form left it blank
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    mailsvc.clear_cache()
    return _fmt(a)


@router.delete("/accounts/{aid}")
def del_account(aid: str, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    db.delete(a)
    db.commit()
    mailsvc.clear_cache()
    return {"ok": True}


# these hit the network (sync def → runs in a threadpool)
@router.get("/test/{aid}")
def test(aid: str, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.check(_acct_dict(a))
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── google oauth ("sign in with google") ──────────────────────────────────────
@router.get("/oauth/status")
def oauth_status():
    return {"configured": mail_oauth.configured(), "redirect_uri": mail_oauth.redirect_uri()}


@router.get("/oauth/google/start")
def oauth_start():
    if not mail_oauth.configured():
        raise HTTPException(400, "google oauth not configured")
    return RedirectResponse(mail_oauth.auth_url(mail_oauth.make_state()))


@router.get("/oauth/google/callback")
def oauth_callback(
    code: str = "", state: str = "", error: str = "", db: DbSession = Depends(get_db)
):
    def _back(status):
        return RedirectResponse(f"/?mailoauth={status}")

    if error:
        return _back("denied")
    if not mail_oauth.check_state(state):
        return _back("badstate")
    try:
        tok = mail_oauth.exchange_code(code)
        access = tok.get("access_token", "")
        email = mail_oauth.fetch_email(access)
    except Exception:
        return _back("failed")
    if not email:
        return _back("noemail")

    a = db.query(MailAccount).filter(MailAccount.email == email).first()
    if not a:
        a = MailAccount(email=email, name=email)
        db.add(a)
    a.auth_type = "oauth"
    a.oauth_provider = "google"
    a.username = email
    a.password = ""  # oauth accounts carry no password
    a.imap_host, a.imap_port = mail_oauth.GMAIL_IMAP
    a.smtp_host, a.smtp_port = mail_oauth.GMAIL_SMTP
    a.use_ssl = True
    a.oauth_access_token = access
    if tok.get("refresh_token"):  # google only returns it on first consent
        a.oauth_refresh_token = tok["refresh_token"]
    a.oauth_expires_at = time.time() + int(tok.get("expires_in", 3600))
    db.commit()
    mailsvc.clear_cache()
    return _back("ok")


@router.get("/inbox/{aid}")
def inbox(
    aid: str,
    folder: str = "INBOX",
    limit: int = 30,
    quick: bool = False,
    db: DbSession = Depends(get_db),
):
    from services import mail_cache

    a = _get(db, aid)
    try:
        msgs = mailsvc.fetch_inbox(_acct_dict(a), folder, limit, quick=quick)
        try:
            mail_cache.save(db, aid, folder, msgs)  # warm the cache for instant/offline reads
        except Exception:
            pass
        return {"messages": msgs}
    except Exception as e:
        # network slow/down → serve the last cached copy so the inbox isn't just blank
        cached = mail_cache.get(db, aid, folder, limit)
        return {"error": str(e)[:200], "messages": cached, "cached": bool(cached)}


@router.get("/unified")
def unified(limit: int = 50, db: DbSession = Depends(get_db)):
    """one inbox across every account, from the cache (instant/offline)."""
    from services import mail_cache

    return {"messages": mail_cache.get_unified(db, limit)}


@router.get("/smart/{aid}")
def smart(aid: str, filter: str = "unread", limit: int = 50, db: DbSession = Depends(get_db)):
    """smart mailbox over the cache: filter = unread | flagged | vip."""
    from services import mail_cache

    _get(db, aid)
    if filter == "vip":
        from core.settings import load_settings

        vips = load_settings().get("mail_vips", [])
        rows = mail_cache.get(db, aid, "INBOX", limit)
        return {"messages": [m for m in rows if mailsvc.is_vip(m.get("from", ""), vips)]}
    msgs = mail_cache.get_filtered(
        db, aid, unread=(filter == "unread"), flagged=(filter == "flagged"), limit=limit
    )
    return {"messages": msgs}


@router.post("/read/{aid}")
def read(
    aid: str, uid: str, seen: bool = True, folder: str = "INBOX", db: DbSession = Depends(get_db)
):
    """mark read/unread — cache is the source of truth, IMAP is best-effort."""
    from services import mail_cache

    a = _get(db, aid)
    mail_cache.set_seen(db, aid, folder, uid, seen)
    try:
        mailsvc.set_seen(_acct_dict(a), uid, seen, folder)
    except Exception:
        pass
    return {"ok": True, "seen": seen}


class VipBody(BaseModel):
    email: str
    add: bool = True


@router.get("/vips")
def get_vips():
    from core.settings import load_settings

    return {"vips": load_settings().get("mail_vips", [])}


@router.post("/vips")
def set_vip(body: VipBody):
    from core.settings import load_settings, save_settings

    vips = [v for v in load_settings().get("mail_vips", []) if v]
    e = body.email.strip().lower()
    if body.add and e and e not in vips:
        vips.append(e)
    elif not body.add:
        vips = [v for v in vips if v.lower() != e]
    save_settings({"mail_vips": vips})
    return {"vips": vips}


@router.post("/flag/{aid}")
def flag(
    aid: str,
    uid: str,
    flagged: bool = True,
    folder: str = "INBOX",
    db: DbSession = Depends(get_db),
):
    """star/flag a message — local cache is the source of truth, IMAP is best-effort."""
    from services import mail_cache

    a = _get(db, aid)
    mail_cache.set_flag(db, aid, folder, uid, flagged)
    try:
        mailsvc.set_flag(_acct_dict(a), uid, flagged, folder)
    except Exception:
        pass  # cache already updated; IMAP sync is best-effort
    return {"ok": True, "flagged": flagged}


@router.get("/cached/{aid}")
def cached_inbox(aid: str, folder: str = "INBOX", limit: int = 30, db: DbSession = Depends(get_db)):
    """instant inbox from the local cache — no IMAP round-trip."""
    from services import mail_cache

    _get(db, aid)
    return {"messages": mail_cache.get(db, aid, folder, limit), "cached": True}


@router.get("/cache-search/{aid}")
def cache_search(aid: str, q: str, limit: int = 40, db: DbSession = Depends(get_db)):
    """instant local search over cached headers (offline-friendly)."""
    from services import mail_cache

    _get(db, aid)
    return {"messages": mail_cache.search(db, aid, q, limit), "cached": True}


# ── triage: advanced search, mute, archive, saved searches (5a) ───────────────
@router.get("/adv-search/{aid}")
def adv_search(aid: str, q: str = "", limit: int = 50, db: DbSession = Depends(get_db)):
    """cache search honoring from:/subject:/before:/after:/text operators."""
    from services import mail_cache

    _get(db, aid)
    spec = mailsvc.parse_search_query(q)
    return {
        "messages": mail_cache.advanced_search(db, aid, spec, limit),
        "spec": spec,
        "cached": True,
    }


@router.get("/smart-search/{aid}")
def smart_search(aid: str, q: str = "", limit: int = 200, db: DbSession = Depends(get_db)):
    """2j - boolean smart mailbox: (from:x OR subject:y) AND NOT label:z over the cache."""
    from services import mail_cache, mail_predicate

    _get(db, aid)
    rows = mail_cache.get_filtered(db, aid, limit=max(limit, 500))
    msgs = mail_predicate.match(q, rows)[:limit]
    return {"messages": msgs, "count": len(msgs), "query": q}


class MuteBody(BaseModel):
    subject: str


@router.post("/mute/{aid}")
def mute_thread(aid: str, body: MuteBody, db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"muted": mail_cache.mute(db, aid, body.subject)}


class ArchiveBody(BaseModel):
    uid: str
    folder: str = "INBOX"


@router.post("/archive/{aid}")
def archive_message(aid: str, body: ArchiveBody, db: DbSession = Depends(get_db)):
    from services import mail_cache

    acct = _get(db, aid)
    # best-effort IMAP move to an Archive folder; never blocks the local archive
    try:
        mailsvc.move_message(acct, body.uid, "Archive", body.folder)
    except Exception:
        pass
    return {"archived": mail_cache.archive(db, aid, body.folder, body.uid)}


class MoveBody(BaseModel):
    uid: str
    dest: str
    folder: str = "INBOX"


@router.post("/move/{aid}")
def move_message(aid: str, body: MoveBody, db: DbSession = Depends(get_db)):
    """2h - move a message to another IMAP folder (best-effort server-side, drops it from cache)."""
    from services import mail_cache

    acct = _get(db, aid)
    moved = False
    try:
        mailsvc.move_message(acct, body.uid, body.dest, body.folder)
        moved = True
    except Exception:
        pass
    mail_cache.archive(db, aid, body.folder, body.uid)  # drop from the source cache view
    return {"ok": True, "moved_on_server": moved, "dest": body.dest}


class SavedSearchBody(BaseModel):
    name: str
    query: str = ""


@router.get("/saved-searches")
def list_saved_searches(db: DbSession = Depends(get_db)):
    from core.database import SavedSearch

    rows = db.query(SavedSearch).order_by(SavedSearch.created_at.asc()).all()
    return {"searches": [{"id": s.id, "name": s.name, "query": s.query or ""} for s in rows]}


@router.post("/saved-searches")
def add_saved_search(body: SavedSearchBody, db: DbSession = Depends(get_db)):
    from core.database import SavedSearch

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    s = SavedSearch(name=name, query=(body.query or "").strip())
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "query": s.query or ""}


@router.delete("/saved-searches/{sid}")
def delete_saved_search(sid: str, db: DbSession = Depends(get_db)):
    from core.database import SavedSearch

    s = db.get(SavedSearch, sid)
    if not s:
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    return {"ok": True}


# ── send control: schedule, undo, snooze (5b) ────────────────────────────────
def _sched_fmt(s):
    return {
        "id": s.id,
        "account_id": s.account_id,
        "to": s.to,
        "cc": s.cc,
        "bcc": s.bcc,
        "subject": s.subject,
        "body": s.body,
        "send_at": s.send_at,
        "status": s.status,
    }


class ScheduleBody(BaseModel):
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    body: str = ""
    html: str = ""
    in_reply_to: str = ""
    references: str = ""
    send_at: str = ""


@router.post("/schedule/{aid}")
def schedule_send(aid: str, body: ScheduleBody, db: DbSession = Depends(get_db)):
    from core.database import ScheduledMail

    _get(db, aid)
    s = ScheduledMail(account_id=aid, status="scheduled", **body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _sched_fmt(s)


class UndoableBody(BaseModel):
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    body: str = ""
    html: str = ""
    in_reply_to: str = ""
    references: str = ""
    delay: int = 10  # seconds the message sits in the outbox so you can undo


@router.post("/send-undoable/{aid}")
def send_undoable(aid: str, body: UndoableBody, db: DbSession = Depends(get_db)):
    """schedule a send a few seconds out so it can be undone (canceled) in the window."""
    from datetime import datetime, timedelta

    from core.database import ScheduledMail

    _get(db, aid)
    send_at = (datetime.utcnow() + timedelta(seconds=max(1, body.delay))).isoformat()
    data = body.model_dump()
    data.pop("delay", None)
    s = ScheduledMail(account_id=aid, status="scheduled", send_at=send_at, **data)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _sched_fmt(s)


@router.get("/scheduled")
def list_scheduled(db: DbSession = Depends(get_db)):
    from core.database import ScheduledMail

    rows = (
        db.query(ScheduledMail)
        .filter(ScheduledMail.status == "scheduled")
        .order_by(ScheduledMail.send_at.asc())
        .all()
    )
    return {"scheduled": [_sched_fmt(s) for s in rows]}


@router.post("/scheduled/{sid}/cancel")
def cancel_scheduled(sid: str, db: DbSession = Depends(get_db)):
    from core.database import ScheduledMail

    s = db.get(ScheduledMail, sid)
    if not s:
        raise HTTPException(404)
    s.status = "canceled"
    db.commit()
    return {"ok": True, "status": s.status}


class SnoozeBody(BaseModel):
    uid: str
    until: str
    folder: str = "INBOX"


@router.post("/snooze/{aid}")
def snooze_message(aid: str, body: SnoozeBody, db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"snoozed": mail_cache.snooze(db, aid, body.folder, body.uid, body.until)}


@router.get("/snoozed/{aid}")
def list_snoozed(aid: str, db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"snoozed": mail_cache.snoozed(db, aid)}


# ── signatures (5c) ───────────────────────────────────────────────────────────
class SignatureBody(BaseModel):
    id: str = ""
    name: str = ""
    body: str = ""


@router.get("/signatures")
def list_signatures():
    from core.settings import load_settings

    return {"signatures": load_settings().get("mail_signatures", [])}


@router.post("/signatures")
def save_signature(body: SignatureBody):
    import uuid

    from core.settings import load_settings, save_settings

    sigs = [s for s in load_settings().get("mail_signatures", []) if s.get("id")]
    sid = body.id or uuid.uuid4().hex
    row = {"id": sid, "name": (body.name or "signature").strip(), "body": body.body or ""}
    sigs = [s for s in sigs if s["id"] != sid] + [row]
    save_settings({"mail_signatures": sigs})
    return row


@router.delete("/signatures/{sid}")
def delete_signature(sid: str):
    from core.settings import load_settings, save_settings

    sigs = [s for s in load_settings().get("mail_signatures", []) if s.get("id") != sid]
    save_settings({"mail_signatures": sigs})
    return {"ok": True}


# ── rules engine, vacation responder, smart reply (5d) ───────────────────────
def _rule_fmt(r):
    return {
        "id": r.id,
        "match_field": r.match_field,
        "match_value": r.match_value,
        "action": r.action,
        "action_arg": r.action_arg or "",
        "enabled": bool(r.enabled),
    }


class RuleBody(BaseModel):
    match_field: str = "from"
    match_value: str = ""
    action: str = "markread"
    action_arg: str = ""
    enabled: bool = True


@router.get("/rules")
def list_rules(db: DbSession = Depends(get_db)):
    from core.database import MailRule

    rows = db.query(MailRule).order_by(MailRule.created_at.asc()).all()
    return {"rules": [_rule_fmt(r) for r in rows]}


@router.post("/rules")
def add_rule(body: RuleBody, db: DbSession = Depends(get_db)):
    from core.database import MailRule

    r = MailRule(
        match_field=body.match_field if body.match_field in ("from", "subject") else "from",
        match_value=(body.match_value or "").strip(),
        action=body.action
        if body.action in ("markread", "mute", "label", "autoreply")
        else "markread",
        action_arg=(body.action_arg or "").strip(),
        enabled=body.enabled,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _rule_fmt(r)


@router.delete("/rules/{rid}")
def delete_rule(rid: str, db: DbSession = Depends(get_db)):
    from core.database import MailRule

    r = db.get(MailRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/rules/run/{aid}")
def run_rules(aid: str, db: DbSession = Depends(get_db)):
    from core.database import MailRule
    from services import mail_rules

    _get(db, aid)
    rules = [_rule_fmt(r) for r in db.query(MailRule).filter(MailRule.enabled == True).all()]  # noqa: E712
    return {"applied": mail_rules.run_on_cache(db, aid, rules)}


class VacationBody(BaseModel):
    enabled: bool = False
    subject: str = "Out of office"
    body: str = ""


@router.get("/vacation")
def get_vacation():
    from core.settings import load_settings

    return load_settings().get(
        "mail_vacation", {"enabled": False, "subject": "Out of office", "body": ""}
    )


@router.post("/vacation")
def set_vacation(body: VacationBody):
    from core.settings import save_settings

    v = body.model_dump()
    save_settings({"mail_vacation": v})
    return v


@router.post("/vacation/run/{aid}")
def run_vacation(aid: str, db: DbSession = Depends(get_db)):
    """2g - send the vacation auto-reply (one per sender per day) for an account's inbox."""
    from datetime import date

    from core.settings import load_settings, save_settings
    from services import mail_rules

    _get(db, aid)
    cfg = load_settings()
    vac = cfg.get("mail_vacation", {"enabled": False})
    state = cfg.get("mail_vacation_state", {})
    n, new_state = mail_rules.run_vacation(db, aid, vac, state, date.today().isoformat())
    save_settings({"mail_vacation_state": new_state})
    return {"sent": n}


class SmartReplyBody(BaseModel):
    text: str = ""


@router.post("/smart-reply")
async def smart_reply(body: SmartReplyBody, db: DbSession = Depends(get_db)):
    """LLM reply suggestions — gated on an enabled model endpoint (disabled → empty)."""
    from core.database import ModelEndpoint

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()  # noqa: E712
    if not ep:
        return {"enabled": False, "suggestions": []}
    try:
        from services.llm import stream_chat

        prompt = (
            "Suggest exactly 3 short, distinct email replies to the message below. "
            "One per line, no numbering, no preamble.\n\n" + (body.text or "")[:4000]
        )
        model = (ep.models or "").split(",")[0].strip() if getattr(ep, "models", "") else ""
        out = ""
        async for chunk in stream_chat(
            [{"role": "user", "content": prompt}], ep.base_url, ep.api_key, model
        ):
            if chunk.get("delta"):
                out += chunk["delta"]
        suggestions = [s.strip("-• ").strip() for s in out.splitlines() if s.strip()][:3]
        return {"enabled": True, "suggestions": suggestions}
    except Exception as e:
        return {"enabled": True, "suggestions": [], "error": str(e)[:200]}


# ── labels + category tabs + idle (5e) ───────────────────────────────────────
class LabelsBody(BaseModel):
    uid: str
    labels: list[str] = []
    folder: str = "INBOX"


@router.post("/labels/{aid}")
def set_labels(aid: str, body: LabelsBody, db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"ok": bool(mail_cache.set_labels(db, aid, body.folder, body.uid, body.labels))}


@router.get("/by-label/{aid}")
def by_label(aid: str, label: str, db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"messages": mail_cache.by_label(db, aid, label)}


@router.get("/category/{aid}")
def category(aid: str, cat: str = "primary", db: DbSession = Depends(get_db)):
    from services import mail_cache

    _get(db, aid)
    return {"messages": mail_cache.by_category(db, aid, cat)}


@router.get("/idle-status/{aid}")
def idle_status(aid: str, db: DbSession = Depends(get_db)):
    """report whether the server supports IDLE push (best-effort, network)."""
    from services import mail_idle

    a = _get(db, aid)
    try:
        return {"idle": mail_idle.idle_available(_acct_dict(a))}
    except Exception:
        return {"idle": False}


@router.get("/message/{aid}")
def message(aid: str, uid: str, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.fetch_message(_acct_dict(a), uid, folder)
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/search/{aid}")
def search_mail(
    aid: str, q: str, folder: str = "INBOX", limit: int = 40, db: DbSession = Depends(get_db)
):
    a = _get(db, aid)
    try:
        return {"messages": mailsvc.search(_acct_dict(a), q, folder, limit)}
    except Exception as e:
        return {"error": str(e)[:200], "messages": []}


@router.get("/threads/{aid}")
def threads(aid: str, folder: str = "INBOX", limit: int = 60, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        msgs = mailsvc.fetch_inbox(_acct_dict(a), folder, limit)
        return {"threads": mailsvc.group_threads(msgs)}
    except Exception as e:
        return {"error": str(e)[:200], "threads": []}


@router.get("/attachments/{aid}")
def attachments(aid: str, uid: str, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return {"attachments": mailsvc.list_attachments(_acct_dict(a), uid, folder)}
    except Exception as e:
        return {"error": str(e)[:200], "attachments": []}


@router.get("/attachment/{aid}")
def attachment(
    aid: str, uid: str, index: int, folder: str = "INBOX", db: DbSession = Depends(get_db)
):
    from urllib.parse import quote

    from fastapi.responses import Response

    a = _get(db, aid)
    try:
        res = mailsvc.fetch_attachment(_acct_dict(a), uid, index, folder)
    except Exception as e:
        raise HTTPException(502, str(e)[:200])
    if not res:
        raise HTTPException(404, "attachment not found")
    filename, ctype, data = res
    return Response(
        content=data,
        media_type=ctype or "application/octet-stream",
        headers={"content-disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/folders/{aid}")
def folders(aid: str, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return {"folders": mailsvc.list_folders(_acct_dict(a))}
    except Exception as e:
        return {"folders": [], "error": str(e)[:200]}


@router.post("/seen/{aid}")
def seen(aid: str, uid: str, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.mark_seen(_acct_dict(a), uid, folder)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


class SendBody(BaseModel):
    to: str
    subject: str = ""
    body: str = ""
    cc: str = ""
    bcc: str = ""
    in_reply_to: str = ""
    references: str = ""


@router.post("/send/{aid}")
def send(aid: str, body: SendBody, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.send_mail(
            _acct_dict(a),
            body.to,
            body.subject,
            body.body,
            body.cc,
            body.bcc,
            body.in_reply_to,
            body.references,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


class SummarizeBody(BaseModel):
    subject: str = ""
    body: str = ""


@router.post("/summarize")
async def summarize_mail(body: SummarizeBody, db: DbSession = Depends(get_db)):
    """AI summary of a mail — bullets + any action items."""
    from core.database import ModelEndpoint
    from services.llm import simple_complete

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep:
        raise HTTPException(400, "no model endpoint configured")
    model = ep.models_list()[0] if ep.models_list() else ""
    if not model:
        raise HTTPException(400, "no model available")
    prompt = [
        {
            "role": "system",
            "content": (
                "Summarize the email in 2-4 short bullet points, then if there are any "
                "action items add a final line starting with 'todo:'. Be terse, plain text only."
            ),
        },
        {"role": "user", "content": f"Subject: {body.subject}\n\n{body.body[:8000]}"},
    ]
    text = await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=400)
    if not text:
        raise HTTPException(502, "model returned nothing — try again")
    return {"summary": text}


class MakeTaskBody(BaseModel):
    title: str


@router.post("/make-task")
def make_task(body: MakeTaskBody, db: DbSession = Depends(get_db)):
    from core.database import Task

    title = body.title.strip()[:300]
    if not title:
        raise HTTPException(400, "empty title")
    t = Task(title=title)
    db.add(t)
    db.commit()
    return {"ok": True, "id": t.id}


class ExtractEventBody(BaseModel):
    subject: str = ""
    body: str = ""
    date: str = ""  # the mail's own date header, helps resolve "next tuesday"


@router.post("/extract-event")
async def extract_event(body: ExtractEventBody, db: DbSession = Depends(get_db)):
    """AI-extract an event from a mail and drop it straight into the calendar."""
    import json as _json
    from datetime import datetime

    from core.database import CalendarEvent, ModelEndpoint
    from services.llm import simple_complete

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep:
        raise HTTPException(400, "no model endpoint configured")
    model = ep.models_list()[0] if ep.models_list() else ""
    if not model:
        raise HTTPException(400, "no model available")

    today = datetime.now().strftime("%A, %Y-%m-%d")
    prompt = [
        {
            "role": "system",
            "content": (
                "You extract calendar events from emails. Reply with ONLY a JSON object, no prose, "
                'no code fences. Schema: {"found": bool, "title": str, "start": "YYYY-MM-DDTHH:MM", '
                '"end": "YYYY-MM-DDTHH:MM" or null, "location": str, "all_day": bool}. '
                f"Today is {today}. Resolve relative dates against the email's date when given. "
                'If the email contains no concrete event (date or time), return {"found": false}.'
            ),
        },
        {
            "role": "user",
            "content": (
                (f"Email date: {body.date}\n" if body.date else "")
                + f"Subject: {body.subject}\n\n{body.body[:6000]}"
            ),
        },
    ]
    raw = await simple_complete(prompt, ep.base_url, ep.api_key, model, max_tokens=300)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = _json.loads(raw)
    except Exception:
        raise HTTPException(502, "model returned unparseable output — try again")
    if not data.get("found") or not data.get("start"):
        return {"found": False}

    desc = "from mail"
    if data.get("location"):
        desc += f" — {data['location']}"
    ev = CalendarEvent(
        title=(data.get("title") or body.subject or "event")[:200],
        description=desc,
        start_dt=str(data["start"]),
        end_dt=str(data["end"]) if data.get("end") else None,
        all_day=bool(data.get("all_day")),
        color="accent",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return {
        "found": True,
        "id": ev.id,
        "title": ev.title,
        "start": ev.start_dt,
        "end": ev.end_dt,
        "all_day": ev.all_day,
    }
