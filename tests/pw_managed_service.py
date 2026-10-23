"""Real owned lifecycle/settings/search persistence with synthetic Docker and localhost search."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api


def run(context_factory=None):
    _require_throwaway_data_root()
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    api("POST", "/api/setup/dismiss", {})
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 820, 390):
            existing = api("GET", "/api/system/searxng")
            if existing["installed"]:
                api("POST", "/api/system/searxng/uninstall", {})
            api(
                "POST",
                "/api/test-fixture/managed-search",
                {"pull_failure": True, "malformed": False},
            )
            context = (
                context_factory(pw, width)
                if context_factory
                else browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    reduced_motion="reduce",
                )
            )
            page = context.new_page()
            page.set_default_timeout(9000)
            errors = []
            console = []
            forbidden = []

            def route(r):
                if urlparse(r.request.url).netloc != urlparse(HOME).netloc:
                    forbidden.append(r.request.url)
                    r.abort()
                    return
                r.continue_()

            context.route("**/*", route)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            record = {
                "scenario_id": "managed-service.first-result",
                "profile": str(width),
                "status": "failed",
                "boundary": "real lifecycle/config/search/save APIs; injected Docker runner; synthetic localhost search provider; no external systems",
            }
            gaps = []
            try:
                page.goto(HOME + "/?view=server", wait_until="networkidle")
                root = page.locator("#server-workbench-view")
                root.locator('[data-group-section="services"]').click()
                card = root.locator(".server-workbench-card").filter(
                    has=page.get_by_role("heading", name="searxng", exact=True)
                )
                button = card.get_by_role("button", name="install", exact=True)
                button.focus()
                button.press("Enter")
                expect(card).to_contain_text("SearXNG image pull failed")
                expect(button).to_be_enabled()
                expect(button).to_be_focused()
                if "install in progress" in root.inner_text():
                    gaps.append("failed install leaves an unrelated in-progress status")
                assert not api("GET", "/api/system/searxng")["installed"]
                page.screenshot(path=str(out / f"{width}-failed-install.png"), full_page=True)
                api("POST", "/api/test-fixture/managed-search", {"pull_failure": False})
                starts = api("GET", "/api/test-fixture/managed-search")["starts"]

                def lose_install_acknowledgement(route):
                    assert route.fetch().ok
                    route.fulfill(status=503, json={"detail": "owned lost acknowledgement"})

                page.route("**/api/system/searxng/install", lose_install_acknowledgement, times=1)
                button.press("Enter")
                expect(card).to_contain_text("owned lost acknowledgement")
                page.reload(wait_until="networkidle")
                root.locator('[data-group-section="services"]').click()
                expect(card).to_contain_text("healthy")
                expect(card).not_to_contain_text("image pull failed")
                assert api("GET", "/api/test-fixture/managed-search")["starts"] == starts + 1
                record["uncertain_install_reconciled"] = True
                service = api("GET", "/api/system/searxng")
                settings = api("GET", "/api/settings")
                assert service["installed"] and service["owned"] and service["healthy"]
                assert (
                    settings["search_provider"] == "searxng"
                    and settings["searxng_url"] == service["url"]
                )
                card.get_by_role("button", name="stop", exact=True).click()
                expect(page.locator(".dialog-overlay")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator(".dialog-overlay")).to_be_hidden()
                assert api("GET", "/api/test-fixture/managed-search")["running"]
                card.get_by_role("button", name="test json search", exact=True).click()
                expect(root).to_contain_text("json search passed")
                if "json search passed" not in card.inner_text():
                    gaps.append("service test result appears in another card")
                query = f"owned managed service {width} !ai"
                page.goto(HOME + "/?app=andromeda", wait_until="networkidle")
                page.locator("#andromeda-query").fill(query)
                page.locator("#andromeda-query").press("Enter")
                expect(page.locator(".andromeda-result")).to_have_count(1)
                expect(page.locator(".andromeda-result")).to_contain_text("owned service result")
                page.locator("#andromeda-save").click()
                expect(page.locator("#andromeda-save-message")).to_have_text("search saved")
                saved = [
                    s for s in api("GET", "/api/andromeda/saved")["searches"] if s["query"] == query
                ]
                assert len(saved) == 1
                page.locator("#andromeda-save-open").click()
                expect(page.locator(".andromeda-result")).to_have_count(1)
                page.wait_for_url(
                    lambda url: parse_qs(urlparse(url).query).get("saved") == [saved[0]["id"]]
                )
                assert parse_qs(urlparse(page.url).query)["saved"] == [saved[0]["id"]]
                page.reload(wait_until="networkidle")
                expect(page.locator(".andromeda-result")).to_contain_text("owned service result")
                record["useful_result_verified"] = True
                record["saved_id"] = saved[0]["id"]
                record["provider"] = settings["search_provider"]
                state = api("GET", "/api/test-fixture/managed-search")
                assert not state["blocked_providers"], state["blocked_providers"]
                assert any(f"owned managed service {width}" in q for q in state["queries"])
                api("POST", "/api/test-fixture/managed-search", {"malformed": True})
                page.locator("#andromeda-settings-button").click()
                button = page.locator(".andromeda-searxng-settings").get_by_role(
                    "button", name="test search", exact=True
                )
                with page.expect_response(
                    lambda r: urlparse(r.url).path == "/api/system/searxng/test"
                ):
                    button.click()
                expect(button).to_be_enabled()
                status = page.locator("#andromeda-searxng-status")
                record["malformed_status"] = status.inner_text()
                if "passed" in status.inner_text():
                    gaps.append("malformed search response reports success")
                page.screenshot(path=str(out / f"{width}-malformed.png"), full_page=True)
                api("POST", "/api/test-fixture/managed-search", {"malformed": False})
                button.click()
                expect(status).to_contain_text("search passed")
                page.route(
                    "**/api/system/searxng/test",
                    lambda route: route.fulfill(json={"ok": False, "results": 0}),
                    times=1,
                )
                button.click()
                expect(status).to_contain_text("invalid")
                button.click()
                expect(status).to_contain_text("search passed")
                page.goto(HOME + "/?view=server", wait_until="networkidle")
                root = page.locator("#server-workbench-view")
                root.locator('[data-group-section="services"]').click()
                card = root.locator(".server-workbench-card").filter(
                    has=page.get_by_role("heading", name="searxng", exact=True)
                )
                button = card.get_by_role("button", name="test json search", exact=True)
                page.route(
                    "**/api/system/searxng/test",
                    lambda route: route.fulfill(json={"ok": False, "results": 0}),
                    times=1,
                )
                button.click()
                expect(card).to_contain_text("invalid")
                button.click()
                expect(card).to_contain_text("json search passed")
                assert not errors and not forbidden, (errors, forbidden)
                assert not [
                    line
                    for line in console
                    if "status of 409" not in line and "status of 503" not in line
                ], console
                assert not gaps, gaps
                record["status"] = "passed"
            except Exception:
                record["error"] = traceback.format_exc()
            finally:
                record.update(gaps=gaps, page_errors=errors, console=console, forbidden=forbidden)
                record["rendered"] = page.evaluate(
                    "({width:innerWidth,dpr:devicePixelRatio,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth})"
                )
                if record["rendered"]["overflow"]:
                    record["status"] = "failed"
                    record["error"] = record.get("error", "") + "\npage overflow"
                page.screenshot(path=str(out / f"{width}-final.png"), full_page=True)
                rows.append(record)
                context.close()
        browser.close()
    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    print([{k: v for k, v in r.items() if k not in ["error", "console"]} for r in rows])
    raise SystemExit(any(r["status"] != "passed" for r in rows))


if __name__ == "__main__":
    run()
