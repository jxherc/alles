"""Synthetic accepted scopes with real local URL receipts; no external requests."""

import json
import os
import re
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
            for mode in ("confirm", "discard", "focused-draft", "corrupt-first"):
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if urlparse(route.request.url).netloc == urlparse(base).netloc
                        else route.abort()
                    ),
                )
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                endpoint = base + "/api/read"
                scope = api.get(endpoint).json()["recovery_scopes"][0]
                other = "f" * 64
                a = {
                    "url": base + f"/scope-a-{width}-{mode}",
                    "request_id": str(uuid.uuid4()),
                    "recovery_scope": scope,
                }
                b = {
                    "url": base + f"/scope-b-{width}-{mode}",
                    "request_id": str(uuid.uuid4()),
                    "recovery_scope": other,
                }
                for pending in (a, b):
                    response = api.post(
                        endpoint, data={k: v for k, v in pending.items() if k != "recovery_scope"}
                    )
                    assert response.ok
                page = context.new_page()
                page.set_default_timeout(3000)
                posts = []
                errors = []
                console = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        posts.append(request.post_data_json)
                        if request.method == "POST" and request.url == endpoint
                        else None
                    ),
                )
                accepted = [scope, other]
                held = []
                hold = [False]

                def listed(route):
                    response = route.fetch()
                    assert response.ok
                    payload = response.json()
                    payload["recovery_scopes"] = list(accepted)
                    if hold[0]:
                        held.append((route, response, payload))
                    else:
                        route.fulfill(response=response, json=payload)

                page.route(re.compile(re.escape(endpoint) + r"(?:\?.*)?$"), listed)

                def recover(route):
                    # Simulate the accepted retained key; receipt lookup itself is real.
                    response = api.get(route.request.url.split("?")[0])
                    route.fulfill(response=response)

                page.route(endpoint + "/requests/*", recover)
                context.tracing.start(screenshots=True, snapshots=True)
                try:
                    if mode == "focused-draft":
                        accepted[:] = [other]
                    page.goto(base + "/?view=read", wait_until="networkidle")
                    entries = [a] if mode == "focused-draft" else [a, b]
                    page.evaluate(
                        "entries => { for(const entry of entries) sessionStorage.setItem('alles.read.pending.v1:'+entry.recovery_scope,JSON.stringify(entry)); }",
                        entries,
                    )
                    if mode == "corrupt-first":
                        page.evaluate(
                            "scope=>sessionStorage.setItem('alles.read.pending.v1:'+scope,'{broken')",
                            scope,
                        )
                    page.reload(wait_until="networkidle")
                    field = page.locator("#read-url")
                    save = page.locator("#read-save")
                    if mode == "focused-draft":
                        field.fill(b["url"])
                        hold[0] = True
                        accepted[:] = [other, scope]
                        page.get_by_role("radio", name="unread", exact=True).click()
                        field.focus()
                        field.fill(b["url"])
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        route, response, payload = held[0]
                        route.fulfill(response=response, json=payload)
                        hold[0] = False
                        expect(field).to_be_disabled()
                        expect(field).to_have_value(a["url"])
                        page.locator("#read-save-check").click()
                        expect(field).to_be_enabled()
                        expect(field).to_have_value(b["url"])
                    else:
                        if mode == "corrupt-first":
                            expect(save).to_be_disabled()
                        else:
                            expect(field).to_have_value(a["url"])
                            expect(save).to_be_enabled()
                        if mode == "confirm":
                            page.locator("#read-save-check").click()
                        else:
                            page.locator("#read-save-discard").click()
                            page.get_by_role("alertdialog").get_by_role(
                                "button", name="confirm", exact=True
                            ).click()
                        expect(field).to_have_value(b["url"])
                        expect(field).to_be_disabled()
                        expect(save).to_be_enabled()
                        assert page.evaluate(
                            "scope=>sessionStorage.getItem('alles.read.pending.v1:'+scope)!==null",
                            other,
                        )
                        page.locator("#read-save-check").click()
                        expect(field).to_be_enabled()
                        expect(field).to_have_value("")
                    assert not posts and not errors and not console, (posts, errors, console)
                    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    rows.append(
                        {
                            "scenario_id": "library.url-scopes." + mode,
                            "profile": str(width),
                            "status": "passed",
                        }
                    )
                except Exception as error:
                    rows.append(
                        {
                            "scenario_id": "library.url-scopes." + mode,
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
