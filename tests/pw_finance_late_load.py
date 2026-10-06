"""Keep editable Finance drafts intact when a navigation read finishes late."""

import base64
import json
import os
import struct
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tests"))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
profiles = [(390, "light", False)] + [
    (width, theme, zoom)
    for width, zoom in [(1440, False), (820, False), (390, False), (1440, True)]
    for theme in ["light", "dark"]
    if (width, theme, zoom) != (390, "light", False)
]
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 844 if width == 390 else 900},
                service_workers="block",
                reduced_motion="reduce" if theme == "light" else "no-preference",
                timezone_id="UTC",
                has_touch=width == 390,
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / ("late-load-" + label)
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        dict(
                            manifest_version=3,
                            name="owned zoom check",
                            version="1.0",
                            permissions=["tabs"],
                            background={"service_worker": "zoom.js"},
                        )
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
            held, writes, errors, console, external, events = [], [], [], [], [], []
            hold = False
            page = context.new_page()
            page.set_default_timeout(7000)

            def route(r):
                target = urlparse(r.request.url)
                if (target.scheme, target.netloc) != ("http", urlparse(base).netloc):
                    external.append(r.request.url)
                    return r.abort()
                if target.path == "/api/money/transactions" and r.request.method == "POST":
                    writes.append(r.request.post_data_json)
                if hold and target.path == "/api/money/goals":
                    assert r.request.method == "GET" and not target.query and not held
                    held.append(r)
                    return None
                return r.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            page.on(
                "requestfinished",
                lambda request: events.append(
                    {"method": request.method, "url": request.url, "finished": True}
                ),
            )
            api = context.request

            def activate(locator):
                locator.tap() if width == 390 else locator.press("Enter")

            def ready():
                expect(page.locator("#finance-view")).to_have_attribute("aria-busy", "false")
                expect(page.locator("#finance-view > .specialist-state")).to_have_attribute(
                    "data-state", "ready"
                )

            def entry():
                if page.locator("#money-entry-fields").is_hidden():
                    activate(page.locator("#money-entry-action"))
                expect(page.locator("#tx-payee")).to_be_visible()

            def capture(name):
                png = base64.b64decode(
                    context.new_cdp_session(page).send(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )["data"]
                )
                assert struct.unpack(">II", png[16:24]) == (width, 844 if width == 390 else 900)
                (out / f"{label}-{name}.png").write_bytes(png)
                (out / f"{label}-{name}.json").write_text(
                    json.dumps(
                        page.evaluate("""() => ({
                    fields: Object.fromEntries(['tx-payee','tx-cat','tx-tags','tx-amt'].map(id => [id, document.getElementById(id)?.value])),
                    focus: document.activeElement?.id, width: innerWidth, height: innerHeight,
                    dpr: devicePixelRatio, visualScale: visualViewport.scale,
                    error: document.getElementById('tx-amt-error')?.textContent,
                    entryVisible: !document.getElementById('money-entry-fields')?.hidden
                })"""),
                        indent=2,
                    )
                    + "\n"
                )

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                account = api.post(
                    base + "/api/money/accounts",
                    data={"name": "late load " + label, "currency": "CAD", "opening": 100},
                ).json()
                assert account["id"]
                page.goto(base + "/?app=finance", wait_until="networkidle")
                ready()
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base => {const t=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(t.id,2);return chrome.tabs.getZoom(t.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function(
                        "innerWidth===720 && innerHeight===450 && devicePixelRatio===2"
                    )
                for scenario in ["settled", "late-valid", "late-invalid"]:
                    ready()
                    if scenario != "settled":
                        hold = True
                        with page.expect_request(
                            lambda request: (
                                request.url == base + "/api/money/goals" and request.method == "GET"
                            )
                        ):
                            activate(page.locator("#finance-tab-money"))
                        # A pending route is pumped by locator expectations; the existing form stays usable.
                        expect(page.locator("#finance-view")).to_have_attribute("aria-busy", "true")
                        assert len(held) == 1
                    entry()
                    wanted = {
                        "tx-payee": (
                            "supplies" if scenario == "late-invalid" else "workshop supplies"
                        )
                        + " "
                        + label
                        + " "
                        + scenario,
                        "tx-cat": "community",
                        "tx-tags": "local-test",
                        "tx-amt": "19.75 extra" if scenario == "late-invalid" else "19.75",
                    }
                    for field, value in wanted.items():
                        page.locator("#" + field).fill(value)
                    if scenario == "late-invalid":
                        activate(page.locator("#tx-add"))
                        expect(page.locator("#tx-amt")).to_have_attribute("aria-invalid", "true")
                        assert len(writes) == 2
                    active = page.locator(":focus").element_handle()
                    node = page.locator("#money-entry-fields").element_handle()
                    capture(scenario + "-before")
                    if scenario != "settled":
                        hold = False
                        pending = held.pop()
                        with page.expect_request_finished(
                            lambda request: request.url == base + "/api/money/goals"
                        ):
                            pending.continue_()
                        ready()
                        capture(scenario + "-after")
                        for field, value in wanted.items():
                            expect(page.locator("#" + field)).to_have_value(value)
                        assert node.evaluate(
                            "element => element === document.getElementById('money-entry-fields')"
                        )
                        assert active.evaluate("element => element === document.activeElement")
                    if scenario == "late-invalid":
                        expect(page.locator("#tx-amt")).to_have_attribute("aria-invalid", "true")
                        page.locator("#tx-amt").fill("19.75")
                    expected = page.evaluate("""() => ({account_id: document.getElementById('tx-acct').dataset.value,
                        date: document.getElementById('tx-date').dataset.value})""")
                    expected.update(
                        amount=-19.75,
                        payee=wanted["tx-payee"],
                        category="community",
                        tags="local-test",
                    )
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/money/transactions"
                            and response.request.method == "POST"
                        )
                    ) as result:
                        activate(page.locator("#tx-add"))
                    assert result.value.ok
                    saved = result.value.json()
                    assert {key: writes[-1][key] for key in expected} == expected
                    expect(page.locator("#money-save-results")).to_contain_text(wanted["tx-payee"])
                    stored = next(
                        row
                        for row in api.get(base + "/api/money/transactions").json()
                        if row["id"] == saved["id"]
                    )
                    assert {key: stored[key] for key in expected} == expected
                    page.reload(wait_until="networkidle")
                    ready()
                    reopened = next(
                        row
                        for row in api.get(base + "/api/money/transactions").json()
                        if row["id"] == saved["id"]
                    )
                    assert stored["notes"] == ""
                    assert reopened == stored
                    rows.append(
                        {
                            "profile": label,
                            "scenario": scenario,
                            "saved": stored,
                            "reopened": reopened,
                        }
                    )
                assert len(writes) == 3 and not errors and not console and not external
            finally:
                hold = False
                for pending in held:
                    pending.abort()
                (out / f"{label}-events.json").write_text(
                    json.dumps(
                        {
                            "writes": writes,
                            "errors": errors,
                            "console": console,
                            "external": external,
                            "events": events,
                        },
                        indent=2,
                    )
                    + "\n"
                )
                context.close()
    finally:
        browser.close()
        (out / "late-load-results.json").write_text(json.dumps(rows, indent=2) + "\n")
print(json.dumps({"profiles": len(profiles), "cases": len(rows), "passed": True}))
