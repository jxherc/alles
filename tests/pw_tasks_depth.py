"""tasks UI depth smoke. :8894."""

import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

TASKS = "http://tasks.localhost:8894"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "tasks"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def _iso(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{TASKS}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#task-add-input", timeout=15000)
        pg.evaluate(
            """async () => {
                const active = await fetch('/api/tasks').then(r => r.json());
                const done = await fetch('/api/tasks/done').then(r => r.json());
                for (const t of [...active, ...done]) await fetch('/api/tasks/' + t.id, {method:'DELETE'});
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#task-add-input", timeout=15000)

        # quick-add parses priority/tags/due and shows them in the list
        pg.fill("#task-add-input", "call mom tomorrow !! #home")
        pg.press("#task-add-input", "Enter")
        pg.wait_for_function(
            "document.querySelector('#tasks-list')?.textContent.includes('call mom')"
        )
        txt = pg.text_content("#tasks-list") or ""
        mom = pg.evaluate(
            "() => fetch('/api/tasks').then(r=>r.json()).then(rows => rows.find(t => t.title === 'call mom'))"
        )
        r["quick_add_priority_tags_due"] = (
            "call mom" in txt
            and "#home" in txt
            and "high" in txt
            and mom
            and mom.get("priority") == 3
            and mom.get("due_date") == _iso(1)
            and "home" in (mom.get("tags") or [])
        )

        # adding while a search is active clears the search so the new task stays visible
        pg.fill("#tasks-search", "nothing-matches-this")
        pg.wait_for_function(
            "document.querySelector('#tasks-list')?.textContent.includes('nothing here')"
        )
        pg.fill("#task-add-input", "visible after search clear !")
        pg.press("#task-add-input", "Enter")
        pg.wait_for_function(
            "document.querySelector('#tasks-list')?.textContent.includes('visible after search clear')"
        )
        r["add_clears_search_filter"] = pg.input_value(
            "#tasks-search"
        ) == "" and "visible after search clear" in (pg.text_content("#tasks-list") or "")

        # reschedule chips stage the date; cancel should not persist it
        tid = pg.evaluate(
            """async () => {
                const rows = await fetch('/api/tasks').then(r => r.json());
                return rows.find(t => t.title === 'visible after search clear')?.id;
            }"""
        )
        pg.eval_on_selector(f'.task-item[data-id="{tid}"] .task-title', "el => el.click()")
        pg.wait_for_selector(".task-editor", timeout=6000)
        pg.click('.te-rs[data-w="next_week"]')
        pg.click("#te-cancel")
        pg.wait_for_selector(".task-editor", state="detached", timeout=5000)
        due_after_cancel = pg.evaluate(
            f"() => fetch('/api/tasks').then(r=>r.json()).then(rows => rows.find(t => t.id === '{tid}')?.due_date || '')"
        )
        r["reschedule_cancel_does_not_persist"] = due_after_cancel == ""

        pg.eval_on_selector(f'.task-item[data-id="{tid}"] .task-title', "el => el.click()")
        pg.wait_for_selector(".task-editor", timeout=6000)
        pg.click('.te-rs[data-w="tomorrow"]')
        pg.click("#te-save")
        pg.wait_for_selector(".task-editor", state="detached", timeout=5000)
        pg.wait_for_function(
            f"() => fetch('/api/tasks').then(r=>r.json()).then(rows => "
            f"rows.find(t => t.id === '{tid}')?.due_date === '{_iso(1)}')"
        )
        r["reschedule_save_persists"] = pg.evaluate(
            f"() => fetch('/api/tasks').then(r=>r.json()).then(rows => rows.find(t => t.id === '{tid}')?.due_date || '')"
        ) == _iso(1)

        # tree shows subtasks and progress
        pg.evaluate(
            """async () => {
                const parent = await fetch('/api/tasks', {method:'POST', headers:{'content-type':'application/json'},
                    body:JSON.stringify({title:'project parent'})}).then(r=>r.json());
                await fetch('/api/tasks', {method:'POST', headers:{'content-type':'application/json'},
                    body:JSON.stringify({title:'first child', parent_id:parent.id})});
                const done = await fetch('/api/tasks', {method:'POST', headers:{'content-type':'application/json'},
                    body:JSON.stringify({title:'done child', parent_id:parent.id})}).then(r=>r.json());
                await fetch('/api/tasks/' + done.id, {method:'PATCH', headers:{'content-type':'application/json'},
                    body:JSON.stringify({done:true})});
            }"""
        )
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#task-add-input", timeout=15000)
        pg.wait_for_function(
            "document.querySelector('#tasks-list')?.textContent.includes('project parent')"
        )
        tree_txt = pg.text_content("#tasks-list") or ""
        r["subtasks_progress_render"] = (
            "project parent" in tree_txt and "first child" in tree_txt and "1/2" in tree_txt
        )

        # tabs use their real endpoints
        pg.click('.tasks-tab[data-tab="upcoming"]')
        pg.wait_for_timeout(500)
        r["upcoming_tab_lists_due"] = "visible after search clear" in (
            pg.text_content("#tasks-list") or ""
        )
        pg.click('.tasks-tab[data-tab="someday"]')
        pg.wait_for_timeout(500)
        r["someday_tab_lists_undated"] = "project parent" in (pg.text_content("#tasks-list") or "")
        pg.click('.tasks-tab[data-tab="done"]')
        pg.wait_for_timeout(500)
        r["history_tab_lists_done"] = "done child" in (pg.text_content("#tasks-list") or "")
        pg.screenshot(path=str(EVID / "tasks-depth.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_tasks_depth.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
