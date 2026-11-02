"""Delete is one tap away, never on show (u.10): no delete control is visible at rest.

opens every app on seeded data (home, plan's views, health, habits, finance and money, docs,
files, inbox, library, vault, aide) at ipad landscape and phone, with the pointer parked, and
fails when a delete control (a trash icon, an aria-label, title, action or text that says
delete, remove or trash, `.task-del` and the like) is visible outside an open menu, a dialog or
an edit panel. money's shut sections are opened and its plan tasks walked first. every find
prints its app, view, size and selector. ALLOWED names each real exception with its reason.

run through the gate runner, which owns the server and its throwaway data. DELETE_SHOTS=<dir>
also saves a screenshot of every find there (before and after evidence).
"""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright
from pw_finance_helpers import pick_money_task

SIZES = {"ipad-landscape": (1180, 820), "phone": (390, 844)}

# (app, view, selector) -> why it may stay visible at rest. only real exceptions belong here: a
# control that deletes nothing. a delete control that deletes goes behind its row's more menu.
ALLOWED = {
    ("docs", "notes", "button#wiki-trash-btn"): "opens the recently deleted list, deletes nothing",
    (
        "files",
        "gallery",
        "nav#photos-sidebar > button.photos-nav-item",
    ): "the trash album in the sidebar, deletes nothing",
}


# the apps, by subdomain, and the views each one opens on (the group tabs found on the page)
APPS = ["", "plan", "health", "finance", "docs", "files", "inbox", "library", "passwords", "aide"]
# aide has no group tabs: its own pages are opened through the app switcher or its sidebar
AIDE_VIEWS = ["memory", "scheduled", "skills", "projects", "gallery", "cookbook", "usage"]

FIND = """
() => {
  const WORD = /\\b(delete|remove|trash|discard|erase|forget|del|rm)\\b/i;
  const ATTR = /(^|-)(del|delete|remove|trash)(-|$)/i;
  const CLASS = /(^|[-_ ])(del|delete|remove|trash|rm)([-_ ]|$)/i;
  const POPUP = '[role="menu"], [role="dialog"], [role="alertdialog"], [role="listbox"], dialog, [aria-modal="true"], '
    + '.ctx-menu, [class*="-menu"], [class*="menu-"], .modal, [class*="overlay"], [class*="-ov"], [class*="edit-panel"], '
    + '[class*="editor"], [class*="-edit"], [data-editing], .dialog-card, [popover]';
  const isInPopup = el => !!el.closest(POPUP);
  const clip = el => {
    // overflow:hidden ancestors cut the control off
    const r = el.getBoundingClientRect();
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (/(hidden|clip)/.test(s.overflowX + s.overflowY)) {
        const q = p.getBoundingClientRect();
        if (q.width === 0 || q.height === 0) return true;
        if (r.right <= q.left || r.left >= q.right || r.bottom <= q.top || r.top >= q.bottom) return true;
      }
    }
    return false;
  };
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    if (!el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    for (let p = el; p && p !== document.documentElement; p = p.parentElement) {
      if (parseFloat(getComputedStyle(p).opacity) < 0.15) return false;
      if (p.hidden || p.getAttribute('aria-hidden') === 'true' && !p.matches('svg, svg *, i, span')) {
        if (p.hidden) return false;
      }
    }
    return !clip(el);
  };
  const label = el => [el.getAttribute('aria-label'), el.getAttribute('title'), el.dataset.act, el.dataset.action,
    el.dataset.tip, el.getAttribute('data-i18n-title')].filter(Boolean).join(' | ');
  const pathOf = el => {
    const parts = [];
    for (let p = el; p && p.nodeType === 1 && parts.length < 4; p = p.parentElement) {
      let s = p.tagName.toLowerCase();
      if (p.id) s += '#' + p.id;
      else if (p.classList.length) s += '.' + [...p.classList].slice(0, 2).join('.');
      parts.unshift(s);
      if (p.id) break;
    }
    return parts.join(' > ');
  };
  const out = [];
  const seen = new Set();
  const pool = document.querySelectorAll(
    'button, [role="button"], [role="menuitem"], a, summary, input[type="button"], [data-act], [class*="del"], [class*="trash"], [class*="remove"]');
  for (const el of pool) {
    if (seen.has(el)) continue;
    const text = (el.children.length === 0 || el.matches('button, a')) ? (el.textContent || '').trim().slice(0, 40) : '';
    const named = WORD.test(label(el)) || (text && /^(delete|remove|trash|discard)\\b/i.test(text))
      || [...el.classList].some(c => CLASS.test(c)) || CLASS.test(el.id || '')
      || el.getAttributeNames().some(n => ATTR.test(n.replace(/^data-/, '')))
      || !!el.querySelector(':scope > svg[class*="trash"], :scope > [data-icon="trash"], :scope > .icon-trash');
    if (!named) continue;
    if (!visible(el) || isInPopup(el)) continue;
    // a control that only has a name in a data attribute but isn't drawn as a button is no control
    seen.add(el);
    const r = el.getBoundingClientRect();
    out.push({
      selector: pathOf(el),
      label: label(el) || text,
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      icon: el.querySelector('svg') ? (el.querySelector('svg').getAttribute('class') || 'svg') : '',
    });
  }
  return out;
}
"""


