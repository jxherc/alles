"""Real pointer cancellation/retry UI with mocked Andromeda HTTP transports.

Run through the owned browser runner. This does not verify a live model, search
provider, source extraction, or server-side cancellation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect
from pw_afterlife_andromeda import search_payload

SIMULATION = (
    "mocked search/providers/preview/overview/verification HTTP; real app UI and pointer input"
)
STOPPED = "overview stopped. normal links are unchanged."


class Transport:
    def __init__(self):
        self.remote = False
        self.hold_next_preview = False
        self.pending = asyncio.Event()
        self.release = asyncio.Event()
        self.released = asyncio.Event()
        self.held_request = None
        self.expected_aborts = []
        self.posts = []
        self.events = []
        self.started = time.monotonic()

    def record(self, event, **details):
        self.events.append(
            {"event": event, "at_ms": round((time.monotonic() - self.started) * 1000, 1), **details}
        )

    def hold(self):
        self.hold_next_preview = True
        self.pending = asyncio.Event()
        self.release = asyncio.Event()
        self.released = asyncio.Event()

    async def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != "127.0.0.1":
            self.record("unexpected_outbound", url=request.url)
            await route.abort("blockedbyclient")
            return
        path = url.path
        if path.startswith("/api/andromeda/"):
            self.record("request", url=request.url, method=request.method)

        async def reply(body):
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        if path == "/api/andromeda/providers":
            await reply(
                {
                    "selected": "searxng",
                    "providers": [{"value": "searxng", "label": "fixture", "available": True}],
                }
            )
        elif path == "/api/andromeda/search":
            await reply(search_payload(request.post_data_json))
        elif path == "/api/andromeda/overview/preview":
            remote = self.remote
            held = self.hold_next_preview
            if held:
                self.hold_next_preview = False
                release, released = self.release, self.released
                self.held_request = request
                self.record("preview_held")
                self.pending.set()
                await release.wait()
                self.record("preview_released")
            await reply(
                {
                    "endpoint_id": "cancellation-fixture",
                    "endpoint": "isolated fixture",
                    "model": "fixture-model",
                    "privacy_class": "remote" if remote else "local",
                }
            )
            if held:
                released.set()
        elif path == "/api/andromeda/overview":
            body = request.post_data_json
            self.posts.append(body)
            self.record("overview_post", body=body)
            quote = "Version 4.0 is the current supported release."
            claim = {
                "text": quote,
                "citations": [
                    {
                        "source_id": "s1",
                        "quote": quote,
                        "url": "https://docs.example.test/releases/4.0",
                        "title": "fixture release notes",
                    }
                ],
            }
            overview = {
                "status": "ready",
                "key_answer": {**claim, "focus": "4.0"},
                "claims": [claim],
            }
            stream = f"data: {json.dumps({'type': 'overview', 'overview': overview})}\n\n"
            await route.fulfill(
                status=200, content_type="text/event-stream", body=stream + "data: [DONE]\n\n"
            )
        elif path == "/api/andromeda/verification/preview":
            await reply({"status": "skipped", "reason": "isolated UI fixture"})
        else:
            await route.continue_()


async def run_profile(browser, base, output, profile, record):
    width = 390 if profile == "phone" else 1440
    context = await browser.new_context(
        viewport={"width": width, "height": 900},
        is_mobile=profile == "phone",
        has_touch=profile == "phone",
        reduced_motion="reduce",
        service_workers="block",
        locale="en-US",
        timezone_id="UTC",
    )
    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
    transport = Transport()
    await context.route("**/*", transport.route)
    page = await context.new_page()
    page.set_default_timeout(15_000)
    events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
    page.on("console", lambda msg: events["console"].append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "requestfailed",
        lambda request: events["failed_requests"].append(
            {
                "url": request.url,
                "failure": request.failure,
                "expected": request in transport.expected_aborts
                and request.failure == "net::ERR_ABORTED",
            }
        ),
    )
    page.on(
        "response",
        lambda response: (
            events["http_errors"].append({"url": response.url, "status": response.status})
            if response.status >= 400
            else None
        ),
    )
    feedback = page.locator("#andromeda-overview-state")
    stop = page.locator("#andromeda-cancel-overview")
    retry = page.locator('[data-andromeda-recovery="retry"]')

    async def search(query):
        await page.locator("#andromeda-query").fill(query)
        await expect(page.locator("#andromeda-form")).to_have_attribute("data-ready", "")
        await page.locator("#andromeda-submit").click()

    async def links():
        return await page.locator("#andromeda-results a[href]").evaluate_all(
            "nodes => nodes.map(node => ({url:node.href, title:node.textContent}))"
        )

    async def release_preview():
        transport.release.set()
        await asyncio.wait_for(transport.released.wait(), timeout=5)
        await page.wait_for_load_state("networkidle")

    current = "andromeda.stop-preview-and-retry"
    record(current, profile, "failed", "workflow did not finish")
    try:
        await page.goto(base, wait_until="networkidle")
        if await page.locator("#setup-skip").is_visible():
            await page.locator("#setup-skip").click()
        await page.locator("#app-drawer-btn").click()
        await page.locator('.app-drawer-item[data-view="andromeda"]').click()
        await expect(page.locator("#andromeda-view")).to_be_visible()
        # Visibility and a previous network-idle event precede async app setup.
        await expect(page.locator("#andromeda-saved-list")).to_have_text("nothing saved yet")
        transport.hold()
        await search("current search release")
        await asyncio.wait_for(transport.pending.wait(), timeout=5)
        await expect(stop).to_be_visible()
        original = await links()
        assert len(original) == 8, original
        assert not transport.posts
        await page.screenshot(path=str(output / f"{profile}-preview-pending.png"))
        transport.expected_aborts.append(transport.held_request)
        transport.record("pointer_stop")
        await stop.click()
        # Feedback must arrive while the preview response is still held.
        await expect(feedback).to_have_text(STOPPED, timeout=1000)
        await expect(stop).to_be_hidden()
        await expect(retry).to_be_visible()
        assert await links() == original
        await page.screenshot(path=str(output / f"{profile}-preview-stopped.png"))
        await release_preview()
        assert not transport.posts, transport.posts
        await expect(feedback).to_have_text(STOPPED)
        await retry.click()
        await expect(page.locator(".andromeda-marker")).to_have_text("4.0")
        assert [row["query"] for row in transport.posts] == ["current search release"]
        assert await links() == original
        await expect(stop).to_be_hidden()
        await page.screenshot(path=str(output / f"{profile}-retry-complete.png"))
        record(current, profile, "passed")

        current = "andromeda.cancel-confirmation-and-retry"
        record(current, profile, "failed", "workflow did not finish")
        transport.remote = True
        await search("remote confirmation fixture")
        dialog = page.locator(".dialog-overlay")
        await expect(dialog).to_be_visible()
        before = len(transport.posts)
        await dialog.locator("[data-dialog-cancel]").click()
        await expect(dialog).to_have_count(0)
        await expect(feedback).to_contain_text("overview cancelled before anything was sent")
        await expect(stop).to_be_hidden()
        assert len(transport.posts) == before
        assert await links() == original
        await page.screenshot(path=str(output / f"{profile}-confirmation-cancelled.png"))
        await retry.click()
        await expect(dialog).to_be_visible()
        await dialog.locator("[data-dialog-confirm]").click()
        await expect(page.locator(".andromeda-marker")).to_have_text("4.0")
        assert len(transport.posts) == before + 1
        assert transport.posts[-1]["confirmed_endpoint_id"] == "cancellation-fixture"
        assert transport.posts[-1]["confirmed_model"] == "fixture-model"
        record(current, profile, "passed")

        current = "andromeda.superseded-preview"
        record(current, profile, "failed", "workflow did not finish")
        transport.remote = False
        transport.hold()
        await search("superseded query")
        await asyncio.wait_for(transport.pending.wait(), timeout=5)
        transport.expected_aborts.append(transport.held_request)
        before = len(transport.posts)
        await search("replacement query")
        await expect(page.locator(".andromeda-marker")).to_have_text("4.0")
        await release_preview()
        assert [row["query"] for row in transport.posts[before:]] == ["replacement query"]
        await expect(page.locator("#andromeda-query")).to_have_value("replacement query")
        await expect(feedback).to_have_text("checked against exact source passages")
        await expect(stop).to_be_hidden()
        assert await links() == original
        await page.screenshot(path=str(output / f"{profile}-replacement-preserved.png"))
        assert await page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert not events["page_errors"], events
        assert not [row for row in events["console"] if row["type"] == "error"], events
        assert not events["http_errors"], events
        assert not [row for row in events["failed_requests"] if not row["expected"]], events
        assert not [row for row in transport.events if row["event"] == "unexpected_outbound"]
        record(current, profile, "passed")
    except BaseException as exc:
        record(current, profile, "failed", f"{type(exc).__name__}: {exc}")
        await page.screenshot(path=str(output / f"{profile}-failure.png"), full_page=True)
        raise
    finally:
        transport.release.set()
        (output / f"{profile}-browser-events.json").write_text(json.dumps(events, indent=2) + "\n")
        (output / f"{profile}-network-events.json").write_text(
            json.dumps(transport.events, indent=2) + "\n"
        )
        await context.tracing.stop(path=str(output / f"{profile}-trace.zip"))
        await context.close()


async def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []

    def record(check, profile, status, error=None):
        scenarios[:] = [row for row in scenarios if (row["id"], row["profile"]) != (check, profile)]
        scenarios.append(
            {
                "id": check,
                "scenario_id": check,
                "profile": profile,
                "status": status,
                "error": error,
                "simulation": SIMULATION,
                "evidence": [f"{profile}-trace.zip", f"{profile}-network-events.json"],
            }
        )
        (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        (output / "browser-environment.json").write_text(
            json.dumps(
                {"browser": "chromium", "version": browser.version, "simulation": SIMULATION},
                indent=2,
            )
            + "\n"
        )
        try:
            for profile in ("desktop", "phone"):
                await run_profile(browser, base, output, profile, record)
        finally:
            await browser.close()
    print(
        "desktop/phone Andromeda cancellation, consent cancellation, retry and superseded-preview checks passed"
    )


if __name__ == "__main__":
    asyncio.run(run())
