"""Owned mail regressions, real local mutations and synthetic message bodies only."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_inbox_workflows import seed_mail

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
results = []
with sync_playwright() as pw:
    api = pw.request.new_context(base_url=base)
    account = seed_mail(api, base)
    aid = account["id"]
    assert api.post("/api/setup/dismiss").ok
    from core.database import CachedMessage, SessionLocal

    browser = pw.chromium.launch()
    for width in [1440, 390]:
        for case in [
            "reader-return",
            "search-after-unread",
            "delete-updated-draft",
            "delete-after-close",
            "delete-external-change",
        ]:
            with SessionLocal() as db:
                for r in db.query(CachedMessage).filter_by(account_id=aid):
                    r.seen = False
                    r.flagged = False
                db.commit()
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            context.route(
                "**/*",
                lambda r: (
                    r.continue_()
                    if urlparse(r.request.url).netloc == urlparse(base).netloc
                    else r.abort()
                ),
            )
            page = context.new_page()
            page.set_default_timeout(5000)
            errors = []
            console = []
            writes = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.on(
                "response",
                lambda r: (
                    writes.append({"url": r.url, "status": r.status})
                    if r.request.method in ["POST", "DELETE"]
                    else None
                ),
            )

            def message(route):
                uid = parse_qs(urlparse(route.request.url).query)["uid"][0]
                route.fulfill(
                    json={
                        "uid": uid,
                        "from": "teammate@example.invalid",
                        "to": "me@example.invalid",
                        "subject": "owned message " + uid,
                        "date": "2026-10-03",
                        "text": "synthetic body",
                        "html": "",
                    }
                )

            page.route(base + "/api/mail/message/*", message)
            result = {
                "scenario_id": "inbox.review." + case,
                "profile": str(width),
                "status": "failed",
            }
            results.append(result)

            def row(uid="702"):
                return page.locator(f'.mail-row[data-aid="{aid}"][data-uid="{uid}"]')

            try:
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                expect(row()).to_be_visible()
                if case.startswith("delete-"):
                    draft = api.post(
                        "/api/mail/drafts",
                        data={"account_id": aid, "subject": "owned draft", "body": "original body"},
                    ).json()
                    endpoint = "/api/mail/drafts/" + draft["id"]
                    page.get_by_role("button", name="drafts", exact=True).click()
                    drow = page.locator(f'.mail-draft-row[data-id="{draft["id"]}"]')
                    drow.locator(".mail-open").click()
                    page.locator("#mc-html").fill("updated body")
                    page.locator("#mc-save").click()
                    expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                    expect(page.locator("#mc-save")).to_have_attribute("aria-disabled", "false")
                    updated = api.get(endpoint).json()
                    assert (
                        updated["body"] == "updated body"
                        and updated["revision"] != draft["revision"]
                    )
                    if case == "delete-after-close":
                        page.locator("#mc-close").click()
                        expect(page.locator("#mc-html")).to_have_count(0)
                    if case == "delete-external-change":
                        external = api.post(
                            "/api/mail/drafts",
                            data={
                                "id": draft["id"],
                                "account_id": aid,
                                "subject": "owned draft",
                                "body": "saved elsewhere",
                                "expected_revision": updated["revision"],
                            },
                        )
                        assert external.ok, external.text()
                    with page.expect_response(
                        lambda r: r.request.method == "DELETE" and "/api/mail/drafts/" in r.url
                    ) as deletion:
                        drow.locator(".mail-draft-del").click()
                    result["delete_status"] = deletion.value.status
                    result["stored_after_delete"] = api.get(endpoint).status
                    if case == "delete-external-change":
                        assert (
                            result["delete_status"] == 409 and result["stored_after_delete"] == 200
                        ), result
                        assert api.get(endpoint).json()["body"] == "saved elsewhere"
                        expect(page.locator("#mc-html")).to_have_text("updated body")
                    else:
                        assert (
                            result["delete_status"] == 200 and result["stored_after_delete"] == 404
                        ), result
                else:
                    if case == "search-after-unread":
                        page.locator('.mail-nav-item[data-filter="unread"]').click()
                        expect(row()).to_be_visible()
                        page.locator("#mail-search").fill("Project")
                        page.locator("#mail-search").press("Enter")
                        expect(row()).to_be_visible()
                        expect(row("701")).to_have_count(0)
                    row().locator(".mail-open").click()
                    expect(page.locator(".mail-reader-subject")).to_have_text("owned message 702")
                    expect(page.locator("#mail-unread")).to_have_attribute("aria-disabled", "false")
                    if case == "reader-return":
                        page.get_by_role("tab", name="overview", exact=True).click()
                        page.get_by_role("tab", name="mail", exact=True).click()
                        expect(page.locator(".mail-reader-subject")).to_have_text(
                            "owned message 702"
                        )
                        page.locator("#mail-unread").focus()
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(200)
                        with SessionLocal() as db:
                            result["seen_after_unread"] = (
                                db.query(CachedMessage)
                                .filter_by(account_id=aid, uid="702")
                                .one()
                                .seen
                            )
                        assert result["seen_after_unread"] is False, result
                    else:
                        result["rows_after_read"] = row().count()
                        assert result["rows_after_read"] == 1, result
                assert not errors, errors
                assert not [
                    m for m in console if not (case == "delete-external-change" and "409" in m)
                ], console
                result["status"] = "passed"
            except Exception as e:
                result.update(error=str(e), traceback=traceback.format_exc())
            finally:
                result.update(page_errors=errors, console=console, writes=writes)
                page.screenshot(path=str(out / f"{width}-{case}.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(results, indent=2))
    browser.close()
    api.dispose()
raise SystemExit(any(x["status"] != "passed" for x in results))
