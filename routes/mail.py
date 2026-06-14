from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, MailAccount
from services import mail as mailsvc

router = APIRouter(prefix="/api/mail")


def _acct_dict(a: MailAccount) -> dict:
    return {
        "imap_host": a.imap_host, "imap_port": a.imap_port,
        "smtp_host": a.smtp_host, "smtp_port": a.smtp_port,
        "username": a.username, "password": a.password,
        "email": a.email, "use_ssl": a.use_ssl,
    }


def _fmt(a: MailAccount) -> dict:   # never leaks the password
    return {
        "id": a.id, "name": a.name, "email": a.email,
        "imap_host": a.imap_host, "imap_port": a.imap_port,
        "smtp_host": a.smtp_host, "smtp_port": a.smtp_port,
        "username": a.username, "use_ssl": a.use_ssl,
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
    db.add(a); db.commit(); db.refresh(a)
    mailsvc.clear_cache()
    return _fmt(a)


@router.patch("/accounts/{aid}")
def patch_account(aid: str, body: AcctBody, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    data = body.model_dump()
    if not data.get("password"):
        data.pop("password")   # keep the existing password if the form left it blank
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    mailsvc.clear_cache()
    return _fmt(a)


@router.delete("/accounts/{aid}")
def del_account(aid: str, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    db.delete(a); db.commit()
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


@router.get("/inbox/{aid}")
def inbox(aid: str, folder: str = "INBOX", limit: int = 30, quick: bool = False, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return {"messages": mailsvc.fetch_inbox(_acct_dict(a), folder, limit, quick=quick)}
    except Exception as e:
        return {"error": str(e)[:200], "messages": []}


@router.get("/message/{aid}")
def message(aid: str, uid: str, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.fetch_message(_acct_dict(a), uid, folder)
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/search/{aid}")
def search_mail(aid: str, q: str, folder: str = "INBOX", limit: int = 40, db: DbSession = Depends(get_db)):
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
def attachment(aid: str, uid: str, index: int, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    from fastapi.responses import Response
    from urllib.parse import quote
    a = _get(db, aid)
    try:
        res = mailsvc.fetch_attachment(_acct_dict(a), uid, index, folder)
    except Exception as e:
        raise HTTPException(502, str(e)[:200])
    if not res:
        raise HTTPException(404, "attachment not found")
    filename, ctype, data = res
    return Response(content=data, media_type=ctype or "application/octet-stream",
                    headers={"content-disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


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


@router.post("/send/{aid}")
def send(aid: str, body: SendBody, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.send_mail(_acct_dict(a), body.to, body.subject, body.body, body.cc)
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
        {"role": "system", "content": (
            "Summarize the email in 2-4 short bullet points, then if there are any "
            "action items add a final line starting with 'todo:'. Be terse, plain text only."
        )},
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
    db.add(t); db.commit()
    return {"ok": True, "id": t.id}


class ExtractEventBody(BaseModel):
    subject: str = ""
    body: str = ""
    date: str = ""    # the mail's own date header, helps resolve "next tuesday"


@router.post("/extract-event")
async def extract_event(body: ExtractEventBody, db: DbSession = Depends(get_db)):
    """AI-extract an event from a mail and drop it straight into the calendar."""
    import json as _json
    from datetime import datetime
    from core.database import ModelEndpoint, CalendarEvent
    from services.llm import simple_complete

    ep = db.query(ModelEndpoint).filter(ModelEndpoint.enabled == True).first()
    if not ep:
        raise HTTPException(400, "no model endpoint configured")
    model = ep.models_list()[0] if ep.models_list() else ""
    if not model:
        raise HTTPException(400, "no model available")

    today = datetime.now().strftime("%A, %Y-%m-%d")
    prompt = [
        {"role": "system", "content": (
            "You extract calendar events from emails. Reply with ONLY a JSON object, no prose, "
            "no code fences. Schema: {\"found\": bool, \"title\": str, \"start\": \"YYYY-MM-DDTHH:MM\", "
            "\"end\": \"YYYY-MM-DDTHH:MM\" or null, \"location\": str, \"all_day\": bool}. "
            f"Today is {today}. Resolve relative dates against the email's date when given. "
            "If the email contains no concrete event (date or time), return {\"found\": false}."
        )},
        {"role": "user", "content": (
            (f"Email date: {body.date}\n" if body.date else "")
            + f"Subject: {body.subject}\n\n{body.body[:6000]}"
        )},
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
    db.add(ev); db.commit(); db.refresh(ev)
    return {"found": True, "id": ev.id, "title": ev.title,
            "start": ev.start_dt, "end": ev.end_dt, "all_day": ev.all_day}
