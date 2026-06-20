"""seed varied, realistic demo data across apps into the ALLES_DATA db (idempotent).
used to give the per-microversion regression sweep populated views.

  ALLES_DATA=…/some_data python tests/seed_demo.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import (  # noqa: E402
    Account,
    Calendar,
    CalendarEvent,
    Contact,
    DayEvent,
    JournalEntry,
    SessionLocal,
    Subscription,
    Task,
    Transaction,
)


def main():
    d = SessionLocal()
    H = lambda m: d.query(m).count()  # noqa: E731
    today = datetime.now().date().isoformat()
    if not H(Task):
        d.add_all(
            [Task(title="Buy groceries", priority=1), Task(title="Email landlord", due_date=today)]
        )
    if not H(JournalEntry):
        d.add(JournalEntry(date=today, content="A good day. Shipped a microversion.", mood="🙂"))
    if not H(Account):
        a = Account(name="Checking", kind="checking", opening=1000.0, currency="USD")
        d.add(a)
        d.flush()
        d.add_all(
            [
                Transaction(
                    account_id=a.id, amount=-42.5, category="food", payee="Cafe", date=today
                ),
                Transaction(
                    account_id=a.id, amount=2000.0, category="income", payee="Work", date=today
                ),
            ]
        )
    if not H(Contact):
        d.add(
            Contact(
                name="Ada Lovelace", email="ada@example.com", company="Analytical", favorite=True
            )
        )
    if not H(Calendar):
        d.add(Calendar(name="Personal", color="#818cf8"))
        d.flush()
    if not H(CalendarEvent):
        cid = d.query(Calendar).first().id
        d.add(
            CalendarEvent(
                calendar_id=cid,
                title="Dentist",
                start_dt=(datetime.now() + timedelta(days=1)).isoformat(),
                end_dt=(datetime.now() + timedelta(days=1, hours=1)).isoformat(),
            )
        )
    if not H(Subscription):
        d.add(
            Subscription(
                name="Netflix",
                price=15.99,
                cycle="monthly",
                next_due=(datetime.now() + timedelta(days=5)).date().isoformat(),
            )
        )
    if not H(DayEvent):
        d.add(DayEvent(name="New Year", date="2027-01-01"))
    d.commit()
    print(
        "seeded:",
        {
            m.__name__: d.query(m).count()
            for m in [
                Task,
                JournalEntry,
                Account,
                Transaction,
                Contact,
                CalendarEvent,
                Subscription,
                DayEvent,
            ]
        },
    )


if __name__ == "__main__":
    main()
