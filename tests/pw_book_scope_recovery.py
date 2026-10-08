"""Synthetic storage/key scopes around real local book creation receipts."""

import json
import os
import traceback
import uuid
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 820, 390):
            for mode in ("confirm", "discard", "corrupt-first", "focused-draft", "retired-scope"):
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
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                endpoint = base + "/api/books"
                scope = api.get(endpoint + "/overview").json()["recovery_scopes"][0]
                other = "f" * 64
                entries = []
                for number, accepted_scope in enumerate((scope, other)):
                    pending = {
                        "payload": {
                            "title": f"Local scoped book {width} {mode} {number}",
                            "author": "Local writer",
                            "cover": "",
                            "isbn": "",
                            "year": 2020,
                            "status": "want",
                        },
                        "request_id": str(uuid.uuid4()),
                        "recovery_scope": accepted_scope,
                    }
                    response = api.post(
                        endpoint, data=pending["payload"] | {"request_id": pending["request_id"]}
                    )
                    assert response.ok
                    entries.append(pending)
                a, b = entries
                book_id = response.json()["id"]
                page = context.new_page()
                page.set_default_timeout(4000)
                accepted, posts, errors, console, held = [scope, other], [], [], [], []
                hold = [False]
                scope_rejections = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
                page.on(
                    "request",
                    lambda r: (
                        posts.append(r.post_data_json)
                        if r.method == "POST" and r.url == endpoint
                        else None
                    ),
                )

                def overview(route):
                    response = route.fetch()
                    payload = response.json()
                    payload["recovery_scopes"] = list(accepted)
                    if hold[0]:
                        held.append((route, response, payload))
                    else:
                        route.fulfill(response=response, json=payload)

                page.route(endpoint + "/overview", overview)
                page.route(
                    endpoint + "/requests/*",
                    lambda r: r.fulfill(response=api.get(r.request.url.split("?")[0])),
                )
                context.tracing.start(screenshots=True, snapshots=True)

                def storage():
                    return page.evaluate(
                        "() => Object.keys(sessionStorage).filter(k=>k.startsWith('alles.books.pending.v1:')).map(k=>sessionStorage.getItem(k))"
                    )

                def refresh():
                    radio = page.locator(f'.book-card[data-id="{book_id}"] [data-rate="4"]')
                    with page.expect_response(
                        lambda response: (
                            response.url == endpoint + "/" + book_id
                            and response.request.method == "PATCH"
                        )
                    ) as write:
                        radio.click()
                    if write.value.status == 409:
                        assert write.value.json() == {
                            "detail": "book storage changed; reopen books"
                        }
                        assert write.value.request.post_data_json["recovery_scope"] == other
                        scope_rejections.append(write.value.status)
                    else:
                        assert write.value.ok, write.value.text()
                    if not hold[0]:
                        expect(radio).to_be_enabled()

                try:
                    if mode == "focused-draft":
                        accepted[:] = [other]
                    page.goto(base + "/?view=books", wait_until="networkidle")
                    page.evaluate(
                        "entries => {for(const v of entries)sessionStorage.setItem('alles.books.pending.v1:'+v.recovery_scope,JSON.stringify(v));}",
                        [a] if mode in ("focused-draft", "retired-scope") else entries,
                    )
                    if mode == "corrupt-first":
                        page.evaluate(
                            "s=>sessionStorage.setItem('alles.books.pending.v1:'+s,'{bad')", scope
                        )
                    page.reload(wait_until="networkidle")
                    field = page.locator("#book-title")
                    if mode == "focused-draft":
                        page.locator("#books-add-toggle").click()
                        field.fill("New unsaved book")
                        page.locator("#book-author").fill("New author")
                        accepted[:] = [other, scope]
                        hold[0] = True
                        refresh()
                        field.focus()
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        route, response, payload = held[0]
                        route.fulfill(response=response, json=payload)
                        hold[0] = False
                        expect(field).to_have_value(a["payload"]["title"])
                        expect(field).to_be_disabled()
                        page.locator("#book-create-check").click()
                        expect(page.locator("#book-create-check")).to_have_count(0)
                        page.locator("#books-add-toggle").click()
                        expect(field).to_have_value("New unsaved book")
                        expect(page.locator("#book-author")).to_have_value("New author")
                    elif mode == "retired-scope":
                        expect(field).to_have_value(a["payload"]["title"])
                        accepted[:] = [other]
                        refresh()
                        expect(field).to_be_enabled()
                        expect(field).to_have_value("")
                        assert len(storage()) == 1
                        field.fill("Replacement draft")
                        accepted[:] = [other, scope]
                        refresh()
                        expect(field).to_have_value(a["payload"]["title"])
                        page.locator("#book-create-check").click()
                        expect(page.locator("#book-create-check")).to_have_count(0)
                        page.locator("#books-add-toggle").click()
                        expect(field).to_have_value("Replacement draft")
                    else:
                        if mode == "corrupt-first":
                            expect(page.locator("#book-create-error")).to_contain_text(
                                "could not read"
                            )
                        else:
                            expect(field).to_have_value(a["payload"]["title"])
                        if mode == "confirm":
                            page.locator("#book-create-check").click()
                        else:
                            page.locator("#book-create-discard").click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                        expect(field).to_have_value(b["payload"]["title"])
                        expect(field).to_be_disabled()
                        assert len(storage()) == 1
                        page.locator("#book-create-check").click()
                        expect(page.locator("#book-create-check")).to_have_count(0)
                    assert not storage() and not posts and not errors, (posts, errors)
                    assert len(scope_rejections) == (
                        1 if mode in ("focused-draft", "retired-scope") else 0
                    )
                    assert len(console) == len(scope_rejections) and all(
                        "409" in message for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    rows.append(
                        {
                            "scenario_id": "library.book-scopes." + mode,
                            "profile": str(width),
                            "status": "passed",
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "library.book-scopes." + mode,
                            "profile": str(width),
                            "status": "failed",
                            "error": str(error),
                            "traceback": traceback.format_exc(),
                        }
                    )
                finally:
                    page.screenshot(path=str(out / f"{width}-{mode}.png"))
                    context.tracing.stop(path=str(out / f"{width}-{mode}.zip"))
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(r["status"] == "passed" for r in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
