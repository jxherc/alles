"""Inbox local persistence, draft recovery, keyboard and narrow-screen regressions.

Runs only against an owned fixture. Provider access is deliberately unavailable;
only explicitly recorded failure responses and pending-write timing are simulated.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def seed_mail(request, base):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    response = request.post(
        base + "/api/mail/accounts",
        data={
            "name": "Inbox fixture",
            "email": "me@example.invalid",
            "imap_host": "127.0.0.1",
            "imap_port": closed_port,
            "smtp_host": "127.0.0.1",
            "smtp_port": closed_port,
            "username": "fixture",
            "password": "synthetic-only",
            "use_ssl": False,
        },
    )
    assert response.ok, response.text()
    account = response.json()
    # Ownership is checked before importing the database module or writing any fixture.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.database import CachedMessage, SessionLocal

    with SessionLocal() as db:
        for uid, sender, subject in [
            ("701", "Receipts <receipts@example.invalid>", "Receipt 中文 with a long subject"),
            ("702", "Teammate <teammate@example.invalid>", "Project notes"),
        ]:
            db.add(
                CachedMessage(
                    account_id=account["id"],
                    folder="INBOX",
                    uid=uid,
                    sender=sender,
                    subject=subject,
                    date="2026-09-25",
                    date_ts=time.time() - int(uid),
                    seen=True,
                    message_id=f"<inbox-fixture-{uid}@example.invalid>",
                    thread_id=f"inbox-fixture-{uid}",
                )
            )
        db.commit()
    return account


def retain_fixture_send_delay(base, identity, submitted_delay):
    """Keep synthetic sends safely in the future without changing their retry identity.

    Browser fixtures replace only the initial API delay with 3600 before forwarding
    it, then restore its original request metadata. Timing itself is covered by API
    tests; the browser checks exact retries, current outcomes and editor ownership.
    """
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
    from datetime import UTC, datetime, timedelta

    from core.database import ScheduledMail, SessionLocal

    with SessionLocal() as db:
        row = db.get(ScheduledMail, identity)
        assert row is not None and row.status == "scheduled"
        assert datetime.fromisoformat(row.send_at) > datetime.now(UTC).replace(
            tzinfo=None
        ) + timedelta(minutes=30)
        row.request_delay = submitted_delay
        db.commit()


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        request = p.request.new_context()
        account = seed_mail(request, base)
        (output / "fixture.json").write_text(
            json.dumps({"account": account, "provider": "closed loopback; no live integration"})
        )
        request.dispose()
        browser = p.chromium.launch()
        for device, theme in [
            ("desktop", "dark"),
            ("desktop", "light"),
            ("phone", "dark"),
            ("phone", "light"),
        ]:
            profile = f"{device}-{theme}"
            context = browser.new_context(
                viewport={"width": 1440 if device == "desktop" else 390, "height": 900},
                service_workers="block",
                is_mobile=device == "phone",
                has_touch=device == "phone",
                reduced_motion="reduce",
                locale="en-US",
                timezone_id="UTC",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            events = {
                "console": [],
                "page_errors": [],
                "failed_requests": [],
                "http_errors": [],
                "writes": [],
            }
            expected_http = []
            expected_network = []
            proof = []
            page.on(
                "console",
                lambda msg: events["console"].append({"type": msg.type, "text": msg.text}),
            )
            page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda req: events["failed_requests"].append(
                    {"url": req.url, "failure": req.failure}
                ),
            )

            def response_event(response):
                if response.status >= 400:
                    events["http_errors"].append({"url": response.url, "status": response.status})
                if "/api/" in response.url and response.request.method != "GET":
                    try:
                        body = response.text()
                    except Exception:
                        body = "response body unavailable"
                    events["writes"].append(
                        {
                            "url": response.url,
                            "method": response.request.method,
                            "status": response.status,
                            "body": body,
                        }
                    )

            page.on("response", response_event)
            current = None

            def begin(name):
                nonlocal current
                current = {
                    "scenario_id": name,
                    "feature_id": "inbox.mail-and-contacts",
                    "profile": profile,
                    "status": "failed",
                    "detail": "workflow did not finish",
                }
                records.append(current)

            def passed():
                current.update(
                    status="passed", detail="visible UI and real saved-result assertions"
                )

            def shot(name):
                page.screenshot(path=str(output / f"{profile}-{name}.png"), full_page=True)

            def contacts():
                response = context.request.get(base + "/api/contacts")
                assert response.ok
                return response.json()

            def drafts():
                response = context.request.get(base + "/api/mail/drafts")
                assert response.ok
                return response.json()

            def inbox(section, reload=False):
                if reload:
                    page.reload(wait_until="networkidle")
                else:
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name=section, exact=True).click()

            def simulation(endpoint, method, status=503, payload=None, abort=False):
                def handler(route):
                    if route.request.method != method:
                        route.continue_()
                        return
                    if abort:
                        expected_network.append(
                            {"url": route.request.url, "failure": "net::ERR_CONNECTION_FAILED"}
                        )
                        route.abort("connectionfailed")
                    else:
                        if status >= 400:
                            expected_http.append({"url": route.request.url, "status": status})
                        route.fulfill(
                            status=status, content_type="application/json", body=json.dumps(payload)
                        )

                page.route(endpoint, handler)
                return handler

            try:
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                page.locator("#today-settings").click()
                choose_settings_section(page, "themes")
                page.wait_for_function(
                    "theme => document.querySelector('[data-theme-mode=\"' + theme + '\"]')?.dataset.bound === '1'",
                    arg=theme,
                )
                with page.expect_response(
                    lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                ) as changed:
                    page.locator(f'[data-theme-mode="{theme}"]').click()
                assert changed.value.ok
                page.locator("#settings-modal-close").click()
                inbox("contacts")
                if theme == "light":
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                else:
                    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
                name = f"Inbox person 李明 with a long family name {profile}"
                email = f"{profile}@example.invalid"
                page.locator("#contact-name").fill(name)
                page.locator("#contact-email").fill(email)
                page.locator("#contact-phone").fill("+1 202 555 0144")

                begin("inbox.contact-create-recovery")
                for status, payload, abort in [
                    (503, {"detail": "simulated contact write outage"}, False),
                    (200, None, False),
                    (200, {}, False),
                    (200, None, True),
                ]:
                    handler = simulation(base + "/api/contacts", "POST", status, payload, abort)
                    page.get_by_role("button", name="add", exact=True).click()
                    expect(page.locator("#contact-add-error")).to_contain_text(
                        "could not add contact"
                    )
                    expect(page.locator("#contact-name")).to_have_value(name)
                    expect(page.locator("#contact-email")).to_have_value(email)
                    expect(page.locator("#contact-phone")).to_have_value("+1 202 555 0144")
                    expect(page.get_by_text("contact added", exact=True)).to_have_count(0)
                    assert not [c for c in contacts() if c["name"] == name]
                    page.unroute(base + "/api/contacts", handler)
                shot("contact-create-error")
                passed()

                begin("inbox.contact-single-submit-reload")
                held = []

                def hold(route):
                    if route.request.method == "POST":
                        held.append(route)
                    else:
                        route.continue_()

                page.route(base + "/api/contacts", hold)
                page.get_by_role("button", name="add", exact=True).dblclick(delay=50)
                expect(page.locator("#contact-add-btn")).to_be_disabled()
                expect(page.locator("#contact-name")).to_be_disabled()
                assert len(held) == 1, len(held)
                held[0].continue_()
                expect(page.locator("#contact-name")).to_have_value("")
                page.unroute(base + "/api/contacts", hold)
                saved = [c for c in contacts() if c["name"] == name]
                assert len(saved) == 1
                contact = saved[0]
                proof.append({"case": "contact created once", "saved": contact})
                inbox("contacts", reload=True)
                row = page.locator(f'.contact-item[data-id="{contact["id"]}"]')
                expect(row).to_contain_text(name)
                for control in row.locator("button").all():
                    assert control.evaluate(
                        "e => getComputedStyle(e.parentElement).opacity !== '0'"
                    )
                footer = page.locator(".contacts-create")
                for control in footer.locator("input,button").all():
                    rect = control.bounding_box()
                    assert (
                        rect
                        and rect["x"] >= 0
                        and rect["x"] + rect["width"] <= page.viewport_size["width"] + 1
                    ), rect
                    assert rect["height"] >= 44, rect
                shot("contacts-populated")
                passed()

                begin("inbox.contact-edit-recovery")
                row.get_by_role("button", name="open", exact=True).press("Enter")
                detail = page.locator(".contact-detail")
                expect(detail.get_by_label("name", exact=True)).to_have_value(name)
                detail.get_by_role("textbox", name="notes", exact=True).fill(
                    "Important saved notes 中文 " + profile
                )
                detail.get_by_label("company", exact=True).fill("Fixture Workshop")
                endpoint = base + "/api/contacts/" + contact["id"]
                for status, payload in [
                    (503, {"detail": "simulated update outage"}),
                    (200, None),
                    (200, {}),
                ]:
                    handler = simulation(endpoint, "PATCH", status, payload)
                    detail.get_by_role("button", name="save", exact=True).click()
                    expect(page.locator("#cd-error")).to_contain_text("could not save contact")
                    expect(detail.get_by_role("textbox", name="notes", exact=True)).to_have_value(
                        "Important saved notes 中文 " + profile
                    )
                    assert context.request.get(endpoint).json()["notes"] == ""
                    page.unroute(endpoint, handler)
                page.locator("#cd-error").scroll_into_view_if_needed()
                shot("contact-edit-error")
                detail.get_by_role("button", name="save", exact=True).press("Enter")
                expect(detail).to_have_count(0)
                inbox("contacts", reload=True)
                row.get_by_role("button", name="open", exact=True).click()
                expect(detail.get_by_role("textbox", name="notes", exact=True)).to_have_value(
                    "Important saved notes 中文 " + profile
                )
                proof.append(
                    {
                        "case": "contact retry persisted",
                        "saved": context.request.get(endpoint).json(),
                    }
                )
                passed()

                begin("inbox.contact-extra-field-preserves-draft")
                pending_note = "Unsaved scalar must survive adding an email 中文 " + profile
                detail.get_by_role("textbox", name="notes", exact=True).fill(pending_note)
                page.get_by_placeholder("label (home/work…)").fill("work")
                page.get_by_placeholder("value", exact=True).fill("extra@example.invalid")
                handler = simulation(
                    endpoint + "/fields", "POST", 503, {"detail": "simulated field outage"}
                )
                page.get_by_role("button", name="add field", exact=True).click()
                expect(page.locator("#cd-error")).to_contain_text("could not add field")
                expect(detail.get_by_role("textbox", name="notes", exact=True)).to_have_value(
                    pending_note
                )
                expect(page.get_by_placeholder("value", exact=True)).to_have_value(
                    "extra@example.invalid"
                )
                page.unroute(endpoint + "/fields", handler)
                page.get_by_role("button", name="add field", exact=True).click()
                expect(page.locator("#cd-fields")).to_contain_text("extra@example.invalid")
                expect(detail.get_by_role("textbox", name="notes", exact=True)).to_have_value(
                    pending_note
                )
                stored = context.request.get(endpoint).json()
                assert (
                    stored["notes"] != pending_note
                    and stored["fields"][0]["value"] == "extra@example.invalid"
                )
                detail.get_by_role("button", name="save", exact=True).click()
                expect(detail).to_have_count(0)
                inbox("contacts", reload=True)
                row.get_by_role("button", name="open", exact=True).click()
                expect(detail.get_by_role("textbox", name="notes", exact=True)).to_have_value(
                    pending_note
                )
                expect(page.locator("#cd-fields")).to_contain_text("extra@example.invalid")
                proof.append(
                    {
                        "case": "extra field plus scalar save/reload",
                        "saved": context.request.get(endpoint).json(),
                    }
                )
                held_list = []

                def hold_previous_list(route):
                    if route.request.method == "GET":
                        held_list.append(route)
                    else:
                        route.continue_()

                page.route(base + "/api/contacts", hold_previous_list)
                with page.expect_request(
                    lambda req: req.url == base + "/api/contacts" and req.method == "GET"
                ):
                    page.get_by_role("button", name="contacts", exact=True).click()
                assert len(held_list) == 1
                passed()

                begin("inbox.contact-list-error-retry")
                handler = simulation(
                    base + "/api/contacts?*", "GET", 503, {"detail": "simulated list outage"}
                )
                page.locator("#contacts-search").fill(profile)
                expect(page.get_by_role("alert")).to_contain_text("could not load contacts")
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/contacts" and response.status == 200
                    )
                ):
                    held_list.pop().fulfill(
                        status=200, content_type="application/json", body=json.dumps(contacts())
                    )
                page.evaluate(
                    "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                )
                expect(page.get_by_role("alert")).to_contain_text("could not load contacts")
                expect(page.get_by_text("no contacts", exact=True)).to_have_count(0)
                assert context.request.get(endpoint).ok
                shot("contact-list-error")
                page.unroute(base + "/api/contacts", hold_previous_list)
                page.unroute(base + "/api/contacts?*", handler)
                page.get_by_role("button", name="retry", exact=True).click()
                expect(row).to_be_visible()
                expect(page.locator("#contacts-search")).to_have_value(profile)
                page.locator("#contacts-search").fill("")
                passed()

                begin("inbox.contact-import-favorite-delete")
                import_name = "Imported contact 測試 " + profile
                vcard = f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{import_name}\r\nEMAIL:imported@example.invalid\r\nEND:VCARD\r\n"
                with page.expect_file_chooser() as chooser:
                    page.get_by_role("button", name="import", exact=True).click()
                chooser.value.set_files(
                    {"name": "fixture.vcf", "mimeType": "text/vcard", "buffer": vcard.encode()}
                )
                expect(page.get_by_text(import_name, exact=True)).to_be_visible()
                imported = next(c for c in contacts() if c["name"] == import_name)
                imported_row = page.locator(f'.contact-item[data-id="{imported["id"]}"]')
                imported_row.get_by_role("button", name="favorite", exact=True).press("Space")
                expect(imported_row.locator(".contact-star")).to_have_class("contact-star on")
                inbox("contacts", reload=True)
                expect(imported_row.locator(".contact-star")).to_have_class("contact-star on")
                imported_row.get_by_role("button", name="del", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(imported_row).to_be_visible()
                imported_row.get_by_role("button", name="del", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(imported_row).to_have_count(0)
                inbox("contacts", reload=True)
                assert not [c for c in contacts() if c["id"] == imported["id"]]
                passed()

                begin("inbox.mail-pointer-keyboard-layout")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(page.locator(".mail-row")).to_have_count(2)
                page.get_by_role("button", name="drafts", exact=True).focus()
                page.keyboard.press("Tab")
                expect(page.locator("#mail-read-retry")).to_be_focused()
                page.keyboard.press("Tab")
                opener = page.get_by_role(
                    "button", name="Receipt 中文 with a long subject", exact=True
                )
                expect(opener).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("#mail-main")).to_contain_text("Connection refused")
                page.get_by_role("button", name="add a label", exact=True).first.press("Tab")
                assert page.locator(":focus").evaluate("e => getComputedStyle(e).opacity === '1'")
                for sender in page.locator(".mail-from").all():
                    assert sender.evaluate("e => e.clientWidth >= e.scrollWidth"), (
                        sender.inner_text()
                    )
                for action in page.locator(".mail-act").all():
                    assert action.evaluate("e => getComputedStyle(e).opacity === '1'")
                shot("mail-populated")
                passed()

                begin("inbox.mail-draft-save-reload")
                page.get_by_role("button", name="compose", exact=True).click()
                page.get_by_placeholder("recipients…").fill("recipient@example.invalid")
                page.get_by_placeholder("recipients…").press("Enter")
                subject = "Inbox draft 中文 " + profile
                page.get_by_placeholder("subject", exact=True).fill(subject)
                page.get_by_role("textbox", name="message", exact=True).fill(
                    "Original local mail body 中文"
                )
                with page.expect_response(
                    lambda r: r.url.endswith("/api/mail/drafts") and r.request.method == "POST"
                ) as saved_response:
                    page.get_by_role("button", name="save draft", exact=True).click()
                assert saved_response.value.ok
                expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                draft = next(d for d in drafts() if d["subject"] == subject)
                page.get_by_role("button", name="close", exact=True).click()
                expect(page.get_by_role("alertdialog")).to_have_count(0)
                inbox("mail", reload=True)
                page.get_by_role("button", name="drafts", exact=True).click()
                expect(page.get_by_role("button", name=subject, exact=True)).to_be_visible()
                page.keyboard.press("Tab")
                expect(page.get_by_role("button", name=subject, exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.get_by_role("textbox", name="message", exact=True)).to_have_text(
                    "Original local mail body 中文"
                )
                proof.append({"case": "draft create/reload", "saved": draft})
                passed()

                begin("inbox.mail-body-dirty-guard-recovery")
                for failure in ["none", "http503", "network"]:
                    body = "Important unsaved body " + failure + " 中文"
                    page.get_by_role("textbox", name="message", exact=True).fill(body)
                    handler = None
                    if failure != "none":
                        handler = simulation(
                            base + "/api/mail/drafts",
                            "POST",
                            503,
                            {"detail": "simulated draft outage"},
                            failure == "network",
                        )
                        page.get_by_role("button", name="save draft", exact=True).click()
                        expect(
                            page.get_by_text("save unconfirmed", exact=True).last
                        ).to_be_visible()
                    page.get_by_role("button", name="close", exact=True).click()
                    expect(page.get_by_role("alertdialog")).to_contain_text(
                        "discard unsaved draft changes?"
                    )
                    page.get_by_role("alertdialog").get_by_role(
                        "button", name="cancel", exact=True
                    ).click()
                    expect(page.get_by_role("textbox", name="message", exact=True)).to_have_text(
                        body
                    )
                    assert (
                        context.request.get(base + "/api/mail/drafts/" + draft["id"]).json()["body"]
                        == "Original local mail body 中文"
                    )
                    if handler:
                        page.unroute(base + "/api/mail/drafts", handler)
                        page.locator("#mail-draft-dismiss").click()
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()
                        expect(
                            page.get_by_role("textbox", name="message", exact=True)
                        ).to_have_text(body)
                shot("mail-body-retained")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/mail/drafts") and r.request.method == "POST"
                ) as saved_response:
                    page.get_by_role("button", name="save draft", exact=True).click()
                assert saved_response.value.ok
                expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                inbox("mail", reload=True)
                page.get_by_role("button", name="drafts", exact=True).click()
                page.get_by_role("button", name=subject, exact=True).press("Enter")
                expect(page.get_by_role("textbox", name="message", exact=True)).to_have_text(body)
                proof.append(
                    {
                        "case": "draft failure retry persisted",
                        "saved": context.request.get(
                            base + "/api/mail/drafts/" + draft["id"]
                        ).json(),
                    }
                )
                page.get_by_role("textbox", name="message", exact=True).fill(
                    "Explicitly discarded change"
                )
                page.get_by_role("button", name="close", exact=True).click()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(page.get_by_role("textbox", name="message", exact=True)).to_have_count(0)
                passed()

                begin("inbox.mail-pending-save-keeps-new-edits")
                page.get_by_role("button", name=subject, exact=True).press("Enter")
                page.get_by_role("textbox", name="message", exact=True).fill(
                    "First body sent to storage"
                )
                pending_drafts = []

                def hold_draft(route):
                    if route.request.method == "POST":
                        pending_drafts.append(route)
                    else:
                        route.continue_()

                page.route(base + "/api/mail/drafts", hold_draft)
                page.get_by_role("button", name="save draft", exact=True).click()
                page.get_by_role("textbox", name="message", exact=True).fill(
                    "Newer body while save is pending"
                )
                assert len(pending_drafts) == 1
                with page.expect_response(
                    lambda r: r.url.endswith("/api/mail/drafts") and r.request.method == "POST"
                ):
                    pending_drafts[0].continue_()
                page.unroute(base + "/api/mail/drafts", hold_draft)
                page.get_by_role("button", name="close", exact=True).click()
                expect(page.get_by_role("alertdialog")).to_be_visible()
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(page.get_by_role("textbox", name="message", exact=True)).to_have_text(
                    "Newer body while save is pending"
                )
                assert (
                    context.request.get(base + "/api/mail/drafts/" + draft["id"]).json()["body"]
                    == "First body sent to storage"
                )
                with page.expect_response(
                    lambda r: r.url.endswith("/api/mail/drafts") and r.request.method == "POST"
                ):
                    page.get_by_role("button", name="save draft", exact=True).click()
                expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "false")
                expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                page.get_by_role("button", name="close", exact=True).click()
                expect(page.get_by_role("alertdialog")).to_have_count(0)
                inbox("mail", reload=True)
                page.get_by_role("button", name="drafts", exact=True).click()
                page.get_by_role("button", name=subject, exact=True).press("Enter")
                expect(page.get_by_role("textbox", name="message", exact=True)).to_have_text(
                    "Newer body while save is pending"
                )
                page.get_by_role("button", name="close", exact=True).click()
                passed()

                begin("inbox.mail-draft-list-retry-delete")
                page.get_by_role("button", name="inbox", exact=True).click()
                handler = simulation(
                    base + "/api/mail/drafts?*",
                    "GET",
                    503,
                    {"detail": "simulated draft list outage"},
                )
                page.get_by_role("button", name="drafts", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("could not load drafts")
                expect(page.get_by_text("no drafts", exact=True)).to_have_count(0)
                shot("mail-list-error")
                page.unroute(base + "/api/mail/drafts?*", handler)
                page.get_by_role("button", name="retry", exact=True).press("Enter")
                expect(page.get_by_role("button", name=subject, exact=True)).to_be_visible()
                page.get_by_role("button", name="delete draft", exact=True).click()
                expect(page.get_by_text("no drafts", exact=True)).to_be_visible()
                inbox("mail", reload=True)
                page.get_by_role("button", name="drafts", exact=True).click()
                expect(page.get_by_text("no drafts", exact=True)).to_be_visible()
                assert not [d for d in drafts() if d["id"] == draft["id"]]
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                passed()

                assert not events["page_errors"], events["page_errors"]
                assert events["http_errors"] == expected_http, events["http_errors"]
                assert events["failed_requests"] == expected_network, events["failed_requests"]
                errors = [e["text"] for e in events["console"] if e["type"] == "error"]
                assert len(errors) == len(expected_http) + len(expected_network), errors
                assert all(
                    "Failed to load resource" in text
                    and ("503" in text or "net::ERR_CONNECTION_FAILED" in text)
                    for text in errors
                ), errors
            except Exception:
                shot("failure")
                raise
            finally:
                events["simulated_http"] = expected_http
                events["simulated_network"] = expected_network
                (output / f"{profile}-events.json").write_text(json.dumps(events, indent=2))
                (output / f"{profile}-persistence.json").write_text(json.dumps(proof, indent=2))
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"{profile}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenario_count": len(records)}))


if __name__ == "__main__":
    run()
