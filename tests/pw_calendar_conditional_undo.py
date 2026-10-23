"""Real stale quick-add undo and unchanged-event control on owned Calendar data."""

import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

STATE = """() => {
  const read = node => {
    if (!node) return null;
    const r = node.getBoundingClientRect(), css = getComputedStyle(node);
    const hit = document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
    return {id:node.id,tag:node.tagName,text:node.textContent,value:node.value,
      rect:{x:r.x,y:r.y,width:r.width,height:r.height},
      hidden:node.hidden,display:css.display,visibility:css.visibility,
      busy:node.getAttribute('aria-busy'),disabled:node.getAttribute('aria-disabled'),
      center_hit:!!hit && (hit===node || node.contains(hit))};
  };
  return {href:location.href,viewport:[innerWidth,innerHeight,devicePixelRatio],
    active:read(document.activeElement),quick:read(document.getElementById('cal-quick')),
    undo:read(document.getElementById('cal-quick-undo')),
    status:read(document.getElementById('cal-quick-status')),
    title:read(document.getElementById('cal-title')),description:read(document.getElementById('cal-desc'))};
}"""


def capture(context, page, target, width, height):
    cdp = context.new_cdp_session(page)
    try:
        data = base64.b64decode(
            cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})[
                "data"
            ]
        )
    finally:
        cdp.detach()
    target.write_bytes(data)
    pixels = struct.unpack(">II", data[16:24])
    assert pixels == (width, height), pixels
    return {"path": str(target), "sha256": hashlib.sha256(data).hexdigest(), "pixels": pixels}


