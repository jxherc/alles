"""Plan task edits, interrupted writes, filtering and responsive controls.

Real local API/SQLite and pointer/keyboard input. Only the named HTTP 503 responses
and a delayed PATCH are simulated; successful edit/move paths include reload checks.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services import agent_tools

    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile in ("desktop", "phone"):
            width = 1440 if profile == "desktop" else 390
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            events = {"console": [], "page_errors": [], "failed_requests": [], "http_errors": []}
            expected_http = []
            page.on("console", lambda m: events["console"].append({"type": m.type, "text": m.text}))
            page.on("pageerror", lambda e: events["page_errors"].append(str(e)))
            page.on(
                "requestfailed",
                lambda r: events["failed_requests"].append({"url": r.url, "failure": r.failure}),
            )
            page.on(
                "response",
                lambda r: (
                    events["http_errors"].append({"url": r.url, "status": r.status})
                    if r.status >= 400
                    else None
                ),
            )
            current = None
            ids = []
            title = f"review school application 日本語 and collect signed supporting documents {profile}"
            notes = f"planning notes 中文 {profile}"

            def begin(scenario):
                nonlocal current
                current = {
                    "scenario_id": scenario,
                    "feature_id": "plan.tasks-calendar",
                    "profile": profile,
                    "status": "failed",
                    "detail": "workflow did not finish",
                }
                records.append(current)

            def passed(detail="visible UI and real persistence assertions"):
                current.update(status="passed", detail=detail)

            def shot(name):
                page.screenshot(path=str(output / f"plan-{profile}-{name}.png"), full_page=True)

            def activate(control):
                control.tap() if profile == "phone" else control.click()

            def saved():
                return next(
                    task
                    for task in context.request.get(base + "/api/tasks").json()
                    if task["id"] == task_id
                )

            def editor():
                activate(page.get_by_role("button", name="edit " + title, exact=True))
                expect(page.get_by_role("dialog", name="edit task")).to_be_visible()

            def save():
                page.locator("#te-save").click()
                expect(page.get_by_role("dialog", name="edit task")).to_have_count(0)

            def theme(value):
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                page.locator("#today-settings").click()
                choose_settings_section(page, "themes")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                ) as response:
                    page.locator(f'[data-theme-mode="{value}"]').click()
                assert response.value.ok
                page.locator("#settings-modal-close").click()
                page.goto(base + "/?view=plan", wait_until="networkidle")
                page.get_by_role("tab", name="tasks", exact=True).click()
                expect(page.get_by_role("button", name="edit " + title, exact=True)).to_be_visible()
                if value == "light":
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                else:
                    expect(page.locator("html")).not_to_have_attribute("data-theme", "light")

            def unobscured_editor():
                dialog = page.get_by_role("dialog", name="edit task")
                bounds = dialog.bounding_box()
                assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
                assert page.locator("#te-title").evaluate("""e => {
                    const r = e.getBoundingClientRect();
                    return [r.left + 2, r.right - 2].every(x => e.contains(document.elementFromPoint(x, r.top + r.height / 2)));
                }"""), "task title is covered by another surface"
                for label in dialog.locator("label:not(.sr-only)").all():
                    assert label.evaluate("""e => {
                        const r = e.getBoundingClientRect();
                        return e.contains(document.elementFromPoint(r.left + 2, r.top + r.height / 2));
                    }"""), label.inner_text()

            try:
                for index in range(18):
                    body = {
                        "title": title
                        if index == 0
                        else f"prepare library renewal 中文 {profile} {index}",
                        "notes": notes,
                        "due_date": "2032-11-06",
                        "project": "school" if index == 0 else "home",
                        "priority": index % 4,
                        "tags": "planning,家人",
                        "stage": "backlog"
                        if index == 0
                        else ("backlog", "next", "doing", "waiting")[index % 4],
                    }
                    response = context.request.post(base + "/api/tasks", data=body)
                    assert response.ok, response.text()
                    ids.append(response.json()["id"])
                task_id = ids[0]
                endpoint = base + "/api/tasks/" + task_id
                theme("dark" if profile == "desktop" else "light")

                begin("plan.search-edit-consistency")
                search = page.get_by_role("textbox", name="search tasks…", exact=True)
                with page.expect_response(lambda r: "/api/tasks/search?" in r.url):
                    search.fill(title)
                expect(page.locator("#tasks-list .task-item")).to_have_count(1)
                with page.expect_response(lambda r: r.url.endswith("/api/tasks/tree")):
                    search.fill("")
                editor()
                page.locator("#te-due").fill("2032-11-07")
                save()
                assert saved()["due_date"] == "2032-11-07"
                editor()
                expect(page.locator("#te-due")).to_have_value("2032-11-07")
                page.locator("#te-proj").fill("university")
                save()
                page.reload(wait_until="networkidle")
                editor()
                expect(page.locator("#te-due")).to_have_value("2032-11-07")
                expect(page.locator("#te-proj")).to_have_value("university")
                assert saved()["due_date"] == "2032-11-07"
                page.locator("#te-cancel").click()
                passed()

                begin("plan.dirty-editor-recovery")
                editor()
                draft = "unsaved draft kept 中文 " + profile
                page.locator("#te-notes").fill(draft)
                page.keyboard.press("Escape")
                confirmation = page.get_by_role("alertdialog", name="discard unsaved task changes?")
                expect(confirmation).to_be_visible()
                expect(
                    confirmation.get_by_role("button", name="cancel", exact=True)
                ).to_be_focused()
                page.keyboard.press("Shift+Tab")
                expect(
                    confirmation.get_by_role("button", name="confirm", exact=True)
                ).to_be_focused()
                page.keyboard.press("Escape")
                expect(confirmation).to_have_count(0)
                expect(page.locator("#te-notes")).to_have_value(draft)
                expect(page.locator("#te-notes")).to_be_focused()
                # The backdrop is a real pointer target outside the centered editor.
                page.mouse.click(width / 2, 100)
                expect(confirmation).to_be_visible()
                confirmation.get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#te-notes")).to_have_value(draft)
                page.locator("#te-cancel").click()
                expect(confirmation).to_be_visible()
                shot("discard-confirmation")
                confirmation.get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#te-notes")).to_have_value(draft)
                save()
                page.reload(wait_until="networkidle")
                assert saved()["notes"] == draft
                editor()
                page.locator("#te-notes").fill("explicitly discard this")
                page.locator("#te-cancel").click()
                confirmation.get_by_role("button", name="confirm", exact=True).click()
                expect(page.get_by_role("dialog", name="edit task")).to_have_count(0)
                assert saved()["notes"] == draft
                passed(
                    "Escape, backdrop and cancel retain drafts until explicit discard; preserved draft saves after reload"
                )

                begin("plan.pending-save-draft")
                editor()
                pending = "submitted slow write 中文 " + profile
                page.locator("#te-notes").fill(pending)
                held = []

                def hold(route):
                    held.append(route)

                page.route(endpoint, hold)
                page.locator("#te-save").click()
                expect(page.locator("#te-save")).to_be_disabled()
                expect(page.locator("#te-notes")).to_be_disabled()
                expect(page.locator("#te-title")).to_be_disabled()
                expect(page.locator("#te-prio")).to_have_attribute("aria-disabled", "true")
                expect(page.locator("#te-cancel")).to_be_disabled()
                page.keyboard.type("must not enter a disabled field")
                page.keyboard.press("Escape")
                page.mouse.click(width / 2, 100)
                expect(page.get_by_role("dialog", name="edit task")).to_be_visible()
                expect(page.locator("#te-notes")).to_have_value(pending)
                assert len(held) == 1
                shot("pending-save")
                held[0].continue_()
                expect(page.get_by_role("dialog", name="edit task")).to_have_count(0)
                page.unroute(endpoint, hold)
                page.reload(wait_until="networkidle")
                assert saved()["notes"] == pending
                editor()
                page.locator("#te-notes").fill("new edit after completed save")
                save()
                assert saved()["notes"] == "new edit after completed save"
                passed(
                    "real delayed PATCH; pending fields cannot accept lost edits; subsequent edit persists"
                )

                begin("plan.task-edit-recovery")
                editor()
                failed_draft = "retry this failed save 中文 " + profile
                page.locator("#te-notes").fill(failed_draft)

                def fail_edit(route):
                    expected_http.append({"url": endpoint, "status": 503})
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"deliberate task service unavailable"}',
                    )

                page.route(endpoint, fail_edit)
                page.locator("#te-save").click()
                expect(page.locator("#te-save")).to_be_enabled()
                expect(page.locator("#te-notes")).to_be_enabled()
                expect(page.locator("#te-notes")).to_have_value(failed_draft)
                expect(page.locator("#te-prio")).to_have_attribute("aria-disabled", "false")
                expect(page.locator("#te-cancel")).to_be_enabled()
                assert saved()["notes"] == "new edit after completed save"
                expect(page.locator(".task-recovery-message")).to_contain_text("save not confirmed")
                shot("failed-save")
                page.unroute(endpoint, fail_edit)
                page.locator("#te-save").press("Enter")
                expect(page.get_by_role("dialog", name="edit task")).to_have_count(0)
                page.reload(wait_until="networkidle")
                assert saved()["notes"] == failed_draft
                passed(
                    "simulated 503 retains draft, restores all controls and saves correctly on retry"
                )

                begin("plan.task-row-readability")
                row = page.locator(f'.task-item[data-id="{task_id}"]')
                title_bounds = row.locator(".task-title").bounding_box()
                assert title_bounds and title_bounds["width"] >= (
                    200 if profile == "phone" else 400
                ), title_bounds
                for control in row.locator("button").all():
                    bounds = control.bounding_box()
                    assert bounds and bounds["width"] >= 44 and bounds["height"] >= 44, bounds
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                row.scroll_into_view_if_needed()
                shot("readable-rows")
                passed(
                    "long task title has a readable line width; metadata wraps and all row actions retain 44px targets"
                )

                begin("plan.task-editor-visibility")
                for value in ("dark", "light"):
                    theme(value)
                    editor()
                    unobscured_editor()
                    activate(page.get_by_role("combobox", name="priority", exact=True))
                    option = page.get_by_role("option", name="none", exact=True)
                    expect(option).to_be_visible()
                    option.click()
                    shot("editor-" + value)
                    page.locator("#te-cancel").click()
                if profile == "phone":
                    editor()
                    page.set_viewport_size({"width": width, "height": 450})
                    page.locator("#te-title").scroll_into_view_if_needed()
                    shot("editor-short-viewport-top")
                    page.locator("#te-save").scroll_into_view_if_needed()
                    expect(page.locator("#te-save")).to_be_in_viewport()
                    shot("editor-short-viewport")
                    page.locator("#te-cancel").click()
                    page.set_viewport_size({"width": width, "height": 900})
                passed(
                    "both themes; title/labels unobscured; custom menu reachable"
                    + ("; short viewport allows Save scrolling" if profile == "phone" else "")
                )

                begin("plan.board-filter-visibility")
                page.get_by_role("tab", name="task board", exact=True).click()
                board_search = page.get_by_role("searchbox", name="search tasks", exact=True)
                expect(board_search).to_be_visible()
                board_search.fill(title)
                if profile == "phone":
                    page.get_by_role("radio", name="inbox", exact=False).tap()
                expect(page.locator(".plan-board-card:visible")).to_have_count(1)
                card = page.locator(f'.plan-board-card[data-task-id="{task_id}"]')
                expect(card).to_be_visible()
                page.get_by_role("button", name="project: all", exact=True).click()
                page.get_by_role("menuitemradio", name="home", exact=True).click()
                expect(page.locator(".plan-board-card:visible")).to_have_count(0)
                expect(card).to_be_hidden()
                shot("board-no-matches")
                page.get_by_role("button", name="project: home", exact=True).click()
                page.get_by_role("menuitemradio", name="all projects", exact=True).click()
                expect(page.locator(".plan-board-card:visible")).to_have_count(1)
                activate(card.locator(".plan-board-card-main"))
                detail = page.get_by_role("complementary", name="selected task details", exact=True)
                expect(detail).to_contain_text(title)
                shot("board-single-match")
                passed("visible cards match search and project filters on desktop and phone")

                begin("plan.board-move-recovery")

                def fail_move(route):
                    expected_http.append({"url": endpoint, "status": 503})
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"deliberate move unavailable"}',
                    )

                page.route(endpoint, fail_move)
                detail.get_by_role("button", name="move forward", exact=True).click()
                expect(page.get_by_text("deliberate move unavailable", exact=False)).to_be_visible()
                assert saved()["stage"] == "backlog"
                page.unroute(endpoint, fail_move)
                detail.get_by_role("button", name="move forward", exact=True).press("Enter")
                expect(page.get_by_text("deliberate move unavailable", exact=False)).to_have_count(
                    0
                )
                assert saved()["stage"] == "next"
                page.reload(wait_until="networkidle")
                assert saved()["stage"] == "next"
                passed(
                    "simulated failed move leaves stage unchanged; keyboard retry persists after reload"
                )

                begin("plan.aide-recurring-completion")
                repeat_title = f"monthly aide check {profile}"
                response = context.request.post(
                    base + "/api/tasks",
                    data={
                        "title": repeat_title,
                        "due_date": "2026-01-31",
                        "repeat": "monthly",
                        "stage": "doing",
                    },
                )
                assert response.ok, response.text()
                repeat_id = response.json()["id"]
                ids.append(repeat_id)
                # Playwright's sync API owns this thread's event loop.
                with ThreadPoolExecutor(max_workers=1) as worker:
                    result = worker.submit(
                        lambda: asyncio.run(
                            agent_tools.execute("task_done", {"id": repeat_id, "done": True})
                        )
                    ).result(timeout=15)
                assert not result.get("error"), result
                completed = context.request.get(base + "/api/tasks/done").json()
                assert any(
                    task["id"] == repeat_id and task["stage"] == "done" for task in completed
                )
                active = [
                    task
                    for task in context.request.get(base + "/api/tasks").json()
                    if task["title"] == repeat_title
                ]
                assert len(active) == 1 and active[0]["due_date"] == "2026-02-28", active
                next_id = active[0]["id"]
                ids.append(next_id)
                page.goto(base + "/?view=plan", wait_until="networkidle")
                page.get_by_role("tab", name="tasks", exact=True).click()
                search = page.get_by_role("textbox", name="search tasks…", exact=True)
                with page.expect_response(lambda r: "/api/tasks/search?" in r.url):
                    search.fill(repeat_title)
                expect(page.locator(f'.task-item[data-id="{next_id}"]')).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                shot("aide-recurring-task")
                passed("Aide tool completion creates the next Task; Plan shows it after reload")

                begin("plan.aide-task-title")
                before_ids = {
                    task["id"] for task in context.request.get(base + "/api/tasks").json()
                }
                aide_title = f"aide capture {profile}"
                with ThreadPoolExecutor(max_workers=1) as worker:
                    invalid = worker.submit(
                        lambda: asyncio.run(agent_tools.execute("task_add", {"title": "   "}))
                    ).result(timeout=15)
                    added = worker.submit(
                        lambda: asyncio.run(
                            agent_tools.execute("task_add", {"title": f"  {aide_title}  "})
                        )
                    ).result(timeout=15)
                assert invalid.get("error"), invalid
                assert not added.get("error"), added
                active = context.request.get(base + "/api/tasks").json()
                assert len(active) == len(before_ids) + 1
                created = [task for task in active if task["id"] not in before_ids]
                assert len(created) == 1 and created[0]["title"] == aide_title, created
                ids.append(created[0]["id"])
                page.goto(base + "/?view=plan", wait_until="networkidle")
                page.get_by_role("tab", name="tasks", exact=True).click()
                search = page.get_by_role("textbox", name="search tasks…", exact=True)
                with page.expect_response(lambda r: "/api/tasks/search?" in r.url):
                    search.fill(aide_title)
                expect(page.locator(f'.task-item[data-id="{created[0]["id"]}"]')).to_be_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                shot("aide-created-task")
                passed("invalid Aide title saves nothing; cleaned valid title appears in Plan")

                assert not events["page_errors"], events
                assert not events["failed_requests"], events
                assert events["http_errors"] == expected_http, events
                errors = [event for event in events["console"] if event["type"] == "error"]
                assert len(errors) == len(expected_http) and all(
                    "503" in event["text"] and "Failed to load resource" in event["text"]
                    for event in errors
                ), events
            except Exception as error:
                if current:
                    current.update(status="failed", detail=str(error))
                shot("failure")
                raise
            finally:
                (output / f"plan-{profile}-events.json").write_text(json.dumps(events, indent=2))
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                for task_id_to_delete in ids:
                    context.request.delete(base + "/api/tasks/" + task_id_to_delete)
                context.tracing.stop(path=str(output / f"plan-{profile}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()
