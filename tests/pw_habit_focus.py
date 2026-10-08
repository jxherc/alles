"""Habit writes preserve newer shell focus and recover focus lost by disabling."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    origin = urlsplit(base)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            for destination in ("shell", "owned"):
                for outcome in ("success", "failure"):
                    context = browser.new_context(
                        viewport={"width": width, "height": 844 if width == 390 else 900},
                        timezone_id="America/Toronto",
                        reduced_motion="reduce",
                        service_workers="block",
                    )
                    denied, sockets = [], []

                    def exact_origin(route):
                        target = urlsplit(route.request.url)
                        if (target.scheme, target.netloc) == (origin.scheme, origin.netloc):
                            route.continue_()
                        else:
                            denied.append({"scheme": target.scheme, "origin": target.netloc})
                            route.abort()

                    def deny_socket(socket):
                        sockets.append(socket.url)
                        socket.close()

                    context.route("**/*", exact_origin)
                    context.route_web_socket("**/*", deny_socket)
                    api = context.request
                    assert api.post(base + "/api/setup/dismiss", max_redirects=0).ok
                    created = api.post(
                        base + "/api/habits",
                        data={"name": f"synthetic focus {width} {destination} {outcome}"},
                        max_redirects=0,
                    )
                    assert created.ok
                    item = created.json()
                    endpoint = base + "/api/habits/" + item["id"]
                    page = context.new_page()
                    page.set_default_timeout(7000)
                    errors, console, held = [], [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            console.append(message.text) if message.type == "error" else None
                        ),
                    )
                    row = {
                        "scenario_id": f"habits.focus.{destination}.{outcome}",
                        "profile": str(width),
                        "status": "untested",
                    }
                    rows.append(row)

                    def keyboard_to(locator, reverse=False):
                        # Same bounded key traversal as pw_mail_compact_navigation.
                        keys = []
                        for _ in range(90):
                            if locator.evaluate("node => document.activeElement === node"):
                                expect(locator).to_be_focused()
                                return keys
                            key = "Shift+Tab" if reverse else "Tab"
                            page.keyboard.press(key)
                            keys.append(key)
                        raise AssertionError("keyboard could not reach " + str(locator))

                    try:
                        page.goto(base + "/?view=habits", wait_until="networkidle")
                        card = page.locator(f'.habit-card[data-id="{item["id"]}"]')
                        action = card.locator(".habit-day").last
                        day = action.get_attribute("data-toggle")
                        shell = page.locator("#app-drawer-btn")
                        expect(shell).to_be_visible()
                        expect(shell).to_be_enabled()
                        assert not shell.evaluate("node => !!node.closest('#habits-body')")
                        page.route(endpoint + "/toggle", lambda route: held.append(route))
                        row["keys_to_action"] = keyboard_to(action)
                        page.keyboard.press("Enter")
                        expect(action).to_be_disabled()
                        expect(page.locator("#habits-body")).to_have_attribute("aria-busy", "true")
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(10)
                        assert len(held) == 1, "expected one held habit write"
                        row["active_after_disable"] = action.evaluate(
                            """node => ({
                                tag: document.activeElement.tagName,
                                id: document.activeElement.id,
                                body: document.activeElement === document.body,
                                original: document.activeElement === node
                            })"""
                        )
                        native_focus = row["active_after_disable"]
                        assert native_focus["body"] or native_focus["original"], native_focus
                        if destination == "shell":
                            row["keys_to_shell"] = keyboard_to(shell, reverse=True)
                            assert row["keys_to_shell"], "newer shell focus requires key navigation"
                            expect(shell).to_be_focused()
                        current_url = page.url
                        expect(page.locator("#habits-body")).to_be_visible()
                        if outcome == "success":
                            response = held[0].fetch(max_redirects=0)
                            assert response.ok
                            held[0].fulfill(response=response)
                        else:
                            held[0].fulfill(status=503, json={"detail": "synthetic unavailable"})
                        held.clear()
                        expect(page.locator("#habits-body")).to_have_attribute("aria-busy", "false")
                        expect(action).to_be_enabled()
                        expect(shell if destination == "shell" else action).to_be_focused()
                        assert page.url == current_url
                        overview_response = api.get(base + "/api/habits/overview", max_redirects=0)
                        assert overview_response.ok
                        overview = overview_response.json()["habits"]
                        saved = next(habit for habit in overview if habit["id"] == item["id"])
                        stored_day = next(value for value in saved["grid"] if value["date"] == day)
                        assert stored_day["done"] == (outcome == "success")
                        expect(action).to_have_attribute(
                            "aria-pressed", "true" if outcome == "success" else "false"
                        )
                        assert not errors, errors
                        assert len(console) == (1 if outcome == "failure" else 0), console
                        assert all("503" in message for message in console), console
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        page.screenshot(
                            path=str(output / f"habit-focus-{width}-{destination}-{outcome}.png")
                        )
                        assert not denied, denied
                        row["status"] = "passed"
                    except Exception as error:
                        row.update(status="failed", error=str(error))
                    finally:
                        row["denied_requests"] = denied
                        row["denied_websockets"] = sockets
                        for route in held:
                            route.abort()
                        page.close()
                        assert api.delete(endpoint, max_redirects=0).ok
                        context.close()
                        (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    print(json.dumps(rows, indent=2))
    raise SystemExit(any(row["status"] != "passed" for row in rows))


if __name__ == "__main__":
    run()