INNER_TABS = (
    '[role="tab"]:not([data-group-section]), '
    'button[aria-controls][aria-pressed="false"]:not([data-group-section])'
)


def seed(api, base):
    today = date.today()
    day = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    failed = []

    def call(method, path, body=None):
        reply = api.fetch(
            base + path,
            method=method,
            data=json.dumps(body) if body is not None else None,
            headers={"content-type": "application/json"},
        )
        if not reply.ok:
            failed.append(f"{method} {path} {reply.status}")
            return {}
        try:
            return reply.json() or {}
        except Exception:  # noqa: BLE001
            return {}

    assert api.post(base + "/api/setup/dismiss").ok
    for n, (title, due, prio) in enumerate(
        [
            ("finish the chemistry lab report on reaction rates", -3, 2),
            ("email ms. patel about the boh4m presentation slot", -2, 1),
            ("ics4u: finish the javascript array practice set", 0, 2),
            ("pick up gym shoes", 0, 0),
            ("study for the chem unit test", 1, 3),
            ("learning log for this week", 2, 0),
            ("ethics assignment draft", 5, 1),
            ("renew the library books", 12, 0),
        ]
    ):
        call("POST", "/api/tasks", {"title": title, "priority": prio, "due_date": day(due)})
    call("POST", "/api/tasks", {"title": "clean out the downloads folder"})
    for title, n, start, end in [
        ("ics4u class", 0, "10:30", "11:45"),
        ("gym: pull day", 0, "17:30", "18:45"),
        ("chem unit test", 1, "09:00", "10:15"),
        ("dentist", 3, "16:00", "16:45"),
    ]:
        call(
            "POST",
            "/api/calendar",
            {"title": title, "start_dt": f"{day(n)}T{start}:00", "end_dt": f"{day(n)}T{end}:00"},
        )
    for text, n, at in [
        ("take vitamins", 0, "20:30"),
        ("call grandma", 1, "18:00"),
        ("return the library books", 3, "12:00"),
    ]:
        call("POST", "/api/reminders", {"text": text, "trigger_at": f"{day(n)}T{at}:00"})
    for name, n in [("chem unit test", 9), ("summer break", 60), ("mom's birthday", 24)]:
        call("POST", "/api/days", {"name": name, "date": day(n), "repeat": "none"})
    for name in ["gym", "read 20 minutes", "stretch"]:
        made = call("POST", "/api/habits", {"name": name})
        if made.get("id"):
            for n in (1, 2, 4):
                call("POST", f"/api/habits/{made['id']}/toggle", {"date": day(-n), "done": True})
    for n, w in [(-13, 153.0), (-7, 152.4), (-2, 151.6), (0, 151.2)]:
        call("POST", "/api/health", {"kind": "weight", "value": w, "unit": "lb", "date": day(n)})
    for n, v in [(-8, 7.2), (-1, 6.5), (0, 7.8)]:
        call("POST", "/api/health", {"kind": "sleep", "value": v, "unit": "h", "date": day(n)})
    acct = call(
        "POST", "/api/money/accounts", {"name": "td chequing", "currency": "CAD", "opening": 900}
    )
    aid = acct.get("id") or acct.get("account", {}).get("id")
    for n, amount, cat, payee in [
        (-40, -64.20, "groceries", "no frills"),
        (-28, 120.00, "income", "tutoring"),
        (-12, -9.99, "subscriptions", "spotify"),
        (-6, -38.75, "groceries", "no frills"),
        (-2, -25.00, "transport", "presto"),
        (0, -5.50, "eating out", "tim hortons"),
    ]:
        call(
            "POST",
            "/api/money/transactions",
            {"account_id": aid, "date": day(n), "amount": amount, "category": cat, "payee": payee},
        )
    call("POST", "/api/money/budgets", {"category": "groceries", "limit_amt": 300})
    call("POST", "/api/money/holdings", {"symbol": "VFV", "qty": 12, "price": 118.4})
    call("POST", "/api/money/rules", {"match": "tim hortons", "category": "eating out"})
    call(
        "POST",
        "/api/money/recurring",
        {"account_id": aid, "amount": -11.99, "payee": "spotify", "next_date": day(9)},
    )
    call(
        "POST",
        "/api/money/goals",
        {"name": "laptop", "target": 1500, "current": 400, "monthly": 100},
    )
    call(
        "POST",
        "/api/subscriptions",
        {
            "name": "spotify",
            "price": 11.99,
            "currency": "CAD",
            "cycle": "monthly",
            "next_due": day(6),
        },
    )
    call(
        "POST",
        "/api/subscriptions",
        {
            "name": "icloud",
            "price": 3.99,
            "currency": "CAD",
            "cycle": "monthly",
            "next_due": day(14),
        },
    )
    call("POST", "/api/notes", {"title": "chem formulas", "content": "NaCl, H2O, CO2"})
    call("POST", "/api/notes", {"title": "groceries", "content": "milk\neggs", "due": day(2)})
    call(
        "POST",
        "/api/vault-md/file",
        {"path": "school/boh4m notes.md", "content": "# boh4m\n\nemotional intelligence"},
    )
    call(
        "PUT", f"/api/journal/{day(0)}", {"content": "a long day, the lab went fine", "mood": "ok"}
    )
    call("PUT", f"/api/journal/{day(-1)}", {"content": "gym, then homework", "mood": "good"})
    call(
        "POST",
        "/api/contacts",
        {"name": "ms. patel", "email": "patel@example.test", "birthday": "1980-11-04"},
    )
    call("POST", "/api/contacts", {"name": "oscar", "phone": "555 0100"})
    call(
        "POST",
        "/api/books",
        {"title": "the pragmatic programmer", "author": "hunt and thomas", "status": "reading"},
    )
    call("POST", "/api/books", {"title": "dune", "author": "frank herbert", "status": "want"})
    call("POST", "/api/watch", {"name": "my site", "url": "http://127.0.0.1:9/", "kind": "http"})
    for name in ["chem study plan", "gym split", "essay outline"]:
        call("POST", "/api/sessions", {"name": name})
    call("POST", "/api/projects", {"name": "alles"})
    call("POST", "/api/files/mkdir", {"path": "school"})
    for name, body in [("lab report.txt", b"reaction rates"), ("notes.md", b"# boh4m")]:
        reply = api.post(
            base + "/api/files/upload",
            multipart={
                "path": "",
                "file": {"name": name, "mimeType": "text/plain", "buffer": body},
            },
        )
        if not reply.ok:
            failed.append(f"upload {name} {reply.status}")
    return failed


