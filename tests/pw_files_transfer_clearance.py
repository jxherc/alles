"""Keep populated Files rows reachable with retained transfer failures visible."""

from __future__ import annotations

import json
import os
import sqlite3
import traceback
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

DATA = Path(os.environ["ALLES_DATA"]).resolve()
BASE = f"http://files.localhost:{os.environ['PORT']}"
OUTPUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])


def run():
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (DATA / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(BASE, run_id)
    root = DATA / "files"
    root.mkdir(exist_ok=True)
    (root / "collisions").mkdir()
    for index in range(18):
        (root / f"{index:02}-会议-record-résumé.txt").write_text(f"original {index}")
    for index in range(3):
        (root / "collisions" / f"{index:02}-会议-record-résumé.txt").write_text(
            f"destination {index}"
        )
    (root / "zz-last-record.txt").write_text("last original")
    scenarios, failures = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for profile, width, height in (("desktop", 1440, 920), ("phone", 390, 844)):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                has_touch=profile == "phone",
                is_mobile=profile == "phone",
                service_workers="block",
                reduced_motion="reduce",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(5000)
            network, errors, observations, ids = [], [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "requestfailed",
                lambda request: network.append({"url": request.url, "failure": request.failure}),
            )
            page.on(
                "response",
                lambda response: (
                    network.append({"url": response.url, "status": response.status})
                    if response.status >= 400
                    else None
                ),
            )

            def unobscured(control, label):
                state = control.evaluate(
                    "element => { const r=element.getBoundingClientRect(), dock=document.querySelector('#files-operation-dock'), d=dock.getBoundingClientRect(), hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return {row:{x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom},dock:{y:d.y,height:d.height,bottom:d.bottom},hit:hit?.outerHTML,clear:!!hit&&(hit===element||element.contains(hit)),dockVisible:!dock.hidden,scroll:{view:document.querySelector('#files-view').scrollTop,list:document.querySelector('#files-list').scrollTop},styles:['#files-view','#files-list','.files-phase7-browser'].map(sel=>{const e=document.querySelector(sel),s=getComputedStyle(e);return {sel,height:e.clientHeight,scroll:e.scrollHeight,padding:s.paddingBottom,clearance:s.getPropertyValue('--files-operation-clearance'),flex:s.flex};})}; }"
                )
                observations.append({"label": label, **state})
                assert state["dockVisible"]
                # The phone transfer region now scrolls before the file list; desktop
                # retains the lower dock. Both layouts must keep the control unobscured.
                assert state["clear"] and (
                    state["row"]["bottom"] <= state["dock"]["y"]
                    or state["dock"]["bottom"] <= state["row"]["y"]
                ), state

            def lower_row(case):
                page.mouse.move(width - 70, min(height - 310, 450))
                page.mouse.wheel(0, 3000)
                last = page.locator('.file-row[data-path="zz-last-record.txt"] [data-file-open]')
                # Native scrolling is asynchronous. Wait for the actual scroll owner to reach its end.
                page.wait_for_function(
                    "() => { const e=innerWidth<=760?document.querySelector('#files-view'):document.querySelector('#files-list'); return e.scrollTop+e.clientHeight>=e.scrollHeight-2; }"
                )
                page.screenshot(
                    path=str(OUTPUT / f"{profile}-{case}-lower-row.png"), full_page=True
                )
                unobscured(last, case + " pointer")
                last.tap() if profile == "phone" else last.click()
                expect(page.locator("#files-detail-panel")).to_be_visible()
                expect(page.locator(".files-detail-name")).to_have_text("zz-last-record.txt")
                page.locator("#files-detail-close").click()
                expect(page.locator('.file-row[data-path="zz-last-record.txt"]')).to_be_focused()
                # Traverse back to an ordinary lower row and return through actual Tab input.
                page.keyboard.press("Shift+Tab")
                page.keyboard.press("Shift+Tab")
                for _ in range(5):
                    page.keyboard.press("Tab")
                    active = page.locator(":focus")
                    if (
                        active.get_attribute("data-file-open") is not None
                        and active.inner_text() == "zz-last-record.txt"
                    ):
                        unobscured(active, case + " keyboard")
                        page.keyboard.press("Enter")
                        break
                else:
                    raise AssertionError("last file did not remain keyboard reachable")
                expect(page.locator(".files-detail-name")).to_have_text("zz-last-record.txt")
                page.locator("#files-detail-close").click()
                assert (root / "zz-last-record.txt").read_text() == "last original"
                assert page.locator("#files-operation-dock").is_visible()
                # A natural-height list must not squeeze the neighboring selection actions.
                page.locator('.file-row[data-path="zz-last-record.txt"] [data-file-select]').click()
                expect(page.locator(".files-phase7-selection-actions")).to_be_visible()
                page.locator('[data-files-bulk="copy"]').click()
                expect(page.locator("#files-transfer-dialog")).to_be_visible()
                page.locator("#files-transfer-dialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                page.locator('[data-files-bulk="clear"]').click()
                expect(page.locator("#files-selection-bar")).to_be_hidden()
                assert page.locator("#files-operation-dock").is_visible()

            try:
                page.goto(BASE, wait_until="networkidle")
                # Queue genuine local copy collisions through the API. The real list renders their saved failures.
                for index in range(3):
                    queued = context.request.post(
                        BASE + "/api/files/operations",
                        data={
                            "action": "copy",
                            "source_location_id": "default-local",
                            "source_path": f"{index:02}-会议-record-résumé.txt",
                            "destination_location_id": "default-local",
                            "destination_path": f"collisions/{index:02}-会议-record-résumé.txt",
                            "run_now": False,
                        },
                    )
                    assert queued.ok, queued.text()
                    operation_id = queued.json()["id"]
                    ids.append(operation_id)
                    failed = context.request.post(
                        BASE + f"/api/files/operations/{operation_id}/run"
                    )
                    assert failed.status == 409, failed.text()
                    if index == 0:
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".files-operation-error")).to_have_text(
                            "destination already exists"
                        )
                        lower_row("single")
                        scenarios.append(
                            {
                                "scenario_id": "files.transfer-clearance-single",
                                "profile": profile,
                                "status": "passed",
                                "evidence": [
                                    f"{profile}-trace.zip",
                                    f"{profile}-observations.json",
                                ],
                            }
                        )
                # Persist 160-character synthetic provider reasons to exercise the supported maximum error length.
                reason = (
                    "synthetic destination unavailable: permission denied while copying 会议 records; reconnect this location and retry. "
                    * 2
                )[:159] + "."
                with sqlite3.connect(DATA / "aide.db") as db:
                    db.executemany(
                        "UPDATE file_operations SET error_code=? WHERE id=?",
                        [(reason, value) for value in ids],
                    )
                page.reload(wait_until="networkidle")
                expect(page.locator(".files-operation-error")).to_have_count(3)
                for mode, current_height in (("normal", height), ("constrained", 600)):
                    page.set_viewport_size({"width": width, "height": current_height})
                    height = current_height
                    for theme in ("light", "dark"):
                        page.evaluate(
                            "theme => import('/static/js/theme.js').then(m => m.resetToDefault(theme))",
                            theme,
                        )
                        lower_row(f"multiple-{mode}-{theme}")
                        dock = page.locator("#files-operation-dock")
                        bounds = dock.bounding_box()
                        assert bounds and bounds["height"] <= 241, bounds
                        # The last long error is inside the independently scrolling transfer panel.
                        page.mouse.move(width - 100, current_height - 60)
                        page.mouse.wheel(0, 1500)
                        last_error = page.locator(".files-operation-error").last
                        expect(last_error).to_be_visible()
                        assert last_error.inner_text() == reason, {
                            "expected": reason,
                            "actual": last_error.inner_text(),
                        }
                        assert last_error.evaluate(
                            "element => element.scrollWidth <= element.clientWidth"
                        )
                        page.screenshot(
                            path=str(OUTPUT / f"{profile}-errors-{mode}-{theme}.png"),
                            full_page=True,
                        )
                    scenarios.append(
                        {
                            "scenario_id": f"files.transfer-clearance-multiple-{mode}",
                            "profile": profile,
                            "status": "passed",
                            "evidence": [f"{profile}-trace.zip", f"{profile}-observations.json"],
                            "simulation": "three real failed copy rows with explicitly seeded 160-character error reasons",
                        }
                    )
                assert errors == [] and network == [], {"errors": errors, "network": network}
                for index in range(3):
                    assert (
                        root / f"{index:02}-会议-record-résumé.txt"
                    ).read_text() == f"original {index}"
                    assert (
                        root / "collisions" / f"{index:02}-会议-record-résumé.txt"
                    ).read_text() == f"destination {index}"
            except Exception as error:
                failures.append(
                    {"profile": profile, "error": str(error), "traceback": traceback.format_exc()}
                )
            finally:
                page.screenshot(path=str(OUTPUT / f"{profile}-final.png"), full_page=True)
                try:
                    # Fixture teardown only; never dismiss/hide during reachability checks.
                    for operation_id in ids:
                        assert context.request.delete(
                            BASE + f"/api/files/operations/{operation_id}"
                        ).ok
                    if not any(failure["profile"] == profile for failure in failures):
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#files-operation-dock")).to_be_hidden()
                        clearance = page.locator("#files-view").evaluate(
                            "element => getComputedStyle(element).getPropertyValue('--files-operation-clearance').trim()"
                        )
                        padding = page.locator("#files-list").evaluate(
                            "element => parseFloat(getComputedStyle(element).paddingBottom)"
                        )
                        observations.append(
                            {
                                "label": "reset after fixture teardown",
                                "clearance": clearance,
                                "padding": padding,
                            }
                        )
                        assert clearance == "0px" and padding <= 32
                        assert errors == [] and network == [], {
                            "errors": errors,
                            "network": network,
                        }
                        scenarios.append(
                            {
                                "scenario_id": "files.transfer-clearance-reset",
                                "profile": profile,
                                "status": "passed",
                                "evidence": [
                                    f"{profile}-trace.zip",
                                    f"{profile}-observations.json",
                                ],
                                "detail": "fixture teardown clears retained operations; reload removes reserved clearance",
                            }
                        )
                except Exception as error:
                    failures.append(
                        {
                            "profile": profile,
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    (OUTPUT / f"{profile}-observations.json").write_text(
                        json.dumps(observations, indent=2)
                    )
                    (OUTPUT / f"{profile}-events.json").write_text(
                        json.dumps({"errors": errors, "network": network}, indent=2)
                    )
                    context.tracing.stop(path=str(OUTPUT / f"{profile}-trace.zip"))
                    context.close()
        browser.close()
    (OUTPUT / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
    (OUTPUT / "failures.json").write_text(json.dumps(failures, indent=2))
    assert not failures, failures
    print("retained Files transfer panel clearance passed")


if __name__ == "__main__":
    run()
