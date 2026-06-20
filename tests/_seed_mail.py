"""seed a fake mail account + cached messages into ALLES_DATA so the cache-backed mail
UI renders with no live IMAP server. the account points at a closed local port so the
inbox fetch fails fast and the UI falls back to the cache. prints the account id."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import CachedMessage, MailAccount, SessionLocal, init_db  # noqa: E402


def _ts(d):
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()


def main():
    init_db()
    db = SessionLocal()
    db.query(CachedMessage).delete()
    db.query(MailAccount).delete()
    db.commit()
    a = MailAccount(
        name="Test",
        email="me@test.com",
        imap_host="127.0.0.1",
        imap_port=9,  # closed port → fetch fails fast → UI uses the cache
        smtp_host="127.0.0.1",
        smtp_port=9,
        username="me",
        password="x",
        use_ssl=False,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    rows = [
        (
            "1",
            "Alice <alice@news.com>",
            "Weekly Newsletter",
            "2026-06-18",
            "<https://news.com/unsub?id=1>",
        ),
        ("2", "Bob <bob@work.com>", "Project plan", "2026-06-17", ""),
        ("3", "Bob <bob@work.com>", "Re: Project plan", "2026-06-16", ""),
        ("4", "Carol <carol@shop.com>", "Your receipt", "2026-06-15", ""),
    ]
    for uid, sender, subject, date, unsub in rows:
        db.add(
            CachedMessage(
                account_id=a.id,
                folder="INBOX",
                uid=uid,
                sender=sender,
                subject=subject,
                date=date,
                date_ts=_ts(date),
                seen=True,
                list_unsubscribe=unsub,
            )
        )
    db.commit()
    print(a.id)
    db.close()


if __name__ == "__main__":
    main()
