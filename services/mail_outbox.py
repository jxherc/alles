"""scheduled-send outbox (5b). a 30s job calls process_due to flush mails whose send_at
has passed; SMTP is best-effort. undo-send is just a near-future schedule you can cancel."""

from datetime import datetime

from core.database import MailAccount, ScheduledMail


def _inline_from_html(html):
    """best-effort: turn /api/uploads refs in the html into cid inline parts (5c)."""
    from services import mail_compose

    if not html or "/api/uploads/" not in html:
        return html or "", []

    def get_bytes(uid):
        from core.database import SessionLocal, Upload
        from routes.uploads import UPLOAD_DIR

        db = SessionLocal()
        try:
            up = db.get(Upload, uid)
            if not up:
                return (None, None)
            p = UPLOAD_DIR / up.filename
            return (
                (p.read_bytes(), (up.mime_type or "image/png").split("/")[-1])
                if p.exists()
                else (None, None)
            )
        finally:
            db.close()

    return mail_compose.embed_inline(html, get_bytes)


def _default_send(acct, m):
    from services import mail as mailsvc

    acct_dict = {
        "imap_host": acct.imap_host,
        "imap_port": acct.imap_port,
        "smtp_host": acct.smtp_host,
        "smtp_port": acct.smtp_port,
        "username": acct.username,
        "password": acct.password,
        "email": acct.email,
        "use_ssl": acct.use_ssl,
    }
    html, inline = _inline_from_html(getattr(m, "html", "") or "")
    mailsvc.send_mail(
        acct_dict,
        m.to,
        m.subject,
        m.body,
        m.cc,
        m.bcc,
        m.in_reply_to,
        m.references,
        html=html,
        inline=inline,
    )


def process_due(db, now_iso=None, send_fn=None):
    """send every scheduled mail whose send_at has passed (best-effort), mark sent."""
    now_iso = now_iso or datetime.utcnow().isoformat()
    send_fn = send_fn or _default_send
    n = 0
    for m in db.query(ScheduledMail).filter(ScheduledMail.status == "scheduled").all():
        if (m.send_at or "") and m.send_at <= now_iso:
            acct = db.get(MailAccount, m.account_id)
            if not acct:
                continue  # account gone — leave it queued so it can send once restored
            try:
                send_fn(acct, m)
            except Exception:
                continue  # transient failure — stays scheduled, retried next tick (never marked sent)
            m.status = "sent"  # only on a real successful send
            n += 1
    db.commit()
    return n


async def _job():
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        process_due(db)
    finally:
        db.close()
