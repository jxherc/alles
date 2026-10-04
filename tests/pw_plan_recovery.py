"""Plan concurrent edits, delayed responses and recoverable per-tab drafts.

Uses real local API/SQLite and pointer/touch/keyboard input. Named response delays,
owner-scope substitution, offline acceptance and browser storage faults are simulated.
"""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    out.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for profile, width in [("desktop", 1440), ("phone", 390)]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                is_mobile=profile == "phone",
                has_touch=profile == "phone",
                reduced_motion="reduce",
                service_workers="block",
                accept_downloads=True,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            events = {
                "console": [],
                "page_errors": [],
                "failed_requests": [],
                "http_errors": [],
                "task_writes": [],
            }
            expected_http = []
            ids = []
            current = None
            a, b = context.new_page(), context.new_page()
            for page in (a, b):
                page.set_default_timeout(10000)
                page.on(
                    "console", lambda m: events["console"].append({"type": m.type, "text": m.text})
                )
                page.on("pageerror", lambda e: events["page_errors"].append(str(e)))
                page.on(
                    "requestfailed",
                    lambda r: events["failed_requests"].append(
                        {"url": r.url, "failure": r.failure}
                    ),
                )
                page.on(
                    "response",
                    lambda r: (
                        events["http_errors"].append({"url": r.url, "status": r.status})
                        if r.status >= 400
                        else None
                    ),
                )
                page.on(
                    "request",
                    lambda r: (
                        events["task_writes"].append({"url": r.url, "body": r.post_data_json})
                        if r.method == "PATCH" and "/api/tasks/" in r.url
                        else None
                    ),
                )

            def begin(name):
                nonlocal current
                current = {
                    "scenario_id": name,
                    "feature_id": "plan.tasks-calendar",
                    "profile": profile,
                    "status": "failed",
                    "detail": "workflow not finished",
                }
                records.append(current)

            def passed(detail):
                current.update(status="passed", detail=detail)

            def action(control):
                control.tap() if profile == "phone" else control.click()

            def shot(page, name):
                page.screenshot(path=str(out / f"plan-{profile}-{name}.png"), full_page=True)

            def enter(page):
                page.goto(base + "/?view=tasks", wait_until="networkidle")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                expect(page.get_by_role("tab", name="tasks", exact=True)).to_have_attribute(
                    "aria-selected", "true"
                )

            def create(title, **fields):
                response = context.request.post(
                    base + "/api/tasks",
                    data={
                        "title": title,
                        "notes": "original note",
                        "due_date": "2032-11-06",
                        "project": "school",
                        **fields,
                    },
                )
                assert response.ok, response.text()
                task = response.json()
                ids.append(task["id"])
                return task

            def saved(task_id=None):
                return next(
                    t
                    for t in context.request.get(base + "/api/tasks").json()
                    if t["id"] == (task_id or item["id"])
                )

            def edit(page):
                action(page.get_by_role("button", name="edit " + item["title"], exact=True))
                expect(page.get_by_role("dialog", name="edit task", exact=True)).to_be_visible()

            def save(page, status=200, closes=True):
                with page.expect_response(
                    lambda r: r.url == endpoint and r.request.method == "PATCH"
                ) as response:
                    action(page.locator("#te-save"))
                assert response.value.status == status, response.value.text()
                if closes:
                    expect(page.get_by_role("dialog", name="edit task", exact=True)).to_have_count(
                        0
                    )
                else:
                    expect(page.locator("#te-save")).to_be_enabled()
                return response.value.json()

            def discard(page):
                action(page.locator("#te-cancel"))
                confirm = page.get_by_role(
                    "alertdialog", name="discard unsaved task changes?", exact=True
                )
                expect(confirm).to_be_visible()
                confirm.get_by_role("button", name="confirm", exact=True).click()
                expect(page.get_by_role("dialog", name="edit task", exact=True)).to_have_count(0)

            def download(page, name):
                with page.expect_download() as result:
                    action(page.locator('[data-task-recovery="export"]'))
                path = out / f"{profile}-{name}.json"
                result.value.save_as(path)
                return json.loads(path.read_text())

            try:
                item = create("review long application 日本語 and supporting documents " + profile)
                alpha = create("alpha 中文 " + profile)
                beta = create("beta 日本語 " + profile)
                completed = create("completed paperwork " + profile)
                assert context.request.patch(
                    base + "/api/tasks/" + completed["id"], data={"done": True}
                ).ok
                endpoint = base + "/api/tasks/" + item["id"]
                enter(a)
                enter(b)

                begin("plan.concurrent-field-edits")
                edit(a)
                edit(b)
                a.locator("#te-due").fill("2032-11-07")
                a.locator("#te-notes").fill("tab A saved note 中文")
                save(a)
                b.locator("#te-proj").fill("university")
                save(b)
                assert set(events["task_writes"][-1]["body"]) == {
                    "project",
                    "expected",
                    "draft_scope",
                }
                assert events["task_writes"][-1]["body"]["expected"] == {"project": "school"}
                b.reload(wait_until="networkidle")
                edit(b)
                expect(b.locator("#te-due")).to_have_value("2032-11-07")
                expect(b.locator("#te-notes")).to_have_value("tab A saved note 中文")
                expect(b.locator("#te-proj")).to_have_value("university")
                assert saved()["due_date"] == "2032-11-07"
                action(b.locator("#te-cancel"))
                passed(
                    "separate real tabs edit different fields; both changes persist after reload"
                )

                begin("plan.saved-refresh-recovery")
                edit(b)
                b.locator("#te-notes").fill("saved despite a failed list refresh")

                def failed_refresh(route):
                    expected_http.append({"url": base + "/api/tasks/tree", "status": 503})
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"detail":"deliberate refresh failure"}',
                    )

                b.route("**/api/tasks/tree", failed_refresh)
                save(b)
                expect(b.locator(".toast.error")).to_contain_text(
                    "task saved, but the list could not refresh"
                )
                assert saved()["notes"] == "saved despite a failed list refresh"
                b.unroute("**/api/tasks/tree", failed_refresh)
                b.reload(wait_until="networkidle")
                assert saved()["notes"] == "saved despite a failed list refresh"
                passed(
                    "simulated refresh failure after real saved PATCH reports saved state, avoids unhandled rejection, and reloads correctly"
                )

                begin("plan.failed-save-guidance")
                edit(b)
                b.locator("#te-notes").fill("keep this exact note after a failed save 中文")

                def failed_save(route):
                    expected_http.append({"url": endpoint, "status": 503})
                    route.fulfill(status=503, json={"detail": "deliberate save failure"})

                b.route(endpoint, failed_save)
                save(b, status=503, closes=False)
                expect(b.locator(".task-recovery-message")).to_have_text(
                    "save not confirmed. your changes are still here. try saving again."
                )
                expect(b.locator(".task-recovery-message")).to_be_focused()
                expect(b.locator(".toast.error")).to_have_count(0)
                expect(b.locator("#te-notes")).to_have_value(
                    "keep this exact note after a failed save 中文"
                )
                assert saved()["notes"] == "saved despite a failed list refresh"
                shot(b, "failed-save-guidance")
                b.unroute(endpoint, failed_save)
                b.reload(wait_until="networkidle")
                expect(b.locator("#te-notes")).to_have_value(
                    "keep this exact note after a failed save 中文"
                )
                save(b)
                assert saved()["notes"] == "keep this exact note after a failed save 中文"
                passed("503 explains retained work and retry; recovered draft saves to real SQLite")

                begin("plan.unconfirmed-save-guidance")
                edit(b)
                b.locator("#te-notes").fill("saved before response became unreadable")

                def unreadable_save(route):
                    response = route.fetch()
                    assert response.ok
                    route.fulfill(response=response, body="{", content_type="application/json")

                b.route(endpoint, unreadable_save)
                action(b.locator("#te-save"))
                expect(b.locator(".task-recovery-message")).to_contain_text("save not confirmed")
                expect(b.locator(".task-recovery-message")).to_be_focused()
                expect(b.locator("#te-save")).to_be_enabled()
                assert saved()["notes"] == "saved before response became unreadable"
                b.unroute(endpoint, unreadable_save)
                expected_http.append({"url": endpoint, "status": 409})
                save(b, status=409, closes=False)
                expect(b.locator(".task-recovery-message")).to_contain_text(
                    "this task changed elsewhere"
                )
                action(b.locator('[data-task-recovery="saved"]'))
                b.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(b.locator("#te-notes")).to_have_value(
                    "saved before response became unreadable"
                )
                action(b.locator("#te-cancel"))
                passed(
                    "unreadable committed response stays uncertain; conditional retry requires review"
                )

                begin("plan.concurrent-conflict-recovery")
                enter(a)
                enter(b)
                edit(a)
                edit(b)
                a.locator("#te-notes").fill("saved in A: original contract")
                b.locator("#te-notes").fill("my draft in B: revised contract 中文")
                save(a)
                expected_http.append({"url": endpoint, "status": 409})
                save(b, status=409, closes=False)
                expect(b.locator(".task-conflict-values")).to_contain_text(
                    "saved in A: original contract"
                )
                expect(b.locator(".task-conflict-values")).to_contain_text(
                    "my draft in B: revised contract 中文"
                )
                expect(b.locator(".task-recovery-message")).to_be_focused()
                b.keyboard.press("Tab")
                expect(b.locator('[data-task-recovery="export"]')).to_be_focused()
                copy = download(b, "conflict-copy")
                assert copy["draft"]["notes"] == "my draft in B: revised contract 中文"
                assert copy["saved"]["notes"] == "saved in A: original contract"
                shot(b, "conflict-comparison")
                action(b.locator('[data-task-recovery="mine"]'))
                confirm = b.get_by_role(
                    "alertdialog",
                    name="replace the conflicting saved values with your changes?",
                    exact=True,
                )
                expect(confirm).to_be_visible()
                b.keyboard.press("Escape")
                expect(b.locator("#te-notes")).to_have_value("my draft in B: revised contract 中文")
                expect(b.locator('[data-task-recovery="mine"]')).to_be_focused()
                action(b.locator('[data-task-recovery="mine"]'))
                confirm.get_by_role("button", name="confirm", exact=True).click()
                expect(b.locator("#te-save")).to_be_focused()
                save(b)
                b.reload(wait_until="networkidle")
                assert saved()["notes"] == "my draft in B: revised contract 中文"
                enter(a)
                enter(b)
                edit(a)
                edit(b)
                a.locator("#te-notes").fill("saved version C")
                b.locator("#te-notes").fill("discard only with my confirmation")
                save(a)
                expected_http.append({"url": endpoint, "status": 409})
                save(b, status=409, closes=False)
                action(b.locator('[data-task-recovery="saved"]'))
                confirm = b.get_by_role(
                    "alertdialog", name="discard your changes and use the saved values?", exact=True
                )
                confirm.get_by_role("button", name="cancel", exact=True).click()
                expect(b.locator("#te-notes")).to_have_value("discard only with my confirmation")
                action(b.locator('[data-task-recovery="saved"]'))
                confirm.get_by_role("button", name="confirm", exact=True).click()
                expect(b.locator("#te-notes")).to_have_value("saved version C")
                action(b.locator("#te-cancel"))
                b.reload(wait_until="networkidle")
                expect(b.get_by_role("dialog", name="edit task", exact=True)).to_have_count(0)
                assert saved()["notes"] == "saved version C"
                passed(
                    "409 keeps both versions; download, nested focus, explicit keep and explicit discard work; retry is conditional"
                )

                begin("plan.draft-history-recovery")
                enter(a)
                edit(a)
                draft = "unsaved reload draft 日本語 " + profile
                a.locator("#te-notes").fill(draft)
                shot(a, "before-reload")
                a.reload(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value(draft)
                expect(a.locator(".task-recovery-message")).to_contain_text(
                    "recovered unsaved task changes"
                )
                assert saved()["notes"] == "saved version C"
                shot(a, "recovered-after-reload")
                discard(a)
                a.goto(base + "/?view=plan", wait_until="networkidle")
                a.goto(base + "/?view=tasks", wait_until="networkidle")
                edit(a)
                a.locator("#te-notes").fill("full history draft 中文 " + profile)
                a.go_back(wait_until="networkidle")
                a.go_forward(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value("full history draft 中文 " + profile)
                save(a)
                a.reload(wait_until="networkidle")
                assert saved()["notes"] == "full history draft 中文 " + profile
                action(a.get_by_role("tab", name="task board", exact=True))
                action(a.get_by_role("tab", name="tasks", exact=True))
                edit(a)
                a.locator("#te-notes").fill("same document history draft")
                draft_url = a.url
                a.go_back(wait_until="domcontentloaded")
                a.get_by_role("alertdialog").get_by_role("button", name="cancel").click()
                expect(a).to_have_url(draft_url)
                expect(a.locator("#te-notes")).to_have_value("same document history draft")
                discard(a)
                a.reload(wait_until="networkidle")
                expect(a.get_by_role("dialog", name="edit task", exact=True)).to_have_count(0)
                passed(
                    "reload, full-document and same-document history retain draft; save persists and explicit discard clears recovery"
                )

                begin("plan.draft-owner-tab-isolation")
                edit(a)
                a.locator("#te-notes").fill("private tab A draft")
                enter(b)
                edit(b)
                expect(b.locator("#te-notes")).to_have_value("full history draft 中文 " + profile)
                action(b.locator("#te-cancel"))

                def other_owner(route):
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"scopes": ["f" * 64]}),
                    )

                a.route("**/api/tasks/draft-scope", other_owner)
                a.reload(wait_until="networkidle")
                expect(a.get_by_role("dialog", name="edit task", exact=True)).to_have_count(0)
                edit(a)
                expect(a.locator("#te-notes")).to_have_value("full history draft 中文 " + profile)
                action(a.locator("#te-cancel"))
                a.unroute("**/api/tasks/draft-scope", other_owner)
                a.reload(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value("private tab A draft")
                discard(a)
                passed(
                    "real second tab cannot read the draft; simulated owner-scope change hides it without deleting the original owner copy"
                )

                begin("plan.draft-storage-failure")
                a.add_init_script("""(() => {
                  const set = Storage.prototype.setItem, remove = Storage.prototype.removeItem;
                  Storage.prototype.setItem = function(k, v) {
                    if (this === sessionStorage && k.startsWith('alles.tasks.draft.v1:') && window.blockTaskDraftWrite)
                      throw new DOMException('deliberate quota failure', 'QuotaExceededError');
                    return set.call(this, k, v);
                  };
                  Storage.prototype.removeItem = function(k) {
                    if (this === sessionStorage && k.startsWith('alles.tasks.draft.v1:') && window.blockTaskDraftRemove)
                      throw new DOMException('deliberate blocked removal', 'SecurityError');
                    return remove.call(this, k);
                  };
                })();""")
                enter(a)
                a.evaluate("window.blockTaskDraftWrite = true")
                edit(a)
                a.locator("#te-notes").fill("draft while browser storage fails 中文")
                expect(a.locator(".task-recovery-message")).to_contain_text(
                    "cannot keep a recovery copy"
                )
                copy = download(a, "storage-failure-copy")
                assert copy["draft"]["notes"] == "draft while browser storage fails 中文"
                native = []

                def keep_work(dialog):
                    native.append(dialog.type)
                    dialog.dismiss()

                a.once("dialog", keep_work)
                try:
                    a.reload(wait_until="domcontentloaded", timeout=3000)
                except Exception:
                    pass
                assert native == ["beforeunload"], native
                expect(a.locator("#te-notes")).to_have_value(
                    "draft while browser storage fails 中文"
                )
                shot(a, "storage-failure-retained")
                a.evaluate("window.blockTaskDraftWrite = false")
                a.locator("#te-notes").fill("recovered storage can keep this draft")
                a.reload(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value(
                    "recovered storage can keep this draft"
                )
                a.evaluate("window.blockTaskDraftRemove = true")
                action(a.locator("#te-cancel"))
                a.get_by_role("alertdialog").get_by_role(
                    "button", name="confirm", exact=True
                ).click()
                expect(a.get_by_role("dialog", name="edit task", exact=True)).to_be_visible()
                expect(a.locator(".task-recovery-message")).to_contain_text(
                    "could not clear the recovery copy"
                )
                a.evaluate("window.blockTaskDraftRemove = false")
                discard(a)
                a.reload(wait_until="networkidle")
                expect(a.get_by_role("dialog", name="edit task", exact=True)).to_have_count(0)
                passed(
                    "simulated write/remove storage errors keep draft, offer real download, warn before reload, and recover after fault removal"
                )

                begin("plan.draft-offline-acceptance")
                edit(a)
                a.locator("#te-notes").fill("queued draft stays recoverable")

                def queued(route):
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body='{"queued":true,"offline":true}',
                    )

                a.route(endpoint, queued)
                save(a, closes=False)
                expect(a.locator(".task-recovery-message")).to_contain_text("change queued offline")
                assert saved()["notes"] != "queued draft stays recoverable"
                a.unroute(endpoint, queued)
                a.reload(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value("queued draft stays recoverable")
                save(a)
                a.reload(wait_until="networkidle")
                assert saved()["notes"] == "queued draft stays recoverable"
                passed(
                    "simulated queued acceptance does not clear the draft or claim server persistence; real retry survives reload"
                )

                begin("plan.response-ownership")
                held = []

                def delay_search(route):
                    if parse_qs(urlparse(route.request.url).query).get("q") == [alpha["title"]]:
                        held.append((route, route.fetch()))
                    else:
                        route.continue_()

                a.route("**/api/tasks/search?*", delay_search)
                search = a.get_by_role("textbox", name="search tasks…", exact=True)
                search.fill(alpha["title"])
                a.wait_for_timeout(250)
                assert held
                with a.expect_response(
                    lambda r: (
                        "/api/tasks/search?" in r.url
                        and parse_qs(urlparse(r.url).query).get("q") == [beta["title"]]
                    )
                ):
                    search.fill(beta["title"])
                expect(a.locator("#tasks-list .task-title")).to_have_text([beta["title"]])
                with a.expect_response(
                    lambda r: (
                        "/api/tasks/search?" in r.url
                        and parse_qs(urlparse(r.url).query).get("q") == [alpha["title"]]
                    )
                ):
                    held[0][0].fulfill(response=held[0][1])
                expect(a.locator("#tasks-list .task-title")).to_have_text([beta["title"]])
                shot(a, "latest-search-retained")
                a.unroute("**/api/tasks/search?*", delay_search)
                enter(a)
                held = []

                def delay_tree(route):
                    held.append((route, route.fetch()))

                a.route("**/api/tasks/tree", delay_tree)
                action(a.get_by_role("button", name="all", exact=True))
                a.wait_for_timeout(100)
                assert held
                with a.expect_response(lambda r: r.url.endswith("/api/tasks/done")):
                    action(a.get_by_role("button", name="history", exact=True))
                expect(a.locator("#tasks-list .task-title")).to_have_text([completed["title"]])
                with a.expect_response(lambda r: r.url.endswith("/api/tasks/tree")):
                    held[0][0].fulfill(response=held[0][1])
                expect(a.locator("#tasks-list .task-title")).to_have_text([completed["title"]])
                expect(a.get_by_role("button", name="history", exact=True)).to_have_attribute(
                    "aria-pressed", "true"
                )
                shot(a, "latest-history-retained")
                a.unroute("**/api/tasks/tree", delay_tree)
                passed(
                    "delayed real search/tree responses cannot replace the latest query or selected History list"
                )

                begin("plan.deleted-task-draft")
                enter(a)
                edit(a)
                a.locator("#te-notes").fill("draft for a task deleted in another tab")
                assert context.request.delete(endpoint).ok
                a.reload(wait_until="networkidle")
                expect(a.locator("#te-notes")).to_have_value(
                    "draft for a task deleted in another tab"
                )
                expected_http.append({"url": endpoint, "status": 404})
                save(a, status=404, closes=False)
                expect(a.locator("#te-notes")).to_have_value(
                    "draft for a task deleted in another tab"
                )
                assert (
                    download(a, "deleted-task-copy")["draft"]["notes"]
                    == "draft for a task deleted in another tab"
                )
                discard(a)
                passed(
                    "real deletion does not destroy the recovery copy; failed save retains it for download or explicit discard"
                )
                assert not events["page_errors"], events
                # Chromium reports a deliberately cancelled beforeunload navigation as a failed document request.
                unexpected = [
                    event
                    for event in events["failed_requests"]
                    if not (
                        event["url"] == base + "/?view=tasks" and "ERR_ABORTED" in event["failure"]
                    )
                ]
                assert not unexpected, events
                assert events["http_errors"] == expected_http, events
                errors = [event for event in events["console"] if event["type"] == "error"]
                assert len(errors) == len(expected_http) and all(
                    "Failed to load resource" in event["text"]
                    and any(str(item["status"]) in event["text"] for item in expected_http)
                    for event in errors
                ), events
            except Exception as error:
                if current:
                    current.update(status="failed", detail=str(error))
                shot(a, "failure-a")
                shot(b, "failure-b")
                raise
            finally:
                (out / f"plan-{profile}-events.json").write_text(json.dumps(events, indent=2))
                (out / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(out / f"plan-{profile}-trace.zip"))
                for task_id in ids:
                    context.request.delete(base + "/api/tasks/" + task_id)
                context.close()
        browser.close()
    print(json.dumps({"status": "passed", "scenarios": records}))


if __name__ == "__main__":
    run()
