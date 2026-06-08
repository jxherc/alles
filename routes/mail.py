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
    return _fmt(a)


@router.delete("/accounts/{aid}")
def del_account(aid: str, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    db.delete(a); db.commit()
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
def inbox(aid: str, folder: str = "INBOX", limit: int = 30, db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return {"messages": mailsvc.fetch_inbox(_acct_dict(a), folder, limit)}
    except Exception as e:
        return {"error": str(e)[:200], "messages": []}


@router.get("/message/{aid}")
def message(aid: str, uid: str, folder: str = "INBOX", db: DbSession = Depends(get_db)):
    a = _get(db, aid)
    try:
        return mailsvc.fetch_message(_acct_dict(a), uid, folder)
    except Exception as e:
        return {"error": str(e)[:200]}


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
