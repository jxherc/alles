"""Aide tool discovery, task naming and local connection guidance on an owned local application."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

from services.appearance import from_legacy

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
profiles = [(w, t, False) for w in [1440, 390, 320] for t in ["dark", "light"]]
profiles += [(1440, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "service_workers": "block",
                "reduced_motion": "reduce" if theme == "dark" else "no-preference",
                "has_touch": width <= 390,
            }
            if zoom:
                profile = Path(os.environ["ALLES_DATA"]) / label
                extension = profile / "extension"
                extension.mkdir(parents=True)
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned zoom check",
                            "version": "1.0",
                            "permissions": ["tabs"],
                            "background": {"service_worker": "zoom.js"},
                        }
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
            state = {"status": 404, "hold": True, "partial": ""}
            held, requests, errors, console, external = [], [], [], [], []

            def reply(route):
                chunks = []
                if state["partial"]:
                    chunks.append({"delta": state["partial"]})
                if state["status"]:
                    chunks.append({"error": "connection refused at " + base + "/synthetic-model"})
                else:
                    chunks.append({"delta": "successful synthetic local answer"})
                chunks.append({"saved_user": {"id": "synthetic-user"}})
                stream = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                route.fulfill(content_type="text/event-stream", body=stream + "data: [DONE]\n\n")

            def route(request):
                url = urlparse(request.request.url)
                if url.scheme + "://" + url.netloc != base:
                    external.append(request.request.url)
                    return request.abort()
                if url.path == "/api/chat" and request.request.method == "POST":
                    requests.append(request.request.post_data_json)
                    if state["hold"]:
                        held.append(request)
                        return None
                    return reply(request)
                return request.continue_()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {"scenario_id": "aide.tool-discovery", "profile": label, "status": "failed"}
            rows.append(row)
            try:
                api = context.request
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                endpoint = api.post(
                    base + "/api/models/endpoint",
                    data={
                        "name": "owned error fixture",
                        "base_url": base + "/synthetic-model",
                        "provider_adapter": "manual",
                    },
                ).json()
                assert api.patch(
                    base + "/api/models/endpoint/" + endpoint["id"],
                    data={"models": ["local-error-fixture"]},
                ).ok
                assert api.patch(
                    base + "/api/settings",
                    data={
                        "default_endpoint_id": endpoint["id"],
                        "default_model": "local-error-fixture",
                        "model_roles": {},
                        "memory_policy": "off",
                        "memory_auto_inject": False,
                        "intent_suggestions": False,
                        "auto_compact": False,
                    },
                ).ok
                page.goto(base + "/?view=chat", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
                # Central Aide exposes these commands through one named menu.
                # The legacy header controls remain hidden implementation adapters.
                more = page.get_by_role("button", name="more Aide actions", exact=True)
                expect(more).to_be_visible()
                expect(more).to_have_accessible_name("more Aide actions")
                assert more.bounding_box()["height"] >= 44
                expect(page.locator("#sidebar-toggle-btn")).to_be_hidden()
                expect(page.locator("#aide-work-panel-toggle")).to_be_hidden()
                page.screenshot(path=str(out / f"{label}-named-controls.png"))

                def menu_open():
                    if width <= 390:
                        more.tap()
                    else:
                        more.press("Enter")
                    menu = page.get_by_role("menu", name="Aide actions", exact=True)
                    expect(menu).to_be_visible()
                    expect(more).to_have_attribute("aria-expanded", "true")
                    return menu

                menu = menu_open()
                items = menu.get_by_role("menuitem")
                expect(items).to_have_text(
                    [
                        "memory",
                        "archive",
                        "conversation settings",
                        "scheduled work",
                        "skills",
                        "tools",
                        "sign in to a site",
                        "private conversation",
                        "export conversation",
                        "settings",
                    ]
                )
                expect(items.first).to_be_focused()
                page.keyboard.press("End")
                expect(items.last).to_be_focused()
                page.keyboard.press("ArrowDown")
                expect(items.first).to_be_focused()
                for item in items.all():
                    assert item.bounding_box()["height"] >= 44
                menu_box = menu.bounding_box()
                assert menu_box["x"] >= 0 and (
                    menu_box["x"] + menu_box["width"] <= page.evaluate("innerWidth")
                ), menu_box
                page.screenshot(path=str(out / f"{label}-tools.png"))
                page.keyboard.press("Escape")
                expect(more).to_be_focused()
                expect(menu).to_be_hidden()
                menu_open().get_by_role("menuitem", name="tools", exact=True).press("Enter")
                expect(page.locator("#aide-work-panel")).to_be_visible()
                page.wait_for_function(
                    "document.querySelector('#aide-work-panel').contains(document.activeElement)"
                )
                page.keyboard.press("Escape")
                expect(page.locator("#aide-work-panel")).to_be_hidden()
                expect(more).to_be_focused()
                # Use the visible side-task action to retain the fresh-name case.
                menu_open().get_by_role("menuitem", name="tools", exact=True).press("Enter")
                page.get_by_role("button", name="side task", exact=True).click()
                field = page.locator("#composer-ta")
                draft = "keep the current question while comparing models"
                field.fill(draft)
                scope = {
                    "kind": "vault_document",
                    "path": "kept.md",
                    "expected_hash": "synthetic-version",
                }
                page.evaluate("scope=>window._setAideDocumentScope(scope)", scope)

                # These retained compatibility routes are no longer archive menu
                # entries. Exercise their router and back/draft/scope contract without
                # pretending that hidden legacy controls remain discoverable.
                for view, title in [("compare", "compare models"), ("usage", "usage")]:
                    assert page.evaluate("view => window._navigateTo(view)", view)
                    root = page.locator("#" + view + "-view")
                    expect(root).to_be_visible()
                    expect(menu).to_be_hidden()
                    expect(page.locator("#aide-sidebar")).to_be_hidden()
                    if view == "compare":
                        expect(page.locator("#compare-model-status")).not_to_have_text(
                            "loading models…"
                        )
                    else:
                        expect(page.locator("#usage-body")).to_contain_text("no usage recorded")
                    page.screenshot(path=str(out / f"{label}-{view}.png"))
                    page.go_back(wait_until="networkidle")
                    expect(field).to_be_visible()
                    expect(field).to_have_value(draft)
                    assert page.evaluate("window._pendingDocumentScope") == scope
                page.evaluate("window._setAideDocumentScope(null)")
                field.fill("original connection failure question")
                page.locator("#send-btn").click()
                expect(page.locator("#send-btn")).to_be_disabled()
                page.wait_for_function(
                    "document.querySelector('#stop-btn').classList.contains('visible')"
                )
                assert len(held) == 1
                sid = requests[0]["session_id"]
                session = api.get(base + "/api/sessions/" + sid + "/history").json()["session"]
                assert session["name"] == "new task", session
                expect(page.locator("#aide-history-name")).to_have_text("new task")
                field.fill("newer draft survives the connection failure")
                reply(held.pop())
                notice = page.locator(".error-msg.model-error").last
                expect(notice.get_by_role("status")).to_have_text(
                    "the model could not be reached. check its connection in model settings, then try again."
                )
                expect(page.locator("#conn-banner")).to_be_visible()
                banner = page.locator("#conn-banner").inner_text()
                assert "http" not in banner and "terminal" not in banner and "python" not in banner
                expect(notice.locator("pre")).to_be_hidden()
                retry = notice.get_by_role("button", name="retry response", exact=True)
                expect(retry).to_be_visible()
                settings = notice.get_by_role("button", name="model settings", exact=True)
                settings.press("Enter")
                expect(page.locator("#s-pane-models")).to_be_visible()
                page.keyboard.press("Escape")
                expect(settings).to_be_focused()
                summary = notice.locator("summary")
                summary.press("Enter")
                expect(notice.locator("pre")).to_have_text(
                    "connection refused at " + base + "/synthetic-model"
                )
                summary.press("Enter")
                expect(notice.locator("pre")).to_be_hidden()
                retry.focus()
                geometry = retry.evaluate("""el => {
                    const r = el.getBoundingClientRect();
                    const c = el.closest('.chat').getBoundingClientRect();
                    const style = getComputedStyle(el);
                    const ring = Math.max(0, parseFloat(style.outlineOffset) + parseFloat(style.outlineWidth));
                    return {top: r.top - ring, bottom: r.bottom + ring,
                        chatTop: c.top, chatBottom: c.bottom, height: r.height,
                        topHit: el.contains(document.elementFromPoint(r.x + r.width / 2, r.top + 1)),
                        bottomHit: el.contains(document.elementFromPoint(r.x + r.width / 2, r.bottom - 1))};
                }""")
                row["retry_geometry"] = geometry
                # Allow subpixel layout rounding, but keep the button and focus ring reachable.
                assert geometry["top"] >= geometry["chatTop"] - 1, geometry
                assert geometry["bottom"] <= geometry["chatBottom"] + 1, geometry
                assert geometry["height"] >= 44 and geometry["topHit"] and geometry["bottomHit"], (
                    geometry
                )
                page.screenshot(path=str(out / f"{label}-connection.png"))
                state.update(status=0, hold=False)
                retry.press("Enter")
                expect(page.locator(".ai-content").last).to_have_text(
                    "successful synthetic local answer"
                )
                reply_actions = page.locator(".ai-wrap").last
                reply_more = reply_actions.get_by_role("button", name="more reply actions")
                reply_more.scroll_into_view_if_needed()
                reply_more.press("Enter")
                stream_action = reply_actions.get_by_role("menuitem", name="+plan task", exact=True)
                expect(stream_action).to_be_visible()
                expect(stream_action).to_have_attribute("title", "review this reply as a plan task")
                row["streamed_plan_action_verified"] = True
                page.keyboard.press("Escape")
                expect(page.locator("#conn-banner")).to_be_hidden()
                expect(field).to_have_value("newer draft survives the connection failure")
                # An existing owner-provided name remains unchanged after the new default.
                named = api.post(base + "/api/sessions", data={"name": "new chat"}).json()
                page.goto(base + "/?view=chat#" + named["id"], wait_until="networkidle")
                page.reload(wait_until="networkidle")
                expect(page.locator("#aide-history-name")).to_have_text("new chat")
                assert (
                    api.get(base + "/api/sessions/" + named["id"] + "/history").json()["session"][
                        "name"
                    ]
                    == "new chat"
                )
                project = api.post(
                    base + "/api/projects", data={"name": "local daily project"}
                ).json()
                page.evaluate("id => window._openProject(id)", project["id"])
                project_view = page.locator("#project-view")
                expect(project_view.locator("#pj-chats")).to_contain_text("no aide tasks yet")
                expect(project_view.locator(".s-card-head").first).to_have_text("aide tasks · 0")
                project_view.get_by_role("button", name="+ new aide task", exact=True).press(
                    "Enter"
                )
                expect(page.locator("#aide-history-name")).to_have_text("new task")
                page.wait_for_function(
                    "id => window._currentSession?.project_id === id", arg=project["id"]
                )
                created_id = page.evaluate("window._currentSession.id")
                saved = api.get(base + "/api/sessions/" + created_id + "/history").json()["session"]
                assert saved["name"] == "new task" and saved["project_id"] == project["id"], saved
                page.reload(wait_until="networkidle")
                expect(page.locator("#aide-history-name")).to_have_text("new task")
                assert not errors and not console and not external, (errors, console, external)
                row.update(
                    status="passed",
                    checks="visible More menu keyboard/focus and compatibility router routes, back with draft/scope, new task name without rewriting old name, bounded connection details/settings/retry",
                )
            except Exception as error:
                row.update(
                    error=str(error),
                    traceback=traceback.format_exc(),
                    page_errors=errors,
                    console_errors=console,
                )
                page.screenshot(path=str(out / f"{label}-failed.png"))
            finally:
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
    finally:
        browser.close()
assert all(row["status"] == "passed" for row in rows), "see scenarios.json"
