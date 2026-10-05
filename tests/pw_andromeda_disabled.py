"""Owned disabled-search recovery, with synthetic neighboring result transports.

The disabled/off cases use the actual local API and settings. Neighboring result
states are fulfilled locally; this does not verify a live search provider.
"""

import base64
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in (1440, 820, 390) for t in ("dark", "light")]
profiles += [(1440, t, True) for t in ("dark", "light")]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce" if theme == "dark" else "no-preference",
                has_touch=width == 390,
            )
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
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
            errors, blocked, requests = [], [], []
            fixture = {"status": None}

            def guard(route):
                parsed = urlsplit(route.request.url)
                if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                    blocked.append(route.request.url)
                    return route.abort()
                if parsed.path == "/api/system/searxng":
                    return route.fulfill(
                        json={"support_verified": False, "installed": False, "available": False}
                    )
                if parsed.path == "/api/andromeda/search":
                    body = route.request.post_data_json
                    requests.append(body)
                    if fixture["status"]:
                        state = fixture["status"]
                        results = (
                            [
                                {
                                    "title": "owned " + state,
                                    "url": base + "/fixture-source",
                                    "snippet": "synthetic excerpt",
                                }
                            ]
                            if state in ("ready", "partial")
                            else []
                        )
                        return route.fulfill(
                            json={
                                "query": body["query"].replace(" !ai", ""),
                                "used_no_ai": True,
                                "category": body.get("category", "all"),
                                "normal_results_enabled": True,
                                "overview_requested": False,
                                "overview_seed": [],
                                "results": results,
                                "status": state,
                                "provider": "local fixture",
                                "elapsed_ms": 7,
                                "failure_type": "timeout" if state in ("error", "partial") else "",
                                "error": "local timeout" if state in ("error", "partial") else "",
                                "has_more": False,
                            }
                        )
                return route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            row = {"profile": label, "status": "failed"}
            rows.append(row)

            def capture(name):
                shot = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                png = base64.b64decode(shot["data"])
                assert struct.unpack("!II", png[16:24]) == (width, 900)
                (out / f"{label}-{name}.png").write_bytes(png)

            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "search_provider": "disabled",
                        "research_search_provider": "",
                        "search_fallback_chain": [],
                        "andromeda_normal_results": True,
                        "andromeda_overview": False,
                        "language": "en",
                    },
                ).ok
                page.goto(base + "/?view=andromeda", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                    row["native_zoom"] = {"factor": 2, "css_width": 720, "dpr": 2}
                field = page.locator("#andromeda-query")

                def search(query):
                    field.fill(query)
                    with page.expect_response(
                        lambda response: (
                            response.url == base + "/api/andromeda/search"
                            and response.request.method == "POST"
                        )
                    ) as response:
                        field.press("Enter")
                    return response.value.json()

                payload = search("owned local question !ai")
                empty = page.locator("#andromeda-results .andromeda-empty")
                expect(empty).to_contain_text("search is disabled")
                row.update(payload=payload, empty_text=empty.inner_text())
                assert payload["normal_results_enabled"] and not payload["overview_requested"]
                assert payload["status"] == "disabled" and payload["failure_type"] == "disabled"
                assert payload["attempted_sources"] == [] and payload["results"] == []
                action = page.get_by_role("button", name="search settings", exact=True)
                expect(action).to_be_visible()
                bounds = action.bounding_box()
                assert bounds and bounds["height"] >= 44 and bounds["width"] >= 44, bounds
                if width == 390:
                    action.tap()
                else:
                    action.focus()
                    action.press("Enter")
                expect(page.locator("#andromeda-settings-panel")).to_be_visible()
                expect(page.locator("#andromeda-primary-provider")).to_have_attribute(
                    "data-value", "disabled"
                )
                page.keyboard.press("Escape")
                expect(page.locator("#andromeda-settings-panel")).to_be_hidden()
                expect(action).to_be_focused()
                ring = action.evaluate(
                    "e=>({style:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth})"
                )
                assert ring["style"] != "none" and float(ring["width"].replace("px", "")) >= 2, ring
                expect(page.locator("#andromeda-result-meta")).to_have_text("")
                assert requests[-1]["normal_results"] and not requests[-1]["overview"]
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                capture("disabled")
                row.update(action_bounds=bounds, focus_ring=ring)

                if width == 390 and theme == "light":
                    row["localized"] = []
                    for language in ("fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar", "en"):
                        messages = json.loads(
                            (Path.cwd() / "static/locales" / (language + ".json")).read_text()
                        )["messages"]
                        result = page.evaluate(
                            "async language => (await import('/static/js/i18n.js')).prepareLocalization({language})",
                            language,
                        )
                        assert not result["fallback"], result
                        expect(empty).to_contain_text(messages["andromeda.search_disabled"])
                        local_action = page.get_by_role(
                            "button", name=messages["andromeda.search_settings"], exact=True
                        )
                        expect(local_action).to_be_visible()
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        local_action.tap()
                        expect(page.locator("#andromeda-settings-panel")).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(local_action).to_be_focused()
                        capture(language)
                        row["localized"].append(language)

                for state in ("empty", "error", "partial", "ready"):
                    fixture["status"] = state
                    result = search("owned " + state + " !ai")
                    assert result["status"] == state
                    if state in ("ready", "partial"):
                        expect(page.locator("#andromeda-results")).to_contain_text("owned " + state)
                        expect(empty).to_have_count(0)
                        expect(page.locator("#andromeda-result-meta")).to_contain_text("1 result")
                    else:
                        expect(empty).to_have_text(
                            "no web results found. try a broader query."
                            if state == "empty"
                            else "search failed. retry or choose another engine in settings."
                        )
                    expect(
                        page.get_by_role("button", name="search settings", exact=True)
                    ).to_have_count(0)
                fixture["status"] = None
                search("owned disabled again !ai")
                action = page.get_by_role("button", name="search settings", exact=True)
                expect(action).to_be_visible()
                action.focus()
                action.press("Enter")
                expect(page.locator("#andromeda-settings-panel")).to_be_visible()
                with page.expect_response(
                    lambda response: (
                        response.url == base + "/api/settings"
                        and response.request.method == "PATCH"
                    )
                ):
                    page.locator("#andromeda-results-toggle").click()
                page.keyboard.press("Escape")
                result = search("owned hidden results !ai")
                assert not result["normal_results_enabled"]
                expect(empty).to_have_text("normal results are off for this search.")
                expect(
                    page.get_by_role("button", name="search settings", exact=True)
                ).to_have_count(0)
                row.update(
                    requests=requests,
                    boundary="actual disabled/off API and settings; locally fulfilled neighboring result states",
                )
                assert not errors and not blocked, (errors, blocked)
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row.update(errors=errors, blocked=blocked)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
