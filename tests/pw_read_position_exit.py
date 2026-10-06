"""Actual page close sends the latest position with delayed older requests."""

import json
import os
import socket
import sqlite3
import time
import traceback
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    # A bound, non-listening owned proxy port rejects external traffic without
    # enabling Chromium Fetch interception. Loopback app requests bypass it.
    with socket.socket() as blocked_proxy, sync_playwright() as pw:
        blocked_proxy.bind(("127.0.0.1", 0))
        browser = pw.chromium.launch(
            proxy={
                "server": f"http://127.0.0.1:{blocked_proxy.getsockname()[1]}",
                "bypass": "127.0.0.1,localhost",
            }
        )
        for width in (1440, 390):
            for case in ("older-committed", "older-delayed", "older-committed-no-uuid"):
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )

                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                response = api.post(
                    base + "/api/read/save-news",
                    data={
                        "url": base + f"/owned-exit-{width}-{case}",
                        "title": f"local reading {width} {case}",
                        "excerpt": "owned fixture",
                    },
                )
                assert response.ok
                item = response.json()["item"]
                content = "\n\n".join(
                    f"Passage {i}. " + "Synthetic local article. " * 16 for i in range(70)
                )
                with sqlite3.connect(data / "aide.db") as db:
                    db.execute(
                        "UPDATE read_items SET text=?, read_position=? WHERE id=?",
                        (content, 0.4, item["id"]),
                    )
                url = base + "/api/read/" + item["id"]
                context.add_init_script(
                    """(() => {
                  const original = window.fetch.bind(window);
                  let held = null;
                  window.fetch = async (input, options) => {
                    if (String(input) === PATH && options?.method === 'PATCH' && !held) {
                      held = { body: JSON.parse(options.body), ready: false, pending: true };
                      window.ownedReadHold = held;
                      if (MODE.startsWith('older-committed')) {
                        const response = await original(input, options);
                        if (!response.ok) throw new Error('owned older position did not commit');
                      }
                      held.ready = true;
                      // Keep the response pending in page JavaScript through pagehide.
                      return new Promise(() => {});
                    }
                    return original(input, options);
                  };
                  window.addEventListener('pagehide', () => localStorage.setItem(
                    'owned-position-pagehide', JSON.stringify({
                      pending: held?.pending, ready: held?.ready,
                      status: document.querySelector('#read-position-status')?.textContent
                    })
                  ));
                })()""".replace("PATH", json.dumps("/api/read/" + item["id"])).replace(
                        "MODE", json.dumps(case)
                    )
                )
                if case.endswith("no-uuid"):
                    context.add_init_script(
                        "Object.defineProperty(crypto,'randomUUID',{value:undefined})"
                    )
                page = context.new_page()
                page.set_default_timeout(5000)
                errors, console = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                row = {
                    "scenario_id": "library.position-exit." + case,
                    "profile": str(width),
                    "status": "failed",
                }
                rows.append(row)
                context.tracing.start(screenshots=True, snapshots=True)

                def open_item():
                    page.goto(base + "/?view=library", wait_until="networkidle")
                    page.get_by_role("tab", name="saved", exact=True).click()
                    page.locator(f'[data-open="{item["id"]}"]').click()
                    expect(page.locator(".read-article h1")).to_have_text(item["title"])
                    page.wait_for_function('document.querySelector("#read-body").scrollTop>0')

                def scroll(value):
                    page.locator("#read-body").evaluate(
                        "(e,p)=>{e.scrollTop=p*(e.scrollHeight-e.clientHeight)}", value
                    )

                try:
                    open_item()
                    scroll(0.65)
                    page.wait_for_function("window.ownedReadHold?.ready === true")
                    held = page.evaluate("window.ownedReadHold.body")
                    expected = 0.65 if case.startswith("older-committed") else 0.4
                    assert abs(api.get(url).json()["position"] - expected) < 0.015
                    scroll(0.75)
                    page.wait_for_timeout(100)
                    row["latest_visible_position"] = page.locator("#read-body").evaluate(
                        "e=>e.scrollTop/(e.scrollHeight-e.clientHeight)"
                    )
                    assert abs(row["latest_visible_position"] - 0.75) < 0.015
                    expect(page.locator("#read-position-status")).to_have_text(
                        "saving reading place…"
                    )
                    page.close(run_before_unload=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            console.append(message.text) if message.type == "error" else None
                        ),
                    )
                    page.set_default_timeout(5000)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        stored = api.get(url).json()
                        if abs(stored["position"] - 0.75) < 0.015:
                            break
                        page.wait_for_timeout(20)
                    row["stored_position"] = stored["position"]
                    assert abs(stored["position"] - 0.75) < 0.015, row
                    if case == "older-delayed":
                        late = api.patch(url, data=held)
                        assert late.status == 409, late.text()
                        row["late_status"] = late.status
                        assert api.get(url).json()["position"] == stored["position"]
                    open_item()
                    row["pagehide_state"] = page.evaluate(
                        "JSON.parse(localStorage.getItem('owned-position-pagehide'))"
                    )
                    row["restored_position"] = page.locator("#read-body").evaluate(
                        "e=>e.scrollTop/(e.scrollHeight-e.clientHeight)"
                    )
                    assert row["pagehide_state"] == {
                        "pending": True,
                        "ready": True,
                        "status": "saving reading place…",
                    }, row
                    assert abs(row["restored_position"] - 0.75) < 0.015, row
                    assert not stored["read"]
                    assert not errors, errors
                    assert not console, console
                    row["status"] = "passed"
                except Exception as error:
                    row.update(error=str(error), traceback=traceback.format_exc())
                finally:
                    row.update(page_errors=errors, console_errors=console)
                    if not page.is_closed():
                        page.screenshot(path=str(out / f"{width}-{case}.png"))
                    context.tracing.stop(path=str(out / f"{width}-{case}.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
