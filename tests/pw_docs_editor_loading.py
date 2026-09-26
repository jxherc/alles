"""Prove Docs draft safety across delayed or failed visual-editor loading."""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from collections import Counter
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

CASES = (
    "failed-retry",
    "failed-reload",
    "autosave-reload",
    "done-reentry",
    "discard-reentry",
    "module-failure",
    "focus-retention",
    "visual-choice",
)


def assert_expected_network(case: str, base: str, network: list[dict]) -> None:
    expected = []
    if case in ("failed-retry", "failed-reload"):
        expected.append({"url": base + "/api/vault-md/safety/save", "status": 503})
    elif case == "module-failure":
        module_url = base + "/static/vendor/cm6.bundle.js"
        expected.extend(
            [
                {"url": module_url, "status": 503},
                {"url": module_url, "failure": "net::ERR_ABORTED"},
            ]
        )
    actual_events = Counter(json.dumps(event, sort_keys=True) for event in network)
    expected_events = Counter(json.dumps(event, sort_keys=True) for event in expected)
    assert actual_events == expected_events, {
        "case": case,
        "expected_network": expected,
        "actual_network": network,
    }


async def run() -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    port = os.environ["PORT"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(f"http://127.0.0.1:{port}", run_id)
    base = f"http://docs.localhost:{port}"
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []
    failures = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        for width in (1440, 390):
            for case in CASES:
                name = f"editor-{width}-{case}.md"
                prefix = f"{width}-{case}"
                record = {
                    "scenario_id": f"docs.editor-load-{case}",
                    "profile": "phone" if width == 390 else "desktop",
                    "status": "failed",
                    "evidence": [f"{prefix}-trace.zip", f"{prefix}-observations.json"],
                    "simulation": "held visual module response; failed-* also use one save HTTP503; module-failure returns HTTP503 for the module; other persistence uses the real server",
                }
                scenarios.append(record)
                context = await browser.new_context(
                    viewport={"width": width, "height": 900},
                    is_mobile=width == 390,
                    has_touch=width == 390,
                    reduced_motion="reduce",
                    service_workers="block",
                )
                await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = await context.new_page()
                page.set_default_timeout(15_000)
                release = asyncio.Event()
                intercepted = asyncio.Event()
                events = []
                requests = []
                network = []
                states = []
                page.on("pageerror", lambda error: events.append({"unexpected": str(error)}))

                def on_console(message):
                    if message.type != "error":
                        return
                    url = message.location.get("url", "")
                    expected = "503" in message.text and (
                        (case.startswith("failed-") and url.endswith("/safety/save"))
                        or (case == "module-failure" and url.endswith("/cm6.bundle.js"))
                    )
                    events.append(
                        {"expected" if expected else "unexpected": message.text, "url": url}
                    )

                page.on("console", on_console)
                page.on(
                    "requestfailed",
                    lambda request: network.append(
                        {"url": request.url, "failure": request.failure}
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        network.append({"url": response.url, "status": response.status})
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        requests.append(
                            {
                                "url": request.url,
                                "method": request.method,
                                "body": request.post_data,
                            }
                        )
                        if "/safety/" in request.url
                        else None
                    ),
                )

                async def module_route(route):
                    intercepted.set()
                    await release.wait()
                    if case == "module-failure":
                        await route.fulfill(status=503, content_type="text/javascript", body="")
                    else:
                        await route.continue_()

                await page.route("**/static/vendor/cm6.bundle.js", module_route)
                content = f"---\ntitle: document {width}\n---\n# Original 文档\n\nSaved text.\n"
                draft = content + "\nRecover this new text. 日本語 📝\n"
                expected = draft

                async def stored():
                    response = await context.request.get(
                        base + "/api/vault-md/file", params={"path": name}
                    )
                    assert response.ok, await response.text()
                    return await response.json()

                async def server_draft():
                    response = await context.request.get(
                        base + "/api/vault-md/safety/draft", params={"path": name}
                    )
                    assert response.ok, await response.text()
                    return (await response.json())["draft"]

                async def state(label):
                    dom = await page.evaluate("""() => ({
                        source: document.querySelector('#wiki-source')?.value,
                        sourceHidden: document.querySelector('#wiki-source')?.hidden,
                        visual: document.querySelector('#wiki-live .cm-content')?.innerText,
                        selected: document.querySelector('#wiki-source-btn')?.getAttribute('aria-pressed'),
                        focus: document.activeElement?.id || document.activeElement?.className,
                        load: document.querySelector('#wiki-editor-load-state')?.textContent,
                        recovery: Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('alles.docs.draft.recovery.v1:')))
                    })""")
                    states.append(
                        {
                            "label": label,
                            "dom": dom,
                            "file": await stored(),
                            "draft": await server_draft(),
                        }
                    )
                    await page.screenshot(path=str(output / f"{prefix}-{label}.png"))

                async def type_source(value):
                    source = page.locator("#wiki-source")
                    await source.click()
                    await source.press("ControlOrMeta+A")
                    await page.keyboard.insert_text(value)
                    await expect(source).to_have_value(value)

                async def save_and_reload(value):
                    async with page.expect_response(
                        lambda response: (
                            response.url.endswith("/safety/save")
                            and response.request.method == "POST"
                        )
                    ) as saved:
                        await page.locator("#wiki-save-btn").click()
                    response = await saved.value
                    assert response.ok, await response.text()
                    assert response.request.post_data_json["content"] == value
                    await expect(page.locator("#wiki-save-state")).to_have_text("saved")
                    assert (await stored())["content"] == value
                    await page.reload(wait_until="networkidle")
                    await expect(page.locator("#wiki-preview")).to_contain_text(
                        "Recover this new text."
                    )
                    assert (await stored())["content"] == value
                    remaining = await server_draft()
                    if case == "done-reentry" and remaining:
                        # The save API deliberately keeps a different existing draft.
                        # Prove that both its earlier text and the newly saved file survive.
                        assert remaining["content"] == draft
                        await expect(page.locator("#wiki-inline-state")).to_contain_text(
                            "local draft and the file on disk both changed"
                        )
                    else:
                        assert remaining is None
                    await state("saved-reloaded")

                try:
                    seed = await context.request.post(
                        base + "/api/vault-md/file", data={"path": name, "content": content}
                    )
                    assert seed.ok, await seed.text()
                    if case == "discard-reentry":
                        recovered = await context.request.put(
                            base + "/api/vault-md/safety/draft",
                            data={
                                "path": name,
                                "content": draft,
                                "base_hash": (await stored())["hash"],
                            },
                        )
                        assert recovered.ok, await recovered.text()
                    await page.goto(base + "/?doc=" + name, wait_until="networkidle")
                    if await page.locator("#setup-skip").is_visible():
                        await page.locator("#setup-skip").click()
                    await expect(page.locator("#wiki-preview")).to_contain_text("Original 文档")
                    if case == "discard-reentry":
                        await (
                            page.locator("#wiki-inline-state")
                            .get_by_role("button", name="resume draft", exact=True)
                            .click()
                        )
                    else:
                        await page.locator("#wiki-edit-btn").click()
                    await asyncio.wait_for(intercepted.wait(), 5)
                    await page.locator("#wiki-source-btn").click()
                    await expect(page.locator("#wiki-source")).to_have_value(
                        draft if case == "discard-reentry" else content
                    )
                    if case == "autosave-reload":
                        async with page.expect_response(
                            lambda response: (
                                response.url.endswith("/safety/draft")
                                and response.request.method == "PUT"
                            )
                        ) as secured:
                            await type_source(draft)
                        assert (await secured.value).ok
                        assert (await server_draft())["content"] == draft
                    else:
                        await type_source(draft)
                    if case.startswith("failed-"):

                        async def fail_save(route):
                            await route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"synthetic save interruption"}',
                            )

                        await page.route("**/api/vault-md/safety/save", fail_save, times=1)
                        await page.locator("#wiki-save-btn").click()
                        await expect(page.locator("#wiki-save-state")).to_have_text(
                            "synthetic save interruption"
                        )
                        emergency = await page.evaluate(
                            "path => JSON.parse(localStorage.getItem('alles.docs.draft.recovery.v1:' + encodeURIComponent(path)))",
                            name,
                        )
                        assert emergency["content"] == draft
                        assert (await stored())["content"] == content
                    if case in ("done-reentry", "discard-reentry"):
                        if case == "done-reentry":
                            await page.locator("#wiki-done-btn").click()
                        else:
                            await (
                                page.locator("#wiki-inline-state")
                                .get_by_role("button", name="discard draft", exact=True)
                                .click()
                            )
                            await page.locator('[data-dialog-action="discard"]').click()
                        await expect(page.locator("#wiki-preview")).to_be_visible()
                        await page.locator("#wiki-edit-btn").click()
                        await page.locator("#wiki-source-btn").click()
                        expected = draft + "\nNewest edit entry must win.\n"
                        await type_source(expected)
                    if case == "focus-retention":
                        await page.locator("#wiki-more-btn").click()
                    if case == "visual-choice":
                        await page.locator("#wiki-visual-btn").click()
                    focus = await page.evaluate("document.activeElement.id")
                    await state("pending")
                    release.set()
                    if case == "module-failure":
                        await expect(page.locator("#wiki-editor-load-state")).to_contain_text(
                            "could not load"
                        )
                        await expect(page.locator("#wiki-editor-load-state")).to_be_visible()
                        await expect(page.locator("#wiki-visual-btn")).to_be_disabled()
                    else:
                        await expect(page.locator("#wiki-live .cm-content")).to_have_count(1)
                        await expect(page.locator("#wiki-editor-load-state")).to_be_hidden()
                    await expect(page.locator("#wiki-source")).to_have_value(expected)
                    if case == "visual-choice":
                        await expect(page.locator("#wiki-live .cm-content")).to_be_visible()
                        await expect(page.locator("#wiki-live .cm-content")).to_contain_text(
                            "Recover this new text."
                        )
                        await expect(page.locator("#wiki-visual-btn")).to_have_attribute(
                            "aria-pressed", "true"
                        )
                    else:
                        await expect(page.locator("#wiki-source")).to_be_visible()
                        await expect(page.locator("#wiki-source-btn")).to_have_attribute(
                            "aria-pressed", "true"
                        )
                    assert await page.evaluate("document.activeElement.id") == focus
                    await state("loaded")
                    if case == "focus-retention":
                        await expect(page.locator("#wiki-more-menu")).to_be_visible()
                        await page.keyboard.press("Escape")
                    if case in ("failed-reload", "autosave-reload"):
                        await page.reload(wait_until="networkidle")
                        await expect(page.locator("#wiki-inline-state")).to_contain_text(
                            "private local draft"
                        )
                        assert (await server_draft())["content"] == expected
                        await (
                            page.locator("#wiki-inline-state")
                            .get_by_role("button", name="resume draft", exact=True)
                            .click()
                        )
                        await expect(page.locator("#wiki-live .cm-content")).to_be_visible()
                        await expect(page.locator("#wiki-live .cm-content")).to_contain_text(
                            "Recover this new text."
                        )
                        await page.locator("#wiki-source-btn").click()
                        await expect(page.locator("#wiki-source")).to_have_value(expected)
                        await state("resumed")
                    if case == "module-failure":
                        expected += "\nStill editable after module failure.\n"
                        await type_source(expected)
                    await save_and_reload(expected)
                    assert not [event for event in events if "unexpected" in event], events
                    assert_expected_network(case, base, network)
                    record["status"] = "passed"
                except Exception as error:
                    record["error"] = str(error) or type(error).__name__
                    record["traceback"] = traceback.format_exc()
                    failures.append(f"{prefix}: {error}")
                    await page.screenshot(path=str(output / f"{prefix}-failure.png"))
                finally:
                    release.set()
                    (output / f"{prefix}-observations.json").write_text(
                        json.dumps(
                            {
                                "path": name,
                                "states": states,
                                "requests": requests,
                                "events": events,
                                "network": network,
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    await context.tracing.stop(path=str(output / f"{prefix}-trace.zip"))
                    await context.close()
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n")
                print(f"{prefix}: {record['status']}", flush=True)
        await browser.close()
    assert not failures, "\n".join(failures)


if __name__ == "__main__":
    asyncio.run(run())
