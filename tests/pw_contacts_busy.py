"""Owned: a contact add while the database is write-locked says the server is busy, keeps the
draft, and shows the message on its own line under the fields without squeezing them (u.13).

The lock is real: a second sqlite connection holds the write lock on the gate's own database, so
the server's write waits out its busy timeout and answers 503 database_busy.
"""

import json
import os
import sqlite3
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

PROFILES = [("desktop", 1440, 900), ("ipad-landscape", 1180, 820), ("phone", 390, 844)]
BUSY = "Alles is busy for a moment. Try again."


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    require_server_ownership(base, run_id)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, width, height in PROFILES:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
                reduced_motion="reduce",
                has_touch=name == "phone",
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            errors, external = [], []
            record = {"profile": name, "status": "failed"}
            records.append(record)
            page.on("pageerror", lambda error: errors.append(str(error)))

            def boundary(route):
                if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort("blockedbyclient")

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda socket: socket.close())
            lock = None
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                page.goto(base + "/?view=contacts", wait_until="networkidle")
                page.locator("#contact-name").fill("Locked Test")
                page.locator("#contact-email").fill("locked@example.invalid")
                lock = sqlite3.connect(data / "aide.db", isolation_level=None, timeout=1)
                lock.execute("BEGIN IMMEDIATE")
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/contacts" and response.request.method == "POST"
                    ),
                    timeout=60000,
                ) as answer:
                    page.locator("#contact-add-btn").click()
                assert answer.value.status == 503
                assert answer.value.json()["code"] == "database_busy"
                error = page.locator("#contact-add-error")
                expect(error).to_have_text(BUSY)
                lock.execute("ROLLBACK")
                lock.close()
                lock = None
                # the draft is kept
                expect(page.locator("#contact-name")).to_have_value("Locked Test")
                expect(page.locator("#contact-email")).to_have_value("locked@example.invalid")
                # one line under the fields, full width, and the fields keep their room
                box = page.evaluate(
                    """() => {
                      const r = id => document.getElementById(id).getBoundingClientRect();
                      const row = document.querySelector('.contacts-create').getBoundingClientRect();
                      const e = r('contact-add-error'), n = r('contact-name');
                      const last = Math.max(...['contact-name', 'contact-email', 'contact-phone', 'contact-add-btn'].map(id => r(id).bottom));
                      return { errTop: e.top, errW: e.width, rowW: row.width, nameW: n.width, last,
                               inside: e.left >= row.left - 1 && e.right <= row.right + 1 };
                    }"""
                )
                assert box["errTop"] >= box["last"] - 1, box
                assert box["inside"] and box["errW"] >= box["rowW"] * 0.8, box
                assert box["nameW"] >= (150 if name != "phone" else 300), box
                record["box"] = box
                # a second try with the lock gone saves it
                page.locator("#contact-add-btn").click()
                expect(page.locator("#contact-add-error")).to_be_hidden()
                expect(page.locator("#contacts-list")).to_contain_text("Locked Test")
                assert not errors and not external, (errors, external)
                record["status"] = "passed"
            except Exception:
                record["error"] = traceback.format_exc()
                page.screenshot(path=str(output / f"{name}-failure.png"))
            finally:
                if lock is not None:
                    lock.execute("ROLLBACK")
                    lock.close()
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.close()
        browser.close()
    print(json.dumps(records, indent=2))
    assert all(record["status"] == "passed" for record in records)


if __name__ == "__main__":
    run()
