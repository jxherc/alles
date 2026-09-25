"""Exercise Plan capture and Docs editing through the minimal workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run() -> None:
    port = os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(f"http://127.0.0.1:{port}", run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []

    def record(scenario, width, status, error=None):
        profile = "phone" if width == 390 else "desktop"
        scenarios[:] = [
            row for row in scenarios if (row["scenario_id"], row["profile"]) != (scenario, profile)
        ]
        scenarios.append(
            {
                "scenario_id": scenario,
                "status": status,
                "profile": profile,
                "evidence": [f"trace-{width}.zip"],
                "error": error,
                "simulation": "one HTTP 503 on document save; remaining writes use the real server",
            }
        )
        (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2) + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=width == 390,
                has_touch=width == 390,
                reduced_motion="reduce",
                service_workers="block",
            )
            # Observe completion of the real async watcher, without manufacturing
            # events or activating product controls through the DOM.
            context.add_init_script("""(() => {
              const NativeSource = window.EventSource;
              window.__vaultHandled = [];
              window.EventSource = class extends NativeSource {
                set onmessage(handler) {
                  super.onmessage = async event => {
                    try { await handler.call(this, event); }
                    finally {
                      if (this.url.includes('/api/vault-md/stream')) {
                        try { window.__vaultHandled.push(JSON.parse(event.data)); } catch {}
                      }
                    }
                  };
                }
              };
            })();""")
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15_000)
            errors = []
            expected_console_errors = []
            network = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def console(message):
                if message.type != "error":
                    return
                if message.location.get("url", "").endswith("/api/vault-md/safety/save") and (
                    "503" in message.text or "409" in message.text
                ):
                    expected_console_errors.append(message.text)
                else:
                    errors.append(message.text)

            page.on("console", console)
            page.on(
                "requestfailed",
                lambda request: network.append({"url": request.url, "failure": request.failure}),
            )
            page.on(
                "response",
                lambda response: (
                    network.append({"url": response.url, "status": response.status})
                    if response.status >= 400
                    else None
                ),
            )
            current = "plan.capture-persistence"
            record(current, width, "failed", "workflow did not finish")
            try:
                page.goto(f"http://plan.localhost:{port}/", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                capture = page.locator('.specialist-group-capture input[name="title"]')
                title = f"review a long document title 日本語 {width}"
                capture.fill(title)
                capture.press("Enter")
                expect(capture).to_have_value("")
                unscheduled = page.get_by_role("button", name="unscheduled", exact=False)
                unscheduled.click()
                expect(page.locator(".specialist-workbench-main")).to_contain_text(title)
                expect(
                    page.locator(".specialist-workbench-main").get_by_text(title, exact=True)
                ).to_have_count(1)
                page.reload(wait_until="networkidle")
                unscheduled.click()
                expect(page.locator(".specialist-workbench-main")).to_contain_text(title)
                toggle = page.locator("#plan-view [data-specialist-sidebar-toggle]")
                toggle.click()
                expect(page.locator("#plan-tabs")).to_be_hidden()
                expect(capture).to_be_visible()
                expect(unscheduled).to_be_visible()
                toggle.press("Enter")
                expect(page.locator("#plan-tabs")).to_be_visible()
                page.screenshot(path=str(output / f"plan-{width}-populated.png"))
                record(current, width, "passed")
                current = "docs.save-persistence"
                record(current, width, "failed", "workflow did not finish")

                page.goto(f"http://docs.localhost:{port}/", wait_until="networkidle")
                page.wait_for_function("window.__vaultHandled.some(event => event.hello)")
                page.locator("#wiki-empty-new").click()
                name = f"workspace-{width}.md"
                page.locator("#docs-dialog-input").fill(name)
                page.locator('[data-dialog-action="confirm"]').click()
                page.wait_for_function(
                    "name => window.__vaultHandled.some(event => event.changed?.includes(name))",
                    arg=name,
                )
                expect(page.locator("#wiki-inline-state")).to_be_hidden()
                expect(page.locator("#wiki-stats")).to_have_text("empty document")
                page.locator("#wiki-source-btn").click()
                content = f"# Stable document {width}\n\nSaved through the editor. 中文 📝\n"
                source = page.locator("#wiki-source")
                source.fill(content)
                page.locator("#docs-workbench-view [data-specialist-sidebar-toggle]").click()
                expect(source).to_have_value(content)
                expect(source).to_be_visible()
                if width == 1440:
                    expect(page.locator(".docs-nav-panel")).to_be_visible()
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_contain_text("saved")
                page.goto(f"http://docs.localhost:{port}/?doc={name}", wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text(f"Stable document {width}")
                expect(page.locator("#wiki-preview")).to_contain_text("Saved through the editor.")
                page.screenshot(path=str(output / f"docs-{width}-saved.png"))
                record(current, width, "passed")
                current = "docs.failed-save"
                record(current, width, "failed", "workflow did not finish")

                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                recovered = content + "\nRecovered after a failed save.\n"
                source.fill(recovered)
                page.route(
                    "**/api/vault-md/safety/save",
                    lambda route: route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic save interruption"}',
                    ),
                    times=1,
                )
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_have_text("synthetic save interruption")
                expect(source).to_have_value(recovered)
                disk = context.request.get(
                    f"http://docs.localhost:{port}/api/vault-md/file", params={"path": name}
                )
                assert disk.ok and disk.json()["content"] == content, disk.text()
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                page.reload(wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text(
                    "Recovered after a failed save."
                )
                page.screenshot(path=str(output / f"docs-{width}-recovered.png"))
                record(current, width, "passed")
                current = "docs.concurrent-save"
                record(current, width, "failed", "workflow did not finish")
                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                local_draft = recovered + "\nUnsaved local changes must survive.\n"
                source.fill(local_draft)
                disk = context.request.get(
                    f"http://docs.localhost:{port}/api/vault-md/file", params={"path": name}
                ).json()
                remote = context.request.post(
                    f"http://docs.localhost:{port}/api/vault-md/safety/save",
                    data={
                        "path": name,
                        "content": "# Changed by another tab\n",
                        "expected_hash": disk["hash"],
                    },
                )
                assert remote.ok, remote.text()
                expect(page.locator("#wiki-inline-state")).to_be_visible()
                expect(source).to_have_value(local_draft)
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_contain_text("conflict")
                expect(source).to_have_value(local_draft)
                page.locator("#wiki-inline-state").get_by_role(
                    "button", name="use file from disk"
                ).click()
                expect(page.locator("#wiki-preview")).to_contain_text("Changed by another tab")
                page.reload(wait_until="networkidle")
                expect(page.locator("#wiki-preview")).to_contain_text("Changed by another tab")
                assert len(expected_console_errors) == 2, expected_console_errors
                unexpected = [
                    event
                    for event in network
                    if not (
                        event.get("status") in {503, 409}
                        and event["url"].endswith("/api/vault-md/safety/save")
                        or event.get("failure") == "net::ERR_ABORTED"
                        and "/api/vault-md/stream" in event["url"]
                    )
                ]
                assert not unexpected, unexpected
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                record(current, width, "passed")
            except Exception as exc:
                record(current, width, "failed", str(exc))
                page.screenshot(path=str(output / f"failure-{width}.png"), full_page=True)
                raise
            finally:
                (output / f"events-{width}.json").write_text(json.dumps(errors, indent=2))
                (output / f"network-{width}.json").write_text(json.dumps(network, indent=2))
                context.tracing.stop(path=str(output / f"trace-{width}.zip"))
                context.close()
        browser.close()
    print("minimal Plan and Docs workflows passed at desktop and phone widths")


if __name__ == "__main__":
    run()