def tab_to(page, selector, row):
    trail = {"target": selector, "active_sequence": []}
    row["keyboard"].append(trail)
    for _ in range(100):
        active = page.evaluate(
            "() => ({id:document.activeElement.id,tag:document.activeElement.tagName})"
        )
        trail["active_sequence"].append(active)
        if page.evaluate("s => document.activeElement.matches(s)", selector):
            return
        page.keyboard.press("Tab")
    raise AssertionError(f"normal Tab did not reach {selector}")


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, height in [(1440, 900), (390, 844)]:
                for theme in ["light", "dark"]:
                    label = f"{width}-{theme}"
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                        is_mobile=width == 390,
                        has_touch=width == 390,
                        service_workers="block",
                        reduced_motion="reduce",
                    )
                    row = {
                        "profile": label,
                        "status": "failed",
                        "rendered_pass": False,
                        "keyboard": [],
                        "checkpoints": [],
                        "receipts": [],
                        "before_undo": [],
                        "page_errors": [],
                        "console": [],
                        "http_errors": [],
                        "request_failures": [],
                        "unexpected": [],
                    }
                    rows.append(row)

                    def boundary(route):
                        url = urlsplit(route.request.url)
                        if (url.scheme, url.netloc) != (origin.scheme, origin.netloc):
                            row["unexpected"].append(route.request.url)
                            return route.abort()
                        return route.continue_()

                    context.route("**/*", boundary)
                    context.route_web_socket(
                        "**/*", lambda ws: (row["unexpected"].append(ws.url), ws.close())
                    )
                    page = context.new_page()
                    page.set_default_timeout(8000)
                    page.on("pageerror", lambda error: row["page_errors"].append(str(error)))
                    page.on(
                        "console",
                        lambda msg: row["console"].append(
                            {"type": msg.type, "text": msg.text, "location": msg.location}
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            row["http_errors"].append(
                                {
                                    "url": response.url,
                                    "status": response.status,
                                    "method": response.request.method,
                                }
                            )
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: row["request_failures"].append(
                            {
                                "url": request.url,
                                "method": request.method,
                                "failure": request.failure,
                            }
                        ),
                    )
                    writer = None

                    def checkpoint(name):
                        state = page.evaluate(STATE)
                        assert state["viewport"] == [width, height, 1], state["viewport"]
                        row["checkpoints"].append(
                            {
                                "name": name,
                                "state": state,
                                "capture": capture(
                                    context, page, out / f"{label}-{name}.png", width, height
                                ),
                            }
                        )

                    try:
                        assert context.request.post(base + "/api/setup/dismiss", max_redirects=0).ok
                        assert context.request.put(
                            base + "/api/appearance", data=from_legacy(theme, None), max_redirects=0
                        ).ok
                        page.goto(base + "/?view=calendar", wait_until="networkidle")
                        writer = pw.request.new_context(storage_state=context.storage_state())
                        auth = writer.get(base + "/api/auth/me", max_redirects=0)
                        assert auth.ok and auth.json()["authenticated"] is True
                        row["writer_auth"] = {
                            k: auth.json().get(k) for k in ["enabled", "authenticated"]
                        }
                        quick, undo = page.locator("#cal-quick"), page.locator("#cal-quick-undo")
                        status = page.locator("#cal-quick-status")
                        if not quick.is_visible():
                            page.locator("#cal-tools-toggle").click()
                        expect(quick).to_be_visible()

                        def saved():
                            response = writer.get(base + "/api/calendar", max_redirects=0)
                            assert response.ok, response.text()
                            return {event["id"]: event for event in response.json()}

                        def create(title):
                            if width == 390:
                                quick.tap()
                            else:
                                tab_to(page, "#cal-quick", row)
                            expect(quick).to_be_focused()
                            expect(quick).to_have_value("")
                            page.keyboard.insert_text(title + " today 1pm")
                            with page.expect_response(
                                lambda response: (
                                    response.url == base + "/api/calendar/quick"
                                    and response.request.method == "POST"
                                )
                            ) as pending:
                                page.keyboard.press("Enter")
                            response = pending.value
                            event = response.json()
                            row["receipts"].append(
                                {
                                    "kind": "quick-add",
                                    "status": response.status,
                                    "request": response.request.post_data_json,
                                    "body": event,
                                }
                            )
                            assert response.status == 200
                            expect(undo).to_be_visible()
                            expect(undo).to_have_attribute("aria-disabled", "false")
                            expect(status).to_have_text("added “" + event["title"] + "”")
                            return event

                        def activate_undo(event):
                            if width != 390:
                                tab_to(page, "#cal-quick-undo", row)
                                expect(undo).to_be_focused()
                            row["before_undo"].append(page.evaluate(STATE))
                            target = base + "/api/calendar/" + quote(event["id"], safe="")
                            with page.expect_response(
                                lambda response: (
                                    response.url == target and response.request.method == "DELETE"
                                )
                            ) as pending:
                                undo.tap() if width == 390 else page.keyboard.press("Enter")
                            response = pending.value
                            receipt = {
                                "kind": "undo",
                                "url": response.url,
                                "status": response.status,
                                "request": response.request.post_data_json,
                                "body": response.json(),
                            }
                            row["receipts"].append(receipt)
                            assert receipt["request"] == event, receipt
                            expect(undo).to_have_attribute("aria-busy", "false")
                            return receipt

                        original = create(
                            "owned keep " + theme + (" phone" if width == 390 else " desktop")
                        )
                        row["original"] = original
                        handle = undo.element_handle()
                        checkpoint("added")
                        patch = {
                            "title": "newer " + original["title"],
                            "description": "second writer keeps these exact notes\n中文 草稿",
                        }
                        conflict_url = base + "/api/calendar/" + quote(original["id"], safe="")
                        changed = writer.patch(conflict_url, data=patch, max_redirects=0)
                        newer = changed.json()
                        row["second_writer"] = {
                            "method": "PATCH",
                            "status": changed.status,
                            "request": patch,
                            "body": newer,
                        }
                        assert changed.status == 200 and newer == {**original, **patch}
                        for attempt in [1, 2]:
                            assert handle.evaluate(
                                "node => node === document.getElementById('cal-quick-undo')"
                            )
                            receipt = activate_undo(original)
                            assert receipt["status"] == 409, receipt
                            assert receipt["body"] == {
                                "detail": "This event changed after quick add. Newer changes were kept."
                            }
                            expect(status).to_have_text(
                                "could not confirm removing “"
                                + original["title"]
                                + "”. try undo again."
                            )
                            expect(undo).to_be_visible()
                            expect(undo).to_have_attribute("aria-disabled", "false")
                            expect(quick).to_have_value("")
                            if width != 390:
                                expect(undo).to_be_focused()
                            retained = saved()[original["id"]]
                            row[f"retained_after_conflict_{attempt}"] = retained
                            assert retained == newer
                            checkpoint(f"conflict-{attempt}")

                        normal = create(
                            "owned remove " + theme + (" phone" if width == 390 else " desktop")
                        )
                        assert normal["id"] != original["id"]
                        receipt = activate_undo(normal)
                        assert receipt["status"] == 200 and receipt["body"] == {"ok": True}
                        expect(status).to_have_text("removed “" + normal["title"] + "”")
                        expect(undo).to_be_hidden()
                        expect(quick).to_have_attribute("aria-busy", "false")
                        if width != 390:
                            expect(quick).to_be_focused()
                        retained = saved()
                        assert normal["id"] not in retained and retained[original["id"]] == newer
                        checkpoint("normal-removed")
                        page.reload(wait_until="networkidle")
                        retained = saved()
                        assert normal["id"] not in retained and retained[original["id"]] == newer
                        row["retained_after_reload"] = retained[original["id"]]
                        page.locator('#cal-view [data-view="agenda"]').click()
                        event_row = page.locator(f'.cal-agenda-ev[data-id="{original["id"]}"]')
                        expect(event_row.locator(".cal-agenda-title")).to_have_text(newer["title"])
                        event_row.tap() if width == 390 else event_row.click()
                        expect(page.locator("#cal-title")).to_have_value(newer["title"])
                        expect(page.locator("#cal-desc")).to_have_value(newer["description"])
                        page.wait_for_load_state("networkidle")
                        checkpoint("reloaded-editor")
                        expected = {"url": conflict_url, "status": 409, "method": "DELETE"}
                        assert row["http_errors"] == [expected, expected], row["http_errors"]
                        errors = [entry for entry in row["console"] if entry["type"] == "error"]
                        assert len(errors) == 2 and all(
                            entry["text"]
                            == "Failed to load resource: the server responded with a status of 409 (Conflict)"
                            and entry["location"].get("url") == conflict_url
                            for entry in errors
                        ), errors
                        assert (
                            not row["page_errors"]
                            and not row["unexpected"]
                            and not row["request_failures"]
                        ), row
                        row["status"] = "passed"
                    except Exception:
                        row["error"] = traceback.format_exc()
                        try:
                            checkpoint("failure")
                        except Exception:
                            row["failure_capture_error"] = traceback.format_exc()
                        raise
                    finally:
                        (out / "calendar-conditional-undo.json").write_text(
                            json.dumps(rows, indent=2) + "\n"
                        )
                        if writer:
                            writer.dispose()
                        context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    run()
