"""ui-4d verify — compose: chip To/Cc/Bcc with autocomplete, Cc/Bcc toggles, a real
date+time schedule picker, and dirty-close confirm."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://mail.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def chip(pg, sel, text, key="Enter"):
    pg.evaluate("""([sel, text, key]) => {
      const inp = document.querySelector(sel);
      inp.value = text;
      inp.dispatchEvent(new Event('input', {bubbles:true}));
      inp.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles:true, cancelable:true}));
    }""", [sel, text, key])


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1300, "height": 950})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.route("**/api/mail/recipients**", lambda r: r.fulfill(status=200, content_type="application/json",
                 body='{"recipients":[{"email":"ada@math.org","name":"Ada Lovelace"},{"email":"adam@x.com","name":""}]}'))
        pg.route("**/api/contacts**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-compose-btn", state="attached", timeout=15000)
        pg.wait_for_timeout(2200)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # open compose
        pg.evaluate("() => document.querySelector('#mail-compose-btn').click()")
        pg.wait_for_timeout(600)
        ok("compose opens with chip fields", pg.query_selector(".mc-chipfield[data-role='to']") is not None)
        ok("cc/bcc hidden by default", pg.evaluate("() => getComputedStyle(document.querySelector('#mc-cc-row')).display") == "none")

        toInput = ".mc-chipfield[data-role='to'] .mc-chip-input"
        chip(pg, toInput, "a@b.com")
        pg.wait_for_timeout(200)
        chip(pg, toInput, "c@d.com", key=",")
        pg.wait_for_timeout(200)
        d = pg.evaluate("""() => ({
          chips: document.querySelectorAll('.mc-chipfield[data-role=to] .mc-chip').length,
          hidden: document.querySelector('#mc-to').value,
        })""")
        ok("typing + Enter/comma makes chips", d["chips"] == 2)
        ok("chips mirror to the hidden field", "a@b.com" in d["hidden"] and "c@d.com" in d["hidden"])

        # backspace on empty removes the last chip
        pg.evaluate("""() => { const i = document.querySelector(".mc-chipfield[data-role=to] .mc-chip-input"); i.value=''; i.dispatchEvent(new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true})); }""")
        pg.wait_for_timeout(200)
        ok("backspace on empty pulls back the last chip", pg.evaluate("() => document.querySelectorAll('.mc-chipfield[data-role=to] .mc-chip').length") == 1)

        # Cc toggle reveals the cc row
        pg.evaluate("() => document.querySelector('#mc-add-cc').click()")
        pg.wait_for_timeout(200)
        ok("Cc toggle reveals the cc field", pg.evaluate("() => getComputedStyle(document.querySelector('#mc-cc-row')).display") != "none")

        # autocomplete: type 'ada' → dropdown with the mocked recipient
        pg.evaluate("""() => { const i=document.querySelector(".mc-chipfield[data-role=to] .mc-chip-input"); i.value='ada'; i.dispatchEvent(new Event('input',{bubbles:true})); }""")
        pg.wait_for_timeout(400)
        ac = pg.evaluate("() => { const e=document.querySelector('.mc-ac'); return e ? e.innerText.toLowerCase() : ''; }")
        ok("autocomplete dropdown appears", "ada@math.org" in ac and "lovelace" in ac)

        # schedule: first click reveals date + time pickers
        pg.evaluate("() => document.querySelector('#mc-schedule').click()")
        pg.wait_for_timeout(300)
        sch = pg.evaluate("""() => ({
          shown: getComputedStyle(document.querySelector('#mc-sched-wrap')).display !== 'none',
          date: !!document.querySelector('#mc-sched-date.date-input'),
          time: !!document.querySelector('#mc-sched-time'),
          label: document.querySelector('#mc-schedule').textContent,
        })""")
        ok("schedule reveals a date picker + time", sch["shown"] and sch["date"] and sch["time"])
        ok("schedule button updates its label", "send" in sch["label"])

        # dirty-close prompts a confirm
        pg.evaluate("() => document.querySelector('#mc-close').click()")
        pg.wait_for_timeout(300)
        ok("closing a dirty compose asks to confirm", pg.query_selector("#_dy") is not None)
        pg.evaluate("() => document.querySelector('#_dn')?.click()")

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