def detect(page):
    page.mouse.move(0, 0)
    page.wait_for_timeout(350)
    return page.evaluate(FIND)


def open_money(page, scan, view):
    """money keeps accounts, caps, schedules, goals, holdings and rules in sections that start
    shut: open both, walk the four plan tasks, and bring each card to the top of the screen
    before scanning, since a control scrolled out of its panel doesn't count as shown."""
    for name in ("plans", "analytics"):
        toggle = page.locator(f'[data-money-section="{name}"]')
        if toggle.count() and toggle.get_attribute("aria-expanded") == "false":
            toggle.click()
    page.wait_for_timeout(400)

    def cards(label):
        shown = page.locator("#money-view .money-card:visible")
        for n in range(shown.count()):
            card = shown.nth(n)
            card.evaluate("e => e.scrollIntoView({ block: 'start' })")
            page.wait_for_timeout(120)
            scan(f"{view}>{label}>{card.get_attribute('data-card') or 'card'}")

    for task in ("accounts", "budgets", "schedules", "goals"):
        pick_money_task(page, task)
        page.wait_for_timeout(300)
        cards(task)


def views(page, sub, base):
    """the group tabs the app shows, or aide's own pages."""
    if sub == "aide":
        return ["chat", *AIDE_VIEWS]
    tabs = page.evaluate(
        "[...document.querySelectorAll('[data-group-section]')]"
        ".filter(e => e.offsetParent).map(e => e.dataset.groupSection)"
    )
    return tabs or [""]


