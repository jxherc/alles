"""Owned Calendar invite races and refused import/booking recovery; no mail delivery."""

import base64
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    day = datetime.now(timezone.utc).date().isoformat()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme, zoom in [
            (1440, "dark", False),
            (390, "light", False),
            (1440, "light", True),
        ]:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                timezone_id="UTC",
                reduced_motion="reduce",
                service_workers="block",
                has_touch=width == 390,
            )
            if zoom:
                profile = data / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned calendar zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
                    )
                )
                (extension / "zoom.js").write_text(
                    "chrome.runtime.onInstalled.addListener(() => {});"
                )
                context = pw.chromium.launch_persistent_context(
                    profile / "browser",
                    channel="chromium",
                    headless=True,
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    **options,
                )
            else:
                context = browser.new_context(**options)
            page = context.new_page()
            page.set_default_timeout(10000)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            errors, console, external, held, api_writes = [], [], [], [], []
            row = {"profile": label, "status": "failed"}
            records.append(row)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console.append({"text": message.text, "url": message.location.get("url", "")})
                    if message.type == "error"
                    else None
                ),
            )

            def local_only(route):
                if urlsplit(route.request.url).netloc != urlsplit(base).netloc:
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local_only)
            context.route_web_socket("**/*", lambda websocket: websocket.close())
            api = context.request

            def rows():
                result = api.get(base + "/api/calendar")
                assert result.ok, result.text()
                return result.json()

            def open_event(eid):
                page.locator('#cal-view [data-view="month"]').click()
                page.locator("#cal-today").click()
                chip = page.locator(f'.cal-chip[data-id="{eid}"]')
                expect(
                    page.locator(f'.cal-chip[data-id="{eid}"], .cal-more[data-day="{day}"]').first
                ).to_be_visible()
                # the month trims lines a frame after it draws; read it once that's done
                page.evaluate(
                    "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
                )
                if chip.count():
                    chip.press("Enter")
                else:
                    # a short month cell (phone, 200% zoom) keeps the rest behind "+N more"
                    page.locator(f'.cal-more[data-day="{day}"]').press("Enter")
                    page.locator(f'.cal-tev[data-id="{eid}"]').click()
                expect(page.locator("#cal-inv-btn")).to_be_visible()

            def tools():
                if not page.locator("#cal-more-btn").is_visible():
                    page.locator("#cal-tools-toggle").click()

            def menu_item(selector):
                tools()
                item = page.locator(selector)
                if not item.is_visible():
                    page.locator("#cal-more-btn").click()
                expect(item).to_be_visible()
                return item

            def prompt(value):
                dialog = page.get_by_role("dialog")
                expect(dialog).to_be_visible()
                dialog.locator("input").fill(value)
                dialog.locator("input").press("Enter")

            def snapshot(name):
                session = context.new_cdp_session(page)
                try:
                    image = session.send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )
                    (output / f"{label}-{name}.png").write_bytes(base64.b64decode(image["data"]))
                finally:
                    session.detach()

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert not api.get(base + "/api/settings").json().get("mail_accounts")
                assert api.patch(base + "/api/settings", data={"language": "en", "theme": theme}).ok
                owners = {}
                for key, hour in [("A", "09"), ("B", "11")]:
                    result = api.post(
                        base + "/api/calendar",
                        data={"title": label + " " + key, "start_dt": day + f"T{hour}:00"},
                    )
                    assert result.ok, result.text()
                    owners[key] = result.json()["id"]
                    # The owned server must stub delivery; this persists only synthetic attendee rows.
                    result = api.post(
                        base + f"/api/calendar/{owners[key]}/invite",
                        data={"name": key + " existing", "email": key.lower() + "@example.invalid"},
                    )
                    assert result.ok, result.text()
                page.goto(base + "/?view=calendar", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")

                def hold_invite(route):
                    held.append(route)
                    api_writes.append(
                        {"url": route.request.url, "body": route.request.post_data_json}
                    )

                page.route("**/api/calendar/*/invite", hold_invite)
                open_event(owners["A"])
                expect(page.locator("#cal-invites")).to_contain_text("A existing")
                page.locator("#cal-inv-name").fill("A pending")
                page.locator("#cal-inv-email").fill("a-pending@example.invalid")
                page.locator("#cal-inv-btn").press("Enter")
                expect(page.locator("#cal-inv-btn")).to_be_disabled()
                open_event(owners["B"])
                expect(page.locator("#cal-invites")).to_contain_text("B existing")
                page.locator("#cal-inv-name").fill("B independent draft")
                page.locator("#cal-inv-email").fill("b-draft@example.invalid")
                page.locator("#cal-inv-email").focus()
                assert len(held) == 1
                request = held.pop()
                saved = request.fetch()
                assert saved.ok, saved.text()
                request.fulfill(response=saved)
                page.wait_for_load_state("networkidle")
                expect(page.locator("#cal-inv-name")).to_have_value("B independent draft")
                expect(page.locator("#cal-inv-email")).to_have_value("b-draft@example.invalid")
                expect(page.locator("#cal-inv-email")).to_be_focused()
                expect(page.locator("#cal-invites")).to_contain_text("B existing")
                expect(page.locator("#cal-invites")).not_to_contain_text("A pending")
                assert len(api.get(base + f"/api/calendar/{owners['A']}/attendees").json()) == 2
                assert len(api.get(base + f"/api/calendar/{owners['B']}/attendees").json()) == 1
                page.locator("#cal-inv-email").evaluate(
                    "el => el.scrollIntoView({block: 'center'})"
                )
                snapshot("invite-owner")
                page.unroute("**/api/calendar/*/invite", hold_invite)

                tools()
                before = rows()
                ics = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{label}-synthetic-import\r\nDTSTART:{day.replace('-', '')}T150000\r\nDTEND:{day.replace('-', '')}T160000\r\nSUMMARY:{label} imported\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"

                # A malformed real file remains available for replacement without partial writes.
                with page.expect_file_chooser() as chooser:
                    menu_item("#cal-import").click()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/calendar/import")
                ) as malformed:
                    chooser.value.set_files(
                        {
                            "name": "malformed.ics",
                            "mimeType": "text/calendar",
                            "buffer": b"not a calendar",
                        }
                    )
                assert malformed.value.status == 400
                expect(page.locator("#cal-import-status")).to_contain_text("malformed.ics")
                expect(page.locator("#cal-import-status")).to_contain_text("isn't a calendar file")
                expect(page.locator("#cal-import-retry")).to_be_enabled()
                assert rows() == before

                def malformed_receipt(route):
                    route.fulfill(status=200, json={"imported": "unknown"})

                page.route("**/api/calendar/import", malformed_receipt)
                with page.expect_file_chooser() as chooser:
                    page.locator("#cal-import-choose").click()
                chooser.value.set_files(
                    {"name": "unconfirmed.ics", "mimeType": "text/calendar", "buffer": ics.encode()}
                )
                expect(page.locator("#cal-import-status")).to_contain_text("wasn't confirmed")
                assert rows() == before
                page.unroute("**/api/calendar/import", malformed_receipt)

                def refuse_import(route):
                    route.fulfill(status=503, json={"detail": "synthetic import unavailable"})

                page.route("**/api/calendar/import", refuse_import)
                with page.expect_file_chooser() as chooser:
                    menu_item("#cal-import").click()
                chooser.value.set_files(
                    {"name": "synthetic.ics", "mimeType": "text/calendar", "buffer": ics.encode()}
                )
                expect(page.locator("#cal-import-status")).to_contain_text("synthetic.ics")
                expect(page.locator("#cal-import-status")).to_contain_text("wasn't confirmed")
                assert (
                    page.locator("#cal-import-file").evaluate("el => el.files[0].name")
                    == "synthetic.ics"
                )
                assert rows() == before
                page.locator("#cal-import-retry").focus()
                page.keyboard.press("Tab")
                expect(page.locator("#cal-import-choose")).to_be_focused()
                for control in page.locator("#cal-import-feedback button").all():
                    bounds = control.bounding_box()
                    assert bounds["width"] >= 44 and bounds["height"] >= 44, bounds
                snapshot("import-refused")
                page.unroute("**/api/calendar/import", refuse_import)
                with page.expect_response(
                    lambda response: response.url.endswith("/api/calendar/import")
                ) as imported:
                    page.locator("#cal-import-retry").press("Enter")
                assert imported.value.ok and imported.value.json()["imported"] == 1
                expect(page.locator("#cal-inv-name")).to_have_value("B independent draft")
                expect(page.locator("#cal-inv-email")).to_have_value("b-draft@example.invalid")
                assert len(rows()) == len(before) + 1
                assert page.locator("#cal-import-file").input_value() == ""
                expect(page.locator("#cal-import-feedback")).to_be_hidden()
                expect(page.locator("#cal-more-btn")).to_be_focused()

                # Refuse a second file, then prove both replacement-picker entry points work.
                page.route("**/api/calendar/import", refuse_import)
                import_requests = []
                page.on(
                    "request",
                    lambda request: (
                        import_requests.append(request.post_data_json)
                        if request.url == base + "/api/calendar/import" and request.method == "POST"
                        else None
                    ),
                )
                with page.expect_file_chooser() as chooser:
                    menu_item("#cal-import").press("Enter")
                chooser.value.set_files(
                    {
                        "name": "rejected.ics",
                        "mimeType": "text/calendar",
                        "buffer": ics.replace(" imported", " rejected").encode(),
                    }
                )
                expect(page.locator("#cal-import-status")).to_contain_text("rejected.ics")
                assert len(import_requests) == 1
                with page.expect_file_chooser() as chooser:
                    menu_item("#cal-import").press("Enter")
                chooser.value.set_files([])
                assert len(import_requests) == 1, (
                    "opening or emptying the replacement picker must not resend the failed file"
                )
                expect(page.locator("#cal-import-retry")).to_be_enabled()
                snapshot("import-replacement-available")
                page.unroute("**/api/calendar/import", refuse_import)
                replacement = ics.replace("synthetic-import", "replacement-import").replace(
                    " imported", " replacement"
                )
                with page.expect_file_chooser() as chooser:
                    page.locator("#cal-import-choose").press("Enter")
                with page.expect_response(
                    lambda response: response.url.endswith("/api/calendar/import")
                ) as replaced:
                    chooser.value.set_files(
                        {
                            "name": "replacement.ics",
                            "mimeType": "text/calendar",
                            "buffer": replacement.encode(),
                        }
                    )
                assert replaced.value.ok and replaced.value.json()["imported"] == 1
                expect(page.locator("#cal-import-feedback")).to_be_hidden()
                expect(page.locator("#cal-more-btn")).to_be_focused()
                assert len(import_requests) == 2 and import_requests[-1]["ics"] == replacement
                assert len(rows()) == len(before) + 2
                assert not any(event["title"] == label + " rejected" for event in rows())
                expect(page.locator("#cal-inv-email")).to_have_value("b-draft@example.invalid")

                def refuse_booking(route):
                    if route.request.method == "POST":
                        route.fulfill(status=503, json={"detail": "synthetic booking unavailable"})
                    else:
                        route.continue_()

                page.route("**/api/calendar", refuse_booking)
                menu_item("#cal-find").press("Enter")
                prompt("60")
                slot = page.locator(".cal-scope-ov [data-s]").first
                slot.click()
                prompt(label + " booked")
                error = page.locator(".cal-scope-ov [role=alert]")
                expect(error).to_contain_text("wasn't confirmed")
                expect(slot).to_be_enabled()
                assert len(rows()) == len(before) + 2
                snapshot("booking-refused")
                page.unroute("**/api/calendar", refuse_booking)
                slot.press("Enter")
                expect(page.get_by_role("dialog").locator("input")).to_have_value(label + " booked")
                page.get_by_role("dialog").locator("input").press("Enter")
                expect(page.locator(".cal-scope-ov")).to_have_count(0)
                expect(page.locator("#cal-inv-email")).to_have_value("b-draft@example.invalid")
                assert len(rows()) == len(before) + 3
                page.reload(wait_until="networkidle")
                assert any(event["title"] == label + " booked" for event in rows())
                assert any(event["title"] == label + " imported" for event in rows())
                assert any(event["title"] == label + " replacement" for event in rows())
                snapshot("persisted-after-reload")
                unexpected_console = [
                    item
                    for item in console
                    if not (
                        (
                            "503 (Service Unavailable)" in item["text"]
                            or "400 (Bad Request)" in item["text"]
                        )
                        and item["url"] in {base + "/api/calendar/import", base + "/api/calendar"}
                    )
                ]
                assert not errors and not external and not unexpected_console, (
                    errors,
                    external,
                    unexpected_console,
                )
                row.update(
                    status="passed",
                    checks="A-to-B invite ownership/focus; malformed file and malformed acknowledgment preserve file without writes; 503 import/file retention and explicit retry; both replacement-picker entry points; empty-picker retention; replacement file persists without resending rejected file; recovery focus/44px controls; 503 booking/title retention and retry; newer editor preserved; real local persistence after reload; keyboard; reduced motion",
                    writes=api_writes,
                )
                for event in rows():
                    assert api.delete(base + "/api/calendar/" + event["id"]).ok
            except Exception:
                row["error"] = traceback.format_exc()
                snapshot("failed")
            finally:
                for request in held:
                    request.abort()
                row.update(page_errors=errors, console=console, blocked_external=external)
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"{label}.zip"))
                context.close()
        browser.close()
    print(json.dumps(records, indent=2))
    assert all(row["status"] == "passed" for row in records)


if __name__ == "__main__":
    run()
