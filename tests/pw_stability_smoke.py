"""Real local Home capture, navigation and Files smoke; run through the owned runner."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run(device: str) -> None:
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    port = os.environ["PORT"]
    base = f"http://127.0.0.1:{port}"
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text("utf-8").strip() == run_id
    require_server_ownership(base, run_id)
    files = data / "files" / "smoke"
    (files / "nested").mkdir(parents=True)
    (files / "proof.txt").write_text("synthetic smoke fixture\n", encoding="utf-8")
    events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
    scenarios = [
        {
            "id": "home.capture-task-persistence",
            "scenario_id": "home.capture-and-navigation.1",
            "feature_id": "home.capture-and-navigation",
            "status": "untested",
        },
        {
            "id": "shell.keyboard-focus-return",
            "feature_id": "accessibility.interface-contract",
            "status": "untested",
        },
        {
            "id": "docs.return-home",
            "scenario_id": "shell.route-history",
            "feature_id": "docs.documents-and-journal",
            "status": "untested",
        },
        {
            "id": "files.local-folder-navigation",
            "feature_id": "files-photos.locations-and-media",
            "status": "untested",
        },
    ]
    current = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 390 if device == "phone" else 1440, "height": 900},
            is_mobile=device == "phone",
            has_touch=device == "phone",
            locale="en-US",
            timezone_id="UTC",
            reduced_motion="reduce",
            service_workers="block",
        )
        fixture = context.request.post(
            base + "/api/vault-md/file",
            data={
                "path": "navigation-proof.md",
                "content": "# Navigation proof\n\nPreserve this document link.\n",
            },
        )
        assert fixture.ok, fixture.text()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(15_000)
        page.on(
            "console",
            lambda message: events["console"].append({"type": message.type, "text": message.text}),
        )
        page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
        page.on(
            "requestfailed",
            lambda request: events["failed_requests"].append(
                {"url": request.url, "failure": request.failure}
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
        try:
            page.goto(base, wait_until="domcontentloaded")
            expect(page.locator("#today-view")).to_be_visible()
            expect(page.locator("#setup-skip")).to_be_visible()
            page.locator("#setup-skip").click()
            expect(page.locator("#setup-wizard")).to_be_hidden()
            if device == "phone":
                page.locator("#today-settings").click()
                page.locator('.s-nav-item[data-pane="themes"]').click()
                with page.expect_response(
                    lambda response: (
                        response.url.endswith("/api/appearance")
                        and response.request.method == "PUT"
                    )
                ) as appearance:
                    page.locator('[data-theme-mode="light"]').click()
                assert appearance.value.ok, appearance.value.text()
                page.locator("#settings-modal-close").click()
                page.reload(wait_until="networkidle")
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
            else:
                expect(page.locator("html")).not_to_have_attribute("data-theme", "light")
            title = f"browser smoke {device} task"
            mode = page.locator("#today-capture-mode")
            if mode.get_attribute("aria-pressed") != "true":
                mode.click()
            capture = page.locator("#today-capture-input")
            capture.fill(title)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/tasks") and response.request.method == "POST"
                )
            ) as saved:
                if device == "phone":
                    page.locator('#today-capture [type="submit"]').click()
                else:
                    capture.press("Enter")
            assert saved.value.ok, saved.value.text()
            expect(capture).to_have_value("")
            expect(capture).to_be_enabled()
            page.reload(wait_until="domcontentloaded")
            expect(page.locator("#today-view")).to_be_visible()
            tasks = context.request.get(base + "/api/tasks").json()
            assert len([task for task in tasks if task["title"] == title]) == 1
            page.screenshot(path=str(output / "home-persisted.png"), full_page=True)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            scenarios[current]["status"] = "passed"
            if device == "phone":
                scenarios.append(
                    {
                        "scenario_id": "home.capture-and-navigation.3",
                        "status": "passed",
                        "checks": [
                            "390px light theme",
                            "pointer capture and persisted task",
                            "no horizontal overflow",
                        ],
                    }
                )
            current = 1

            trigger = page.locator("#app-drawer-btn")
            trigger.press("Enter")
            expect(page.locator("#app-drawer")).to_be_visible()
            expect(page.locator("#app-drawer-close")).to_be_focused()
            page.screenshot(path=str(output / "apps-open.png"), full_page=True)
            page.keyboard.press("Escape")
            expect(page.locator("#app-drawer")).to_be_hidden()
            expect(trigger).to_be_focused()
            scenarios[current]["status"] = "passed"
            current = 2
            page.locator('.today-shortcut[data-view="wiki"]').click()
            expect(page.locator("#wiki-view")).to_be_visible()
            expect(page).to_have_url(re.compile(r"[?&]view=docs(?:&|$)"))
            page.locator('#wiki-empty-recent [data-file="navigation-proof.md"]').click()
            expect(page.get_by_role("heading", name="Navigation proof", exact=True)).to_be_visible()
            document_url = page.url
            trigger.click()
            page.locator('.app-drawer-item[data-view="today"]').click()
            expect(page.locator("#today-view")).to_be_visible()
            expect(page).to_have_url(re.compile(r"[?&]view=today(?:&|$)"))
            for _ in range(2):
                page.reload(wait_until="networkidle")
                expect(page.locator("#today-view")).to_be_visible()
            page.go_back(wait_until="networkidle")
            expect(page.locator("#wiki-view")).to_be_visible()
            expect(page).to_have_url(document_url)
            expect(page.get_by_role("heading", name="Navigation proof", exact=True)).to_be_visible()
            page.go_forward(wait_until="networkidle")
            expect(page.locator("#today-view")).to_be_visible()
            for destination, visible in (
                ("chat", "#composer-ta"),
                ("andromeda", "#andromeda-query"),
            ):
                trigger.click()
                page.locator(f'.app-drawer-item[data-view="{destination}"]').click()
                expect(page.locator(visible)).to_be_visible()
                for _ in range(2):
                    page.reload(wait_until="networkidle")
                    expect(page.locator(visible)).to_be_visible()
                    expect(page).to_have_url(re.compile(rf"[?&]view={destination}(?:&|$)"))
            page.go_back(wait_until="networkidle")
            expect(page.locator("#composer-ta")).to_be_visible()
            page.go_forward(wait_until="networkidle")
            expect(page.locator("#andromeda-query")).to_be_visible()
            page.screenshot(path=str(output / "primary-navigation-reloaded.png"))
            scenarios[current]["status"] = "passed"
            current = 3

            page.goto(f"http://files.localhost:{port}/?p=smoke", wait_until="domcontentloaded")
            names = page.locator("#files-list .file-name-button")
            expect(names).to_have_text(["nested", "proof.txt"])
            names.first.press("Enter")
            expect(page.locator("#files-breadcrumb")).to_contain_text("nested")
            page.locator('[data-crumb-path="smoke"]').click()
            expect(names).to_have_text(["nested", "proof.txt"])
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=str(output / "files-returned.png"), full_page=True)
            assert not events["page_errors"], events["page_errors"]
            assert not [event for event in events["console"] if event["type"] == "error"], events[
                "console"
            ]
            assert not events["failed_requests"], events["failed_requests"]
            assert not events["http_errors"], events["http_errors"]
            scenarios[current]["status"] = "passed"
        except BaseException:
            scenarios[current]["status"] = "failed"
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise
        finally:
            for scenario in scenarios:
                scenario["profile"] = device
            (output / "scenarios.json").write_text(
                json.dumps(scenarios, indent=2) + "\n", encoding="utf-8"
            )
            (output / "browser-events.json").write_text(
                json.dumps(events, indent=2) + "\n", encoding="utf-8"
            )
            (output / "browser-environment.json").write_text(
                json.dumps(
                    {
                        "browser": "chromium",
                        "version": browser.version,
                        "device": device,
                        "viewport": page.viewport_size,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            context.tracing.stop(path=str(output / "trace.zip"))
            context.close()
            browser.close()
    print(
        f"{device} smoke passed: real capture persisted once; shell keyboard focus; Docs/Home; Files keyboard and pointer navigation"
    )


if __name__ == "__main__":
    run(sys.argv[1])
