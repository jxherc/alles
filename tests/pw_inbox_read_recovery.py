"""Owned Inbox reads; cached records are real and message-provider replies are controlled."""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    cases = [
        "search-retry",
        "search-order",
        "message-retry-and-draft",
        "message-order",
        "filter-failure",
        "cached-inbox-recovery",
        "inbox-to-search-order",
        "accounts-failure",
        "empty-inbox",
        "sent-folder-failure",
        "retry-preserves-moved-focus",
        "partial-account-search",
        "filtered-retry-keeps-reply",
        "inbox-retry-focus",
        "sent-retry-focus",
        "inbox-retry-moved-focus",
        "accounts-preserve-newer-draft",
    ]
    if len(sys.argv) > 1:
        cases = [case for case in cases if case in sys.argv[1:]]
    assert cases
    with sync_playwright() as pw:
        api = pw.request.new_context(base_url=base)
        account = seed_mail(api, base)
        assert api.post("/api/setup/dismiss").ok
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in cases:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.set_default_timeout(7000)
                errors, console, seen = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda item: console.append(item.text) if item.type == "error" else None,
                )
                page.on(
                    "request",
                    lambda request: (
                        seen.append(request.url) if "/api/mail/seen/" in request.url else None
                    ),
                )
                secondary = None
                result = {
                    "scenario_id": "inbox.read." + case,
                    "profile": str(width),
                    "status": "failed",
                }
                records.append(result)

                def fail(route):
                    route.fulfill(status=503, json={"detail": "synthetic unavailable"})

                def message(uid):
                    return {
                        "uid": uid,
                        "from": "Teammate <teammate@example.invalid>",
                        "to": "me@example.invalid",
                        "subject": "owned message " + uid,
                        "date": "2026-09-25",
                        "text": "owned body " + uid,
                        "html": "",
                        "message_id": f"<owned-{uid}@example.invalid>",
                        "references": "",
                    }

                def wait_held(held):
                    deadline = time.monotonic() + 5
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "expected one held read"

                try:
                    if case == "accounts-failure":
                        page.route(base + "/api/mail/accounts", fail)
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    field = page.locator("#mail-search")
                    mailbox = page.locator("#mail-list")
                    main = page.locator("#mail-main")

                    def search(query):
                        field.fill(query)
                        field.press("Enter")

                    def row(uid):
                        return mailbox.locator(
                            f'.mail-row[data-aid="{account["id"]}"][data-uid="{uid}"] .mail-open'
                        )

                    search_url = base + f"/api/mail/adv-search/{account['id']}?*"
                    inbox_url = base + f"/api/mail/inbox/{account['id']}?*"
                    message_url = base + f"/api/mail/message/{account['id']}?*"
                    if case == "accounts-failure":
                        expect(page.locator(".specialist-state:visible")).to_have_attribute(
                            "data-state", "error"
                        )
                        expect(page.locator(".mail-accounts:visible")).to_have_count(0)
                        page.unroute(base + "/api/mail/accounts", fail)
                        page.locator(".specialist-state:visible").get_by_role(
                            "button", name="retry", exact=True
                        ).click()
                        search("Project")
                        expect(row("702")).to_be_visible()
                    else:
                        search("Project")
                        expect(row("702")).to_be_visible()
                        if case == "search-retry":
                            page.route(search_url, fail)
                            search("Receipt")
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            expect(mailbox).not_to_contain_text("no mail matches")
                            retry = page.locator("#mail-read-retry")
                            retry.focus()
                            page.keyboard.press("Enter")
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            expect(retry).to_be_focused()
                            page.screenshot(
                                path=str(out / f"{width}-search-error.png"), full_page=True
                            )
                            expect(field).to_have_value("Receipt")
                            page.unroute(search_url, fail)
                            retry.click()
                            expect(row("701")).to_be_visible()
                            expect(row("701")).to_be_focused()
                        elif case == "search-order":
                            held = []

                            def hold_search(route):
                                if parse_qs(urlparse(route.request.url).query).get("q") == [
                                    "Receipt"
                                ]:
                                    response = route.fetch()
                                    held.append((route, response))
                                else:
                                    route.continue_()

                            page.route(search_url, hold_search)
                            search("Receipt")
                            wait_held(held)
                            search("Project")
                            expect(row("702")).to_be_visible()
                            route, response = held.pop()
                            route.fulfill(response=response)
                            page.unroute(search_url, hold_search)
                            page.wait_for_load_state("networkidle")
                            expect(row("702")).to_be_visible()
                            expect(row("701")).to_have_count(0)
                            expect(field).to_have_value("Project")
                        elif case == "message-retry-and-draft":
                            page.route(message_url, fail)
                            row("702").click()
                            expect(main.get_by_role("alert")).to_contain_text(
                                "could not load message"
                            )
                            expect(main.locator(".mail-reader")).to_have_count(0)
                            assert not seen, seen
                            retry = page.locator("#mail-message-retry")
                            retry.focus()
                            page.keyboard.press("Enter")
                            expect(main.get_by_role("alert")).to_contain_text(
                                "could not load message"
                            )
                            expect(retry).to_be_focused()
                            page.screenshot(
                                path=str(out / f"{width}-message-error.png"), full_page=True
                            )
                            page.unroute(message_url, fail)
                            page.route(
                                message_url, lambda route: route.fulfill(json=message("702"))
                            )
                            retry.click()
                            expect(main.locator(".mail-reader-subject")).to_have_text(
                                "owned message 702"
                            )
                            expect(main.locator(".mail-reader-subject")).to_be_focused()
                            page.locator("#mail-reply").click()
                            expect(page.locator("#mc-subj")).to_have_value("Re: owned message 702")
                            expect(page.locator("#mc-html")).to_contain_text("owned body 702")
                            page.locator("#mc-html").fill(f"retained reply {width}")
                            page.locator("#mail-refresh-btn").click()
                            page.wait_for_load_state("networkidle")
                            expect(page.locator("#mc-html")).to_have_text(f"retained reply {width}")
                            with page.expect_response(
                                lambda r: (
                                    r.url.endswith("/api/mail/drafts")
                                    and r.request.method == "POST"
                                )
                            ) as response:
                                page.get_by_role("button", name="save draft", exact=True).click()
                            assert response.value.ok
                            draft = response.value.json()
                            stored = api.get("/api/mail/drafts/" + draft["id"]).json()
                            assert stored["body"] == f"retained reply {width}"
                            assert stored["in_reply_to"] == "<owned-702@example.invalid>"
                            page.reload(wait_until="networkidle")
                            page.get_by_role("button", name="drafts", exact=True).click()
                            page.locator(
                                f'.mail-draft-row[data-id="{draft["id"]}"] .mail-open'
                            ).click()
                            expect(page.locator("#mc-html")).to_have_text(f"retained reply {width}")
                        elif case == "message-order":
                            search("")
                            expect(row("701")).to_be_visible()
                            held = []

                            def delayed_message(route):
                                uid = parse_qs(urlparse(route.request.url).query)["uid"][0]
                                if uid == "701":
                                    held.append(route)
                                else:
                                    route.fulfill(json=message(uid))

                            page.route(message_url, delayed_message)
                            row("701").click()
                            wait_held(held)
                            row("702").click()
                            expect(main.locator(".mail-reader-subject")).to_have_text(
                                "owned message 702"
                            )
                            held.pop().fulfill(json=message("701"))
                            page.wait_for_load_state("networkidle")
                            expect(main.locator(".mail-reader-subject")).to_have_text(
                                "owned message 702"
                            )
                            assert all("uid=702" in url for url in seen), seen
                        elif case == "filter-failure":
                            for choice, endpoint in [("primary", "category"), ("flagged", "smart")]:
                                url = base + f"/api/mail/{endpoint}/{account['id']}?*"
                                page.route(url, fail)
                                page.get_by_role("button", name=choice, exact=True).click()
                                expect(mailbox.get_by_role("alert")).to_contain_text(
                                    "synthetic unavailable"
                                )
                                expect(field).to_have_value("")
                                page.unroute(url, fail)
                                page.locator("#mail-read-retry").click()
                                expect(mailbox.get_by_role("alert")).to_have_count(0)
                                expect(mailbox).not_to_contain_text("loading")
                        elif case in {"cached-inbox-recovery", "empty-inbox"}:
                            page.get_by_role("button", name="inbox", exact=True).click()
                            expect(row("701")).to_be_visible()
                            if case == "cached-inbox-recovery":
                                expect(mailbox.get_by_role("alert")).to_contain_text("saved mail")
                                page.route(inbox_url, fail)
                                page.locator("#mail-refresh-btn").click()
                                expect(mailbox.get_by_role("alert")).to_contain_text(
                                    "synthetic unavailable"
                                )
                                expect(row("701")).to_be_visible()
                                page.unroute(inbox_url, fail)
                            page.route(
                                inbox_url, lambda route: route.fulfill(json={"messages": []})
                            )
                            page.locator(
                                "#mail-read-retry"
                                if case == "cached-inbox-recovery"
                                else "#mail-refresh-btn"
                            ).click()
                            expect(mailbox.locator(".mail-row")).to_have_count(0)
                            expect(mailbox).to_contain_text("nothing in inbox")
                            page.reload(wait_until="networkidle")
                            expect(mailbox.locator(".mail-row")).to_have_count(0)
                        elif case == "sent-folder-failure":
                            folders_url = base + f"/api/mail/folders/{account['id']}"
                            requests = []
                            page.on(
                                "request",
                                lambda request: (
                                    requests.append(request.url)
                                    if "/api/mail/inbox/" in request.url
                                    else None
                                ),
                            )
                            page.route(folders_url, fail)
                            page.get_by_role("button", name="sent", exact=True).click()
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            assert not requests, requests
                            page.unroute(folders_url, fail)
                            page.route(
                                folders_url,
                                lambda route: route.fulfill(json={"folders": ["INBOX", "Sent"]}),
                            )
                            page.route(
                                inbox_url, lambda route: route.fulfill(json={"messages": []})
                            )
                            page.locator("#mail-read-retry").click()
                            expect(mailbox).to_contain_text("nothing in sent")
                            expect(mailbox.get_by_role("alert")).to_have_count(0)
                        elif case == "retry-preserves-moved-focus":
                            page.route(message_url, fail)
                            row("702").click()
                            expect(main.get_by_role("alert")).to_contain_text(
                                "could not load message"
                            )
                            page.unroute(message_url, fail)
                            held = []
                            page.route(message_url, lambda route: held.append(route))
                            page.locator("#mail-message-retry").click()
                            wait_held(held)
                            field.focus()
                            held.pop().fulfill(json=message("702"))
                            expect(main.locator(".mail-reader-subject")).to_have_text(
                                "owned message 702"
                            )
                            expect(field).to_be_focused()
                        elif case == "partial-account-search":
                            secondary = seed_mail(api, base)
                            page.reload(wait_until="networkidle")
                            search("Receipt")
                            expect(mailbox.locator('.mail-row[data-uid="701"]')).to_have_count(2)
                            page.route(search_url, fail)
                            page.locator("#mail-refresh-btn").click()
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            expect(mailbox.locator('.mail-row[data-uid="701"]')).to_have_count(2)
                            page.screenshot(
                                path=str(out / f"{width}-partial-search.png"), full_page=True
                            )
                            page.unroute(search_url, fail)
                            page.route(
                                search_url, lambda route: route.fulfill(json={"messages": []})
                            )
                            page.locator("#mail-read-retry").click()
                            expect(row("701")).to_have_count(0)
                            expect(mailbox.locator('.mail-row[data-uid="701"]')).to_have_count(1)
                            expect(mailbox.get_by_role("alert")).to_have_count(0)
                        elif case == "accounts-preserve-newer-draft":
                            subject = f"owned delayed accounts {width}"
                            saved = api.post(
                                "/api/mail/drafts",
                                data={
                                    "account_id": account["id"],
                                    "subject": subject,
                                    "body": "saved draft",
                                },
                            )
                            assert saved.ok
                            held = []

                            def hold_accounts(route):
                                response = route.fetch()
                                held.append((route, response))

                            page.get_by_role("tab", name="contacts", exact=True).click()
                            page.route(base + "/api/mail/accounts", hold_accounts)
                            page.get_by_role("tab", name="mail", exact=True).click()
                            wait_held(held)
                            page.get_by_role("button", name="drafts", exact=True).click()
                            mailbox.get_by_role("button", name=subject, exact=True).click()
                            body = page.get_by_role("textbox", name="message", exact=True)
                            body.fill("unsaved newer draft")
                            route, response = held.pop()
                            route.fulfill(response=response)
                            page.wait_for_load_state("networkidle")
                            expect(body).to_have_text("unsaved newer draft")
                            assert (
                                api.get("/api/mail/drafts/" + saved.json()["id"]).json()["body"]
                                == "saved draft"
                            )
                            drafts_url = base + "/api/mail/drafts?*"
                            page.route(drafts_url, fail)
                            page.locator("#mail-refresh-btn").click()
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "could not load drafts"
                            )
                            expect(body).to_have_text("unsaved newer draft")
                            page.locator("#mail-drafts-retry").click()
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "could not load drafts"
                            )
                            expect(body).to_have_text("unsaved newer draft")
                            page.unroute(drafts_url, fail)
                            page.locator("#mail-drafts-retry").click()
                            expect(mailbox.get_by_role("alert")).to_have_count(0)
                            expect(body).to_have_text("unsaved newer draft")
                        elif case == "filtered-retry-keeps-reply":
                            cached = api.get(
                                f"/api/mail/adv-search/{account['id']}?q=Project"
                            ).json()["messages"]
                            for cached_message in cached:
                                cached_message["labels"] = ["owned"]
                            page.route(
                                message_url, lambda route: route.fulfill(json=message("702"))
                            )
                            previous_reply = None
                            for choice, endpoint in [
                                ("primary", "category"),
                                ("flagged", "smart"),
                                ("owned", "by-label"),
                            ]:
                                url = base + f"/api/mail/{endpoint}/{account['id']}?*"
                                page.route(
                                    url, lambda route: route.fulfill(json={"messages": cached})
                                )
                                if choice == "owned":
                                    mailbox.locator('[data-labelfilter="owned"]').first.click()
                                else:
                                    page.get_by_role("button", name=choice, exact=True).click()
                                expect(row("702")).to_be_visible()
                                page.route(url, fail)
                                page.locator("#mail-refresh-btn").click()
                                expect(mailbox.get_by_role("alert")).to_contain_text(
                                    "synthetic unavailable"
                                )
                                if previous_reply is not None:
                                    expect(page.locator("#mc-html")).to_have_text(previous_reply)
                                row("702").click()
                                if previous_reply is not None:
                                    dialog = page.get_by_role("alertdialog")
                                    expect(dialog).to_be_visible()
                                    expect(page.locator("#mc-html")).to_have_text(previous_reply)
                                    dialog.get_by_role("button", name="confirm", exact=True).click()
                                expect(main.locator(".mail-reader-subject")).to_have_text(
                                    "owned message 702"
                                )
                                page.locator("#mail-reply").click()
                                page.locator("#mc-html").fill(f"unsaved {choice} reply {width}")
                                page.locator("#mail-read-retry").click()
                                expect(mailbox.get_by_role("alert")).to_contain_text(
                                    "synthetic unavailable"
                                )
                                expect(page.locator("#mc-html")).to_have_text(
                                    f"unsaved {choice} reply {width}"
                                )
                                page.unroute(url, fail)
                                page.locator("#mail-read-retry").click()
                                expect(mailbox.get_by_role("alert")).to_have_count(0)
                                expect(page.locator("#mc-html")).to_have_text(
                                    f"unsaved {choice} reply {width}"
                                )
                                previous_reply = f"unsaved {choice} reply {width}"
                        elif case in {
                            "inbox-retry-focus",
                            "sent-retry-focus",
                            "inbox-retry-moved-focus",
                        }:
                            folder = "sent" if case == "sent-retry-focus" else "inbox"
                            if folder == "sent":
                                page.route(
                                    base + f"/api/mail/folders/{account['id']}",
                                    lambda route: route.fulfill(
                                        json={"folders": ["INBOX", "Sent"]}
                                    ),
                                )
                            page.route(inbox_url, fail)
                            page.get_by_role("button", name=folder, exact=True).click()
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            retry = page.locator("#mail-read-retry")
                            retry.focus()
                            page.keyboard.press("Enter")
                            expect(mailbox.get_by_role("alert")).to_contain_text(
                                "synthetic unavailable"
                            )
                            expect(retry).to_be_focused()
                            page.unroute(inbox_url, fail)
                            if case == "inbox-retry-moved-focus":
                                held = []
                                page.route(inbox_url, lambda route: held.append(route))
                                retry.click()
                                wait_held(held)
                                field.focus()
                                held.pop().fulfill(json={"messages": []})
                                expect(mailbox).to_contain_text("nothing in inbox")
                                expect(field).to_be_focused()
                            else:
                                page.route(
                                    inbox_url, lambda route: route.fulfill(json={"messages": []})
                                )
                                retry.click()
                                expect(mailbox).to_contain_text("nothing in " + folder)
                                expect(mailbox.get_by_role("status")).to_be_focused()
                        elif case == "inbox-to-search-order":
                            page.get_by_role("button", name="inbox", exact=True).click()
                            expect(row("701")).to_be_visible()
                            held = []

                            def hold_inbox(route):
                                response = route.fetch()
                                held.append((route, response))

                            page.route(inbox_url, hold_inbox)
                            page.locator("#mail-refresh-btn").click()
                            wait_held(held)
                            search("Receipt")
                            expect(row("701")).to_be_visible()
                            expect(row("702")).to_have_count(0)
                            route, response = held.pop()
                            route.fulfill(response=response)
                            page.unroute(inbox_url, hold_inbox)
                            page.wait_for_load_state("networkidle")
                            expect(row("702")).to_have_count(0)
                            expect(field).to_have_value("Receipt")
                    assert not errors, errors
                    assert all("503" in value for value in console), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    result["status"] = "passed"
                except Exception as error:
                    result.update(error=str(error), page_errors=errors, console=console, seen=seen)
                finally:
                    page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                    context.close()
                    if secondary:
                        assert api.delete("/api/mail/accounts/" + secondary["id"]).ok
                    (out / "scenarios.json").write_text(json.dumps(records, indent=2))
        browser.close()
        api.dispose()
    raise SystemExit(any(result["status"] != "passed" for result in records))


if __name__ == "__main__":
    run()
