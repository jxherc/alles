"""Habit create retries and archive restoration use real disposable server records."""

import json
import os
import re
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in [
                "retry",
                "uuid-fallback",
                "retry-list-failed",
                "conflict",
                "cancel",
                "missing",
                "rejected-after-lost",
                "deleted",
                "archived-recovery",
                "archive-recovery-selection",
                "archive-close-pending",
                "archive-close-navigation",
                "recovery-navigation",
                "recovery-list-navigation",
                "retry-save-navigation",
                "retry-error-navigation",
                "archive-restore",
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="UTC",
                    reduced_motion="reduce",
                    service_workers="block",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                if case == "uuid-fallback":
                    context.add_init_script(
                        "Object.defineProperty(crypto, 'randomUUID', {value: undefined})"
                    )
                page = context.new_page()
                page.set_default_timeout(7000)
                errors, console, posts = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                page.on(
                    "request",
                    lambda req: (
                        posts.append(req.post_data_json)
                        if req.url == base + "/api/habits" and req.method == "POST"
                        else None
                    ),
                )
                name = f"reading {case} {width}"
                overview = base + "/api/habits/overview"
                archived_route = re.compile(
                    re.escape(overview) + r"\?date_q=\d{4}-\d{2}-\d{2}&archived=true$"
                )
                overview_route = re.compile(re.escape(overview) + r"\?date_q=\d{4}-\d{2}-\d{2}$")
                form = page.locator(".habit-add")
                result = {
                    "scenario_id": "habits.create." + case,
                    "feature_id": "health.logs-and-habits",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                scenarios.append(result)

                def rows(archived=False):
                    return context.request.get(overview, params={"archived": archived}).json()[
                        "habits"
                    ]

                def unavailable(route):
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"synthetic unavailable"}',
                    )

                def lost(route):
                    if case != "missing":
                        response = route.fetch()
                        assert response.ok, response.text()
                    unavailable(route)

                def keyboard(locator):
                    expect(locator).to_be_enabled()
                    locator.focus()
                    page.keyboard.press("Enter")

                def open_form():
                    keyboard(page.locator("#habits-add-toggle"))
                    form.locator('[data-f="name"]').fill(name)

                def discard_confirmation():
                    keyboard(page.locator(".dialog-overlay [data-dialog-confirm]"))

                try:
                    context.request.post(base + "/api/setup/dismiss")
                    if case == "archive-recovery-selection":
                        older = context.request.post(
                            base + "/api/habits", data={"name": "older archived habit"}
                        ).json()
                        assert context.request.patch(
                            base + "/api/habits/" + older["id"], data={"archived": True}
                        ).ok
                    page.goto(base + "/?view=habits", wait_until="networkidle")
                    open_form()
                    if case == "archive-restore":
                        keyboard(form.locator('[data-act="create"]'))
                        expect(form).to_have_count(0)
                        saved = next(row for row in rows() if row["name"] == name)
                        card = page.locator(f'.habit-card[data-id="{saved["id"]}"]')
                        keyboard(card.locator(".habit-day").last)
                        expect(card.locator(".habit-day").last).to_have_class("habit-day done")
                        history = rows()[0]["grid"]
                        keyboard(card.locator('[data-act="edit"]'))
                        keyboard(card.locator('[data-act="archive"]'))
                        expect(card).to_have_count(0)
                        page.route(archived_route, unavailable)
                        keyboard(page.locator('[data-act="archive-view"]'))
                        expect(page.locator(".habit-load-error")).to_be_visible()
                        expect(page.locator(".habits-empty")).to_have_count(0)
                        expect(card).to_have_count(0)
                        page.unroute(archived_route)
                        keyboard(page.locator('[data-act="retry-load"]'))
                        expect(card.locator('[data-act="restore"]')).to_be_visible()
                        expect(card.locator(".habit-day")).to_have_count(0)
                        assert rows(True)[0]["grid"] == history
                        page.screenshot(path=str(output / f"archive-{width}.png"), full_page=True)
                        endpoint = base + "/api/habits/" + saved["id"]
                        page.route(endpoint, unavailable)
                        keyboard(card.locator('[data-act="restore"]'))
                        expect(page.locator(".toast.error").last).to_be_visible()
                        expect(card.locator('[data-act="restore"]')).to_be_enabled()
                        assert rows(True)[0]["grid"] == history
                        page.unroute(endpoint)
                        page.route(endpoint, lost)
                        keyboard(card.locator('[data-act="restore"]'))
                        expect(card.locator('[data-act="restore"]')).to_be_enabled()
                        assert rows()[0]["grid"] == history
                        page.unroute(endpoint)
                        keyboard(card.locator('[data-act="restore"]'))
                        expect(card).to_have_count(0)
                        keyboard(page.locator('[data-act="archive-view"]'))
                        expect(card.locator(".habit-day").last).to_have_class("habit-day done")
                        assert rows()[0]["grid"] == history
                        keyboard(card.locator(".habit-day").last)
                        expect(card.locator(".habit-day").last).to_have_class("habit-day")
                        keyboard(page.locator('[data-act="archive-view"]'))
                        page.evaluate("window._navigateTo('today')")
                        keyboard(
                            page.locator(
                                f'#today-sections [data-view="habits"][data-record="{saved["id"]}"]'
                            )
                        )
                        expect(card).to_be_focused()
                        expect(card.locator(".habit-day").last).to_be_visible()
                    else:
                        page.route(base + "/api/habits", lost)
                        keyboard(form.locator('[data-act="create"]'))
                        expect(form.locator('[role="alert"]')).to_contain_text("could not confirm")
                        expect(form.locator('[data-f="name"]')).to_have_value(name)
                        page.screenshot(
                            path=str(output / f"{case}-{width}-uncertain.png"), full_page=True
                        )
                        if case == "retry":
                            expect(form.locator('[data-act="create"]')).to_be_focused()
                        page.unroute(base + "/api/habits")
                        assert len(rows()) == (0 if case == "missing" else 1)
                        saved = rows()[0] if case != "missing" else None
                        endpoint = base + "/api/habits/" + saved["id"] if saved else None
                        if case == "rejected-after-lost":
                            page.route(
                                base + "/api/habits",
                                lambda route: route.fulfill(
                                    status=400,
                                    content_type="application/json",
                                    body='{"detail":"rejected"}',
                                ),
                            )
                            keyboard(form.locator('[data-act="create"]'))
                            expect(form.locator('[data-act="create"]')).to_be_enabled()
                            page.unroute(base + "/api/habits")
                        if case in {"retry-save-navigation", "retry-error-navigation"}:
                            held = []
                            page.route(
                                base + "/api/habits",
                                lambda route: held.append((route, route.fetch())),
                            )
                            keyboard(form.locator('[data-act="create"]'))
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert held, "save acknowledgment was not held"
                            other = context.request.post(
                                base + "/api/habits", data={"name": "new home selection"}
                            ).json()
                            page.evaluate("window._navigateTo('today')")
                            keyboard(
                                page.locator(
                                    f'#today-sections [data-view="habits"][data-record="{other["id"]}"]'
                                )
                            )
                            selected = page.locator(f'.habit-card[data-id="{other["id"]}"]')
                            expect(selected).to_be_focused()
                            for route, response in list(held):
                                if case == "retry-save-navigation":
                                    route.fulfill(response=response)
                                else:
                                    unavailable(route)
                            page.unroute(base + "/api/habits")
                            expect(selected.locator(".habit-day").last).to_be_enabled()
                            expect(selected).to_be_focused()
                            assert selected.evaluate("el => el.classList.contains('record-target')")
                            if case == "retry-save-navigation":
                                expect(form).to_have_count(0)
                            else:
                                expect(form.locator('[data-f="name"]')).to_have_value(name)
                                expect(form.locator('[role="alert"]')).to_contain_text(
                                    "could not confirm"
                                )
                            assert len(rows()) == 2
                        elif case in {"recovery-navigation", "recovery-list-navigation"}:
                            other = context.request.post(
                                base + "/api/habits", data={"name": "home selected habit"}
                            ).json()
                            assert context.request.patch(endpoint, data={"archived": True}).ok
                            held = []
                            pattern = (
                                base + "/api/habits/requests/**"
                                if case == "recovery-navigation"
                                else archived_route
                            )
                            page.route(pattern, lambda route: held.append(route))
                            keyboard(form.locator('[data-act="open-saved"]'))
                            discard_confirmation()
                            for _ in range(100):
                                if held:
                                    break
                                page.wait_for_timeout(10)
                            assert held, "recovery request was not held"
                            page.evaluate("window._navigateTo('today')")
                            keyboard(
                                page.locator(
                                    f'#today-sections [data-view="habits"][data-record="{other["id"]}"]'
                                )
                            )
                            selected = page.locator(f'.habit-card[data-id="{other["id"]}"]')
                            expect(selected).to_be_focused()
                            for route in list(held):
                                route.fulfill(response=route.fetch())
                            page.unroute(pattern)
                            expect(selected.locator(".habit-day").last).to_be_enabled()
                            expect(page.locator('[data-act="archive-view"]')).to_have_text(
                                "archived habits"
                            )
                            expect(selected).to_be_focused()
                        elif case in {"archive-close-pending", "archive-close-navigation"}:
                            held = []
                            page.route(
                                overview_route,
                                lambda route: held.append(route) if not held else route.continue_(),
                            )
                            keyboard(page.locator('[data-act="archive-view"]'))
                            discard_confirmation()
                            expect(page.locator('#habits-body [role="status"]')).to_contain_text(
                                "loading"
                            )
                            expect(page.locator("#habits-add-toggle")).to_be_disabled()
                            expect(page.locator('[data-act="archive-view"]')).to_be_disabled()
                            if case == "archive-close-navigation":
                                page.evaluate("window._navigateTo('today')")
                                keyboard(
                                    page.locator(
                                        f'#today-sections [data-view="habits"][data-record="{saved["id"]}"]'
                                    )
                                )
                                expect(
                                    page.locator(f'.habit-card[data-id="{saved["id"]}"]')
                                ).to_be_focused()
                            for route in list(held):
                                route.fulfill(response=route.fetch())
                            page.unroute(overview_route)
                            expect(form).to_have_count(0)
                            if case == "archive-close-navigation":
                                expect(page.locator('[data-act="archive-view"]')).to_have_text(
                                    "archived habits"
                                )
                            else:
                                expect(page.locator('[data-act="archive-view"]')).to_have_text(
                                    "active habits"
                                )
                                keyboard(page.locator('[data-act="archive-view"]'))
                            open_form()
                            form.locator('[data-f="name"]').fill("retained next draft")
                            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                            expect(page.locator('#habits-body [role="status"]')).to_have_count(0)
                            expect(form.locator('[data-f="name"]')).to_have_value(
                                "retained next draft"
                            )
                            keyboard(form.locator('[data-act="cancel-add"]'))
                            expect(form).to_have_count(0)
                        elif case in {"cancel", "rejected-after-lost"}:
                            keyboard(form.locator('[data-act="cancel-add"]'))
                            expect(page.locator(".dialog-overlay")).to_be_visible()
                            page.keyboard.press("Escape")
                            expect(form.locator('[data-f="name"]')).to_have_value(name)
                            keyboard(form.locator('[data-act="cancel-add"]'))
                            discard_confirmation()
                            expect(form).to_have_count(0)
                            expect(
                                page.locator(f'.habit-card[data-id="{saved["id"]}"]')
                            ).to_be_visible()
                            if case == "cancel":
                                open_form()
                                keyboard(form.locator('[data-act="create"]'))
                                expect(form).to_have_count(0)
                                assert len(rows()) == 2
                                assert posts[-1]["request_id"] != posts[0]["request_id"]
                        elif case == "deleted":
                            assert context.request.delete(endpoint).ok
                            keyboard(form.locator('[data-act="create"]'))
                            expect(form.locator('[role="alert"]')).to_contain_text("was deleted")
                            expect(form.locator('[data-act="create"]')).to_be_disabled()
                            assert rows() == []
                            keyboard(form.locator('[data-act="cancel-add"]'))
                            discard_confirmation()
                            expect(form).to_have_count(0)
                        elif case in {
                            "conflict",
                            "archived-recovery",
                            "archive-recovery-selection",
                            "missing",
                        }:
                            if case == "conflict":
                                form.locator('[data-f="name"]').fill("changed draft")
                                keyboard(form.locator('[data-act="create"]'))
                                expect(form.locator('[role="alert"]')).to_contain_text(
                                    "already saved"
                                )
                                assert rows()[0]["name"] == name
                                assert context.request.patch(
                                    endpoint, data={"name": "current correction"}
                                ).ok
                            elif case in {"archived-recovery", "archive-recovery-selection"}:
                                assert context.request.patch(endpoint, data={"archived": True}).ok
                            keyboard(form.locator('[data-act="open-saved"]'))
                            discard_confirmation()
                            if case == "missing":
                                expect(form.locator('[role="alert"]')).to_contain_text(
                                    "no saved habit"
                                )
                                expect(form.locator('[data-f="name"]')).to_have_value(name)
                                keyboard(form.locator('[data-act="create"]'))
                                expect(form).to_have_count(0)
                                assert len(rows()) == 1
                            elif case in {"archived-recovery", "archive-recovery-selection"}:
                                expect(form).to_have_count(0)
                                restore = page.locator(
                                    f'.habit-card[data-id="{saved["id"]}"] [data-act="restore"]'
                                )
                                expect(restore).to_be_visible()
                                assert (
                                    len(rows(True))
                                    == (2 if case == "archive-recovery-selection" else 1)
                                    and rows() == []
                                )
                                if case == "archive-recovery-selection":
                                    expect(restore).to_be_focused()
                                keyboard(restore)
                                expect(restore).to_have_count(0)
                                keyboard(page.locator('[data-act="archive-view"]'))
                                assert len(rows()) == 1
                            else:
                                editor = page.locator(".habit-card.editing")
                                expect(editor.locator('[data-f="name"]')).to_have_value(
                                    "current correction"
                                )
                                editor.locator('[data-f="name"]').fill("reviewed correction")
                                keyboard(editor.locator('[data-act="save"]'))
                                expect(page.locator(".habit-name")).to_have_text(
                                    "reviewed correction"
                                )
                                assert len(rows()) == 1 and rows()[0]["id"] == saved["id"]
                        else:
                            if case == "retry-list-failed":
                                page.evaluate(
                                    "document.dispatchEvent(new Event('visibilitychange'))"
                                )
                                expect(
                                    page.locator(f'.habit-card[data-id="{saved["id"]}"]')
                                ).to_be_visible()
                                page.route(overview_route, unavailable)
                            keyboard(form.locator('[data-act="create"]'))
                            expect(form).to_have_count(0)
                            expect(page.locator(".habit-card[data-id]")).to_have_count(1)
                            assert len(rows()) == 1 and rows()[0]["id"] == saved["id"]
                            if case == "retry-list-failed":
                                expect(page.locator(".habit-load-error")).to_be_visible()
                                page.unroute(overview_route)
                                keyboard(page.locator('[data-act="retry-load"]'))
                                expect(page.locator(".habit-load-error")).to_have_count(0)
                        if case not in {"cancel", "archive-restore"}:
                            assert len({post["request_id"] for post in posts}) == 1
                    page.screenshot(path=str(output / f"{case}-{width}.png"), full_page=True)
                    for button in page.locator(
                        '#habits-body [data-act="archive-view"], #habits-body [data-act="restore"]'
                    ).all():
                        box = button.bounding_box()
                        assert box and box["width"] >= 44 and box["height"] >= 44, box
                    assert not errors, errors
                    assert console and all(
                        any(str(code) in message for code in [400, 404, 409, 410, 503])
                        for message in console
                    ), console
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    before = rows() + rows(True)
                    page.reload(wait_until="networkidle")
                    assert rows() + rows(True) == before
                    assert not errors, errors
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                    page.screenshot(path=str(output / f"{case}-{width}-failed.png"), full_page=True)
                finally:
                    for row in rows() + rows(True):
                        context.request.delete(base + "/api/habits/" + row["id"])
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
        browser.close()
    print(json.dumps(scenarios, indent=2))
    raise SystemExit(any(row["status"] != "passed" for row in scenarios))


if __name__ == "__main__":
    run()
