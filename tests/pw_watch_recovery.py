"""Watch recovery with synthetic monitor/status endpoints and no network probes."""

import copy
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy

BASE = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, theme in [(1440, "dark"), (390, "light")]:
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            has_touch=width == 390,
            service_workers="block",
            reduced_motion="reduce",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(6000)
        errors, console, external = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: console.append(msg.text) if msg.type == "error" else None)

        def boundary(route):
            if urlsplit(route.request.url).netloc == urlsplit(BASE).netloc:
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        context.route("**/*", boundary)
        context.route_web_socket("**/*", lambda socket: socket.close())
        assert context.request.post(BASE + "/api/setup/dismiss").ok
        assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
        monitors = [
            {
                "id": "fixture-monitor",
                "name": "retained monitor",
                "url": "https://owned.example.invalid",
                "status": "up",
                "kind": "http",
                "spark": [8, 10, 7],
                "latest": None,
                "interval_secs": 300,
                "expect_status": 200,
                "expect_keyword": "",
                "latency_ceiling_ms": 0,
            }
        ]
        state = {
            "load": "success",
            "delete": "fail",
            "status": "fail",
            "public": False,
            "deletes": 0,
            "puts": 0,
        }
        held = []

        def fixture(route):
            req, path = route.request, urlsplit(route.request.url).path
            if path == "/api/watch/overview":
                if state["load"] == "hold":
                    held.append((route, copy.deepcopy(monitors)))
                elif state["load"] == "fail":
                    route.fulfill(status=503, json={"detail": "synthetic monitors unavailable"})
                else:
                    route.fulfill(json={"monitors": copy.deepcopy(monitors)})
                return
            if path == "/api/status/config":
                if req.method == "PUT":
                    state["puts"] += 1
                    if state["status"] == "hold":
                        held.append((route, req.post_data_json))
                        return
                    if state["status"] == "fail":
                        route.fulfill(status=503, json={"detail": "synthetic status save failed"})
                        return
                    if state["status"] == "malformed":
                        route.fulfill(json={})
                        return
                    state["public"] = req.post_data_json["enabled"]
                route.fulfill(json={"enabled": state["public"]})
                return
            if path == "/api/watch/fixture-monitor" and req.method == "DELETE":
                state["deletes"] += 1
                if state["delete"] == "hold":
                    held.append((route, None))
                    return
                if state["delete"] == "fail":
                    route.fulfill(status=503, json={"detail": "synthetic deletion failed"})
                    return
                monitors.clear()
                route.fulfill(json={"ok": True})
                return
            if path == "/api/usage/summary":
                route.fulfill(json={"total_tokens": 42, "total_messages": 2})
                return
            raise AssertionError("unexpected Watch request: " + req.method + " " + path)

        for pattern in ["/api/watch**", "/api/status/config", "/api/usage/summary"]:
            page.route(BASE + pattern, fixture)
        row = {"profile": f"{width}-{theme}", "status": "failed", "steps": []}
        rows.append(row)

        def activate(target):
            target.tap() if width == 390 else target.press("Enter")

        def wait_held():
            for _ in range(100):
                if held:
                    return
                page.wait_for_timeout(10)
            assert held

        def screenshot(name):
            page.screenshot(path=str(OUT / f"{width}-{name}.png"))

        try:
            page.goto(BASE + "/?view=watch", wait_until="networkidle")
            card = page.locator('.watch-card[data-id="fixture-monitor"]')
            expect(card).to_be_visible()
            activate(card.locator('[data-act="del"]'))
            activate(
                page.get_by_role("alertdialog").get_by_role("button", name="cancel", exact=True)
            )
            assert state["deletes"] == 0
            activate(card.locator('[data-act="del"]'))
            activate(
                page.get_by_role("alertdialog").get_by_role("button", name="confirm", exact=True)
            )
            expect(page.locator(".toast.error").last).to_contain_text("synthetic deletion failed")
            expect(card).to_be_visible()
            expect(card.locator('[data-act="del"]')).to_be_enabled()
            assert page.locator(".toast.success").filter(has_text="removed").count() == 0
            screenshot("delete-failed")
            row["steps"].append(
                "cancel submits nothing; refused delete keeps monitor and reports error without success"
            )

            toggle = page.locator("#watch-status-toggle")
            activate(toggle)
            expect(page.locator(".toast.error").last).to_contain_text(
                "synthetic status save failed"
            )
            expect(toggle).to_have_text("status: off")
            assert not state["public"]
            assert page.locator(".toast.success").filter(has_text="is now public").count() == 0
            state["status"] = "malformed"
            activate(toggle)
            expect(page.locator(".toast.error").last).to_contain_text("not confirmed")
            expect(toggle).to_have_text("status: off")
            state["status"] = "hold"
            activate(toggle)
            wait_held()
            expect(toggle).to_be_disabled()
            expect(toggle).to_have_attribute("aria-busy", "true")
            page.keyboard.press("Enter")
            assert state["puts"] == 3
            route, payload = held.pop()
            state["public"] = payload["enabled"]
            route.fulfill(json={"enabled": state["public"]})
            expect(toggle).to_have_text("status: public")
            expect(toggle).to_be_enabled()
            screenshot("status-retried")
            row["steps"].append(
                "503 and malformed public-status acknowledgments retain off; pending retry submits once and confirms public"
            )

            state["load"] = "fail"
            activate(page.get_by_role("tab", name="updates", exact=True))
            activate(page.get_by_role("tab", name="watch", exact=True))
            expect(page.locator("#watch-body [role=alert]")).to_contain_text(
                "synthetic monitors unavailable"
            )
            expect(page.locator(".watch-summary")).to_have_text("last loaded monitors")
            expect(card).to_be_visible()
            assert "nothing watched yet" not in page.locator("#watch-body").inner_text()
            screenshot("load-failed-retained")
            state["load"] = "success"
            activate(page.locator("#watch-retry"))
            expect(page.locator("#watch-retry")).to_have_count(0)
            expect(card).to_be_visible()
            row["steps"].append(
                "failed list retains known monitor with explicit error; visible retry recovers"
            )

            state["load"] = "hold"
            activate(page.get_by_role("tab", name="updates", exact=True))
            activate(page.get_by_role("tab", name="watch", exact=True))
            wait_held()
            older, snapshot = held.pop()
            state["load"] = "success"
            monitors[0]["name"] = "newer monitor state"
            activate(page.get_by_role("tab", name="updates", exact=True))
            activate(page.get_by_role("tab", name="watch", exact=True))
            expect(card.locator(".watch-name")).to_have_text("newer monitor state")
            older.fulfill(json={"monitors": snapshot})
            page.wait_for_timeout(100)
            expect(card.locator(".watch-name")).to_have_text("newer monitor state")
            row["steps"].append("a held old overview cannot replace a newer return to Watch")

            state["delete"] = "hold"
            activate(card.locator('[data-act="del"]'))
            activate(
                page.get_by_role("alertdialog").get_by_role("button", name="confirm", exact=True)
            )
            wait_held()
            expect(card.locator('[data-act="del"]')).to_be_disabled()
            page.keyboard.press("Enter")
            assert state["deletes"] == 2
            activate(page.get_by_role("tab", name="updates", exact=True))
            activate(page.get_by_role("tab", name="watch", exact=True))
            expect(card).to_be_visible()
            expect(card.locator('[data-act="del"]')).to_be_disabled()
            route, _ = held.pop()
            monitors.clear()
            route.fulfill(json={"ok": True})
            expect(card).to_have_count(0)
            expect(page.locator(".watch-summary")).to_have_text("no monitors")
            row["steps"].append(
                "delete retry submits once while pending; navigation replaces the card and confirmed deletion removes its current render"
            )
            screenshot("delete-retried")
            state["load"] = "fail"
            page.reload(wait_until="networkidle")
            expect(page.locator(".watch-summary")).to_have_text("monitor status unavailable")
            expect(page.locator("#watch-body [role=alert]")).to_be_visible()
            assert "nothing watched yet" not in page.locator("#watch-body").inner_text()
            state["load"] = "success"
            activate(page.locator("#watch-retry"))
            expect(page.locator(".watch-summary")).to_have_text("no monitors")
            row["steps"].append(
                "first-load failure is unavailable; successful empty retry is explicitly empty"
            )
            assert not errors and not external, (errors, external)
            assert all("503" in message for message in console), console
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            row["status"] = "passed"
        except Exception as error:
            row.update(error=str(error), traceback=traceback.format_exc())
            screenshot("failure")
        finally:
            row.update(page_errors=errors, console_errors=console, external=external)
            (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2))
            context.tracing.stop(path=str(OUT / f"{width}-trace.zip"))
            context.close()
    browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