def run():
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    shots = os.environ.get("DELETE_SHOTS", "")
    shot_dir = Path(shots) if shots else None
    finds, excused, walked, matched = [], [], [], set()
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        seeded = browser.new_context(service_workers="block")
        failed = seed(seeded.request, base)
        seeded.close()
        for size, (width, height) in SIZES.items():
            context = browser.new_context(
                viewport={"width": width, "height": height},
                timezone_id="America/Toronto",
                service_workers="block",
                reduced_motion="reduce",
                has_touch=width <= 820,
            )
            page = context.new_page()
            errors = []
            page.on(
                "pageerror",
                # a poll cut off by the next app's page load is not a page bug
                lambda error: (
                    None
                    if re.search(
                        r"access control checks|Load failed|Fetch API cannot load", str(error)
                    )
                    else errors.append(str(error))
                ),
            )
            for sub in APPS:
                host = f"{sub}.localhost" if sub else "localhost"
                page.goto(f"http://{host}:{port}/")
                page.wait_for_timeout(2200)
                for view in views(page, sub, base):
                    if view and sub != "aide":
                        tab = page.locator(f'[data-group-section="{view}"]').first
                        if tab.count() and tab.is_visible():
                            tab.click()
                            page.wait_for_timeout(1400)
                    elif view and sub == "aide" and view != "chat":
                        page.goto(f"http://{host}:{port}/?view={view}")
                        page.wait_for_timeout(1600)
                    app = sub or "home"

                    def scan(label):
                        walked.append(f"{app}/{label}/{size}")
                        for item in detect(page):
                            key = (app, label, item["selector"])
                            item.update(app=app, view=label, size=size)
                            if key in ALLOWED:
                                matched.add(key)
                                excused.append(item)
                                continue
                            finds.append(item)
                            if shot_dir:
                                shot_dir.mkdir(parents=True, exist_ok=True)
                                name = re.sub(
                                    r"[^a-z0-9]+",
                                    "-",
                                    f"{app}-{label}-{item['selector'][-40:]}".lower(),
                                ).strip("-")
                                page.screenshot(path=str(shot_dir / f"{name}-{size}.png"))

                    scan(view or "-")
                    if app == "finance" and view == "money":
                        open_money(page, scan, view)
                    # tabs inside the view (money's plan tabs, tasks' lists, calendar's modes)
                    inner = page.locator(INNER_TABS)
                    names = [
                        " ".join(text.split())[:30]
                        for text in inner.all_inner_texts()
                        if text.strip()
                    ][:10]
                    for name in names:
                        again = page.locator(INNER_TABS).filter(has_text=name).first
                        if not again.count() or not again.is_visible():
                            continue
                        again.click()
                        page.wait_for_timeout(500)
                        scan(f"{view or '-'}>{name}")
            assert not errors, errors[:3]
            context.close()
        browser.close()
    print(f"walked {len(walked)} app views, {len(failed)} seed calls refused: {failed[:6]}")
    unique = {}
    for item in finds:
        found = unique.setdefault(
            (item["app"], item["view"], item["selector"]), {"sizes": set(), "labels": []}
        )
        found["sizes"].add(item["size"])
        if item["label"] not in found["labels"]:
            found["labels"].append(item["label"])
    for (app, view, selector), found in sorted(unique.items()):
        sizes, labels = ", ".join(sorted(found["sizes"])), found["labels"]
        print(f"FIND {app}/{view} [{sizes}] {selector}  ({len(labels)}x, e.g. {labels[0]})")
    if os.environ.get("DELETE_FINDS"):
        everything = {}
        for item in [*finds, *excused]:
            row = everything.setdefault(
                (item["app"], item["view"], item["selector"]),
                {"app": item["app"], "view": item["view"], "selector": item["selector"],
                 "label": item["label"], "sizes": set(),
                 "allowed": (item["app"], item["view"], item["selector"]) in ALLOWED},
            )  # fmt: skip
            row["sizes"].add(item["size"])
        rows = [{**row, "sizes": sorted(row["sizes"])} for row in everything.values()]
        Path(os.environ["DELETE_FINDS"]).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    stale = sorted(set(ALLOWED) - matched)
    assert not stale, f"ALLOWED entries that matched nothing (remove them): {stale}"
    assert not unique, f"{len(unique)} delete controls are visible at rest"


if __name__ == "__main__":
    run()
