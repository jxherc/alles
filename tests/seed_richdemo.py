"""richer demo data for README screenshots — populated tasks/money/subs/calendar/
days/journal/contacts + a handful of vault docs. additive + idempotent-ish (guards on
count so a re-run doesn't pile up). NOT used by the product; screenshots only.

  ALLES_DATA=…/some_data python tests/seed_richdemo.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import settings as _settings  # noqa: E402
from core.database import (  # noqa: E402
    Account,
    Budget,
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

NOW = datetime.now()
TODAY = NOW.date()


def iso(d):
    return d.isoformat()


def main():
    d = SessionLocal()
    cnt = lambda m: d.query(m).count()  # noqa: E731

    # ── tasks ────────────────────────────────────────────────────────────────
    if cnt(Task) < 6:
        tasks = [
            ("Finish Q3 planning doc", 2, 1, "work,writing", "Outline + budget table"),
            ("Email landlord about lease", 2, 0, "home", ""),
            ("Book dentist appointment", 1, 2, "health", ""),
            ("Renew passport", 2, 14, "travel,admin", "Photos done, form half-filled"),
            ("Groceries — milk, eggs, coffee", 0, 0, "home", ""),
            ("Review pull request #482", 1, 1, "work", ""),
            ("Call mom", 1, 0, "family", ""),
            ("Plan weekend hike", 0, 3, "outdoors", "Check the weather first"),
            ("Pay credit card", 2, 4, "finance", ""),
            ("Read 'The Pragmatic Programmer'", 0, 30, "reading", ""),
        ]
        for i, (title, pri, due_off, tags, notes) in enumerate(tasks):
            d.add(Task(title=title, priority=pri, due_date=iso(TODAY + timedelta(days=due_off)),
                       tags=tags, notes=notes, sort_order=i))
        # a couple already done
        for title in ("Submit expense report", "Water the plants"):
            t = Task(title=title, done=True, completed_at=NOW - timedelta(days=1))
            d.add(t)

    # ── money: accounts + budgets + a month of transactions ──────────────────
    if cnt(Account) < 3:
        checking = Account(name="Checking", kind="checking", opening=3200.0, currency="USD", color="#818cf8")
        savings = Account(name="Savings", kind="savings", opening=12500.0, currency="USD", color="#4ade80")
        card = Account(name="Visa", kind="credit", opening=-640.0, currency="USD", color="#f87171")
        d.add_all([checking, savings, card])
        d.flush()
        cat_payees = [
            ("food", ["Whole Foods", "Blue Bottle", "Chipotle", "Trader Joe's"], (-9, -85)),
            ("transport", ["Uber", "Shell", "Transit Pass"], (-3, -60)),
            ("shopping", ["Amazon", "Uniqlo", "IKEA"], (-15, -180)),
            ("bills", ["PG&E", "Comcast", "Water Dept"], (-40, -160)),
            ("entertainment", ["Steam", "AMC", "Spotify"], (-10, -55)),
            ("health", ["CVS", "Gym"], (-12, -75)),
        ]
        # deterministic spread (no RNG — keeps runs reproducible)
        import itertools
        seq = itertools.count(7)
        for wk in range(4):
            for cat, payees, (lo, hi) in cat_payees:
                n = next(seq)
                amt = lo + ((n * 37) % (hi - lo if hi != lo else 1))
                payee = payees[n % len(payees)]
                d.add(Transaction(account_id=checking.id, amount=float(round(amt, 2)),
                                  category=cat, payee=payee, tags=cat,
                                  date=iso(TODAY - timedelta(days=wk * 7 + (n % 6)))))
        # income + a transfer-ish deposit
        d.add(Transaction(account_id=checking.id, amount=4200.0, category="income",
                          payee="Acme Corp — payroll", date=iso(TODAY - timedelta(days=2))))
        d.add(Transaction(account_id=savings.id, amount=500.0, category="savings",
                          payee="Monthly transfer", date=iso(TODAY - timedelta(days=2))))
    if cnt(Budget) < 3:
        for cat, lim in [("food", 600), ("shopping", 300), ("entertainment", 120), ("transport", 200)]:
            d.add(Budget(category=cat, limit_amt=float(lim)))

    # ── subscriptions ────────────────────────────────────────────────────────
    if cnt(Subscription) < 4:
        subs = [
            ("Netflix", 15.99, "entertainment", 5),
            ("Spotify", 11.99, "entertainment", 12),
            ("iCloud+", 2.99, "software", 1),
            ("GitHub Pro", 4.0, "software", 20),
            ("ChatGPT Plus", 20.0, "software", 8),
            ("Notion", 8.0, "software", 24),
            ("NYTimes", 17.0, "news", 16),
            ("Adobe CC", 54.99, "software", 27),
        ]
        for name, price, cat, due_off in subs:
            d.add(Subscription(name=name, price=price, cycle="monthly", category=cat,
                               next_due=iso(TODAY + timedelta(days=due_off))))

    # ── calendar: a month of events ──────────────────────────────────────────
    if not d.query(Calendar).count():
        d.add(Calendar(name="Personal", color="#818cf8"))
        d.flush()
    if not d.query(Calendar).filter(Calendar.name == "Work").count():
        d.add(Calendar(name="Work", color="#4d9ef5"))
        d.flush()
    if cnt(CalendarEvent) < 4:
        personal = d.query(Calendar).filter(Calendar.name == "Personal").first()
        work = d.query(Calendar).filter(Calendar.name == "Work").first()
        evs = [
            (work, "Team standup", -2, 9, 1, False),
            (work, "1:1 with Sam", 0, 14, 1, False),
            (work, "Design review", 1, 11, 2, False),
            (work, "Sprint demo", 3, 15, 1, False),
            (personal, "Dentist", 1, 8, 1, False),
            (personal, "Gym — leg day", 0, 18, 1, False),
            (personal, "Dinner w/ Alex", 2, 19, 2, False),
            (personal, "Farmers market", 4, 9, 2, False),
            (personal, "Mom's birthday", 6, 0, 0, True),
            (work, "Quarterly offsite", 8, 0, 0, True),
        ]
        for cal, title, day_off, hr, dur, allday in evs:
            start = (NOW + timedelta(days=day_off)).replace(hour=hr, minute=0, second=0, microsecond=0)
            d.add(CalendarEvent(calendar_id=cal.id, title=title,
                               start_dt=start.isoformat(),
                               end_dt=(start + timedelta(hours=dur or 1)).isoformat(),
                               all_day=allday))

    # ── days: countdowns + anniversaries ─────────────────────────────────────
    if cnt(DayEvent) < 4:
        days = [
            ("New Year", "2027-01-01", "holiday", True),
            ("Trip to Japan", iso(TODAY + timedelta(days=43)), "travel", True),
            ("Project launch", iso(TODAY + timedelta(days=12)), "work", False),
            ("Started this job", "2023-04-17", "milestone", False),
            ("Anniversary", "2019-09-21", "personal", True),
            ("Lease renewal", iso(TODAY + timedelta(days=78)), "home", False),
        ]
        for name, date_, cat, pin in days:
            d.add(DayEvent(name=name, date=date_, category=cat, pinned=pin))

    # ── journal: spread across ~16 weeks so the heatmap looks alive ───────────
    if cnt(JournalEntry) < 10:
        moods = ["🙂", "😀", "😐", "😴", "🤔", "😌", "🔥"]
        notes = [
            "Shipped the new model picker. Brand colours finally line up.",
            "Long walk, clear head. Sketched the release plan.",
            "Debugged a gnarly streaming bug for hours. Got it.",
            "Quiet day. Read and recharged.",
            "Pairing session went great — learned a new git trick.",
            "Cooked a proper dinner for once. Worth it.",
            "Tired but productive. Closed six tickets.",
        ]
        for i in range(46):
            day = TODAY - timedelta(days=i * 3)   # every 3 days → unique, ~4 months of heatmap
            if d.query(JournalEntry).filter(JournalEntry.date == iso(day)).count():
                continue
            d.add(JournalEntry(date=iso(day), content=notes[i % len(notes)],
                              mood=moods[i % len(moods)], tags="daily"))

    # ── contacts ─────────────────────────────────────────────────────────────
    if cnt(Contact) < 4:
        people = [
            ("Ada Lovelace", "ada@analytical.io", "Analytical Engines", "Mathematician", True),
            ("Alan Turing", "alan@bletchley.uk", "Bletchley", "Cryptographer", False),
            ("Grace Hopper", "grace@navy.mil", "US Navy", "Rear Admiral", True),
            ("Katherine Johnson", "kj@nasa.gov", "NASA", "Mathematician", False),
            ("Sam Rivera", "sam@acme.co", "Acme Corp", "Manager", False),
            ("Alex Chen", "alex@example.com", "Freelance", "Designer", False),
        ]
        for name, email, company, title, fav in people:
            d.add(Contact(name=name, email=email, company=company, title=title, favorite=fav))

    d.commit()
    out = {m.__name__: cnt(m) for m in [Task, Transaction, Subscription, CalendarEvent,
                                        DayEvent, JournalEntry, Contact, Budget]}
    print("rich-seeded:", out)

    # ── demo docs (.md files in the vault) ───────────────────────────────────
    vault = os.path.join(_settings.data_dir(), "vault")
    os.makedirs(vault, exist_ok=True)
    docs = {
        "Welcome.md": (
            "---\ntags: [start-here]\n---\n\n"
            "# Welcome to your vault\n\n"
            "These are plain `.md` files you own. Try [[Project Atlas]] or the "
            "[[Reading list]]. Tag things with #ideas and link freely.\n\n"
            "- [ ] explore the graph view\n- [x] write your first note\n"
        ),
        "Project Atlas.md": (
            "---\ntags: [work, project]\n---\n\n"
            "# Project Atlas\n\n"
            "The big one. See [[Welcome]] for context and [[Meeting notes]].\n\n"
            "## Milestones\n- [x] kickoff\n- [ ] beta\n- [ ] launch\n\n"
            "> The map is not the territory. #ideas\n"
        ),
        "Meeting notes.md": (
            "---\ntags: [work]\n---\n\n"
            "# Meeting notes\n\nStandup w/ [[Project Atlas]] team.\n\n"
            "- shipped the model picker\n- next: docs polish\n"
        ),
        "Reading list.md": (
            "---\ntags: [reading]\n---\n\n"
            "# Reading list\n\n- The Pragmatic Programmer\n- Thinking in Systems\n"
            "- Designing Data-Intensive Applications #ideas\n"
        ),
    }
    for name, body in docs.items():
        p = os.path.join(vault, name)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
    print("docs written to", vault)


if __name__ == "__main__":
    main()
