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
        from routes.uploads import upload_dir

        db = SessionLocal()
        try:
            up = db.get(Upload, uid)
            if not up:
                return (None, None)
            p = upload_dir() / up.filename
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

    # carry the full account incl. auth_type + oauth tokens, or an oauth (sign-in-with-google)
    # account falls through to a password login with an empty password and never delivers
    acct_dict = {
        "id": acct.id,
        "imap_host": acct.imap_host,
        "imap_port": acct.imap_port,
        "smtp_host": acct.smtp_host,
        "smtp_port": acct.smtp_port,
        "username": acct.username,
        "password": acct.password,
        "email": acct.email,
        "use_ssl": acct.use_ssl,
        "auth_type": acct.auth_type,
        "oauth_access_token": acct.oauth_access_token,
        "oauth_refresh_token": acct.oauth_refresh_token,
        "oauth_expires_at": acct.oauth_expires_at,
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


def _mark_interrupted_uncertain(db):
    """Quarantine sends interrupted after their durable claim.

    A ``sending`` row may already have reached SMTP, so it is unsafe to put it
    back in the automatic queue after a process restart.
    """
    count = (
        db.query(ScheduledMail)
        .filter(ScheduledMail.status == "sending")
        .update({ScheduledMail.status: "uncertain"}, synchronize_session=False)
    )
    if count:
        db.commit()
    return count


def process_due(db, now_iso=None, send_fn=None):
    """Send due mail with a durable claim before the external side effect."""
    now_iso = now_iso or datetime.utcnow().isoformat()
    send_fn = send_fn or _default_send
    _mark_interrupted_uncertain(db)
    n = 0
    for m in db.query(ScheduledMail).filter(ScheduledMail.status == "scheduled").all():
        if (m.send_at or "") and m.send_at <= now_iso:
            acct = db.get(MailAccount, m.account_id)
            if not acct:
                continue  # account gone — leave it queued so it can send once restored
            claimed = (
                db.query(ScheduledMail)
                .filter(
                    ScheduledMail.id == m.id,
                    ScheduledMail.status == "scheduled",
                )
                .update({ScheduledMail.status: "sending"}, synchronize_session=False)
            )
            db.commit()  # claim first: a crash after SMTP must not leave it queued
            if not claimed:
                continue
            try:
                send_fn(acct, m)
            except Exception:
                # The exception may happen after SMTP accepted the message. Re-sending
                # automatically would risk a duplicate, so leave it for user review.
                m.status = "uncertain"
                db.commit()
                continue
            m.status = "sent"
            db.commit()
            n += 1
    return n


async def _job():
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        process_due(db)
    finally:
        db.close()
