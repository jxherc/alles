"""Focused browser gate for the one-mode Afterlife Aide shell."""

import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8030")
HOME = f"http://localhost:{PORT}"
LIGHT_APPEARANCE = {
    "_stored": True,
    "preset": "light",
    "colors": {
        "bg": "#f5f4f1",
        "text": "#111111",
        "panel": "#efede9",
        "faint": "#d4d2ce",
        "accent": "#818cf8",
    },
    "font": "sans",
    "density": "comfortable",
    "bgPattern": "none",
    "frosted": False,
}


def _require_throwaway_data_root() -> None:
    data = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or len(run_id) < 16:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if data == temp_root or temp_root not in data.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (data / ".alles-test-owner").read_text("utf-8").strip() != run_id:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(HOME, run_id)


def run() -> None:
    _require_throwaway_data_root()
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        requested_viewport = os.environ.get("VIEWPORT", "").strip().lower()
        viewports = ((1440, 1000, "desktop"), (390, 844, "mobile"))
        for width, height, label in viewports:
            if requested_viewport and label != requested_viewport:
                continue
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
            )
            context.add_init_script(
                """
                localStorage.setItem('alles-appearance', JSON.stringify({
                  preset:'light',
                  colors:{bg:'#f5f4f1',text:'#111111',panel:'#efede9',faint:'#d4d2ce',accent:'#818cf8'},
                  font:'sans',density:'comfortable',bgPattern:'none',frosted:false
                }));
                """
            )
            page = context.new_page()
            page.set_default_timeout(5_000)
            page.set_default_navigation_timeout(10_000)
            projects = [{"id": "project-saved", "name": "saved"}]
            branch_state = {
                "repository": True,
                "current": "main",
                "branches": ["main", "dev-afterlife"],
                "dirty": False,
            }
            terminal_messages: list[dict] = []
            session_requests: list[dict] = []
            chat_requests: list[dict] = []
            reminder_requests: list[dict] = []

            def route_projects(route):
                if route.request.method == "GET":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(projects),
                    )
                    return
                body = json.loads(route.request.post_data or "{}")
                folder = body.get("working_dir", "").rstrip("/")
                created = {
                    "id": "project-folder",
                    "name": folder.rsplit("/", 1)[-1] or "project",
                    "working_dir": folder,
                    "folder_state": "available",
                }
                projects.append(created)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(created),
                )

            def route_project_folders(route):
                path = parse_qs(urlparse(route.request.url).query).get("path", [""])[0]
                if path == "/workspace/alles":
                    body = {"path": path, "parent": "/workspace", "folders": []}
                else:
                    body = {
                        "path": "/workspace",
                        "parent": "/",
                        "folders": [{"name": "alles", "path": "/workspace/alles"}],
                    }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )

            def route_terminal(socket):
                typed = ""

                def receive(message):
                    nonlocal typed
                    event = json.loads(message)
                    terminal_messages.append(event)
                    if event.get("type") != "input":
                        return
                    typed += event.get("data", "")
                    if "\r" in typed and "pwd" in typed:
                        socket.send(b"\r\n/tmp/alles-test\r\n$ ")
                        typed = ""

                socket.on_message(receive)
                socket.send(json.dumps({"type": "ready", "cwd": "/tmp/alles-test"}))
                socket.send(b"$ ")

            page.route_web_socket("**/api/shell/pty**", route_terminal)

            def route_project_branches(route):
                if route.request.method == "POST":
                    body = json.loads(route.request.post_data or "{}")
                    if branch_state.get("reject_next"):
                        branch_state.pop("reject_next", None)
                        route.fulfill(
                            status=409,
                            content_type="application/json",
                            body=json.dumps(
                                {
                                    "code": "project_git_switch_failed",
                                    "detail": "save, commit, or stash the Project changes before switching branches",
                                }
                            ),
                        )
                        return
                    branch_state["current"] = body.get("branch", branch_state["current"])
                    branch_state["branches"] = [
                        branch_state["current"],
                        *[
                            branch
                            for branch in branch_state["branches"]
                            if branch != branch_state["current"]
                        ],
                    ]
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(branch_state),
                )

            page.route("**/api/projects/*/git/branches", route_project_branches)
            page.route("**/api/sessions/*/git/branches", route_project_branches)

            def route_sessions(route):
                if route.request.method != "POST":
                    route.continue_()
                    return
                body = json.loads(route.request.post_data or "{}")
                session_requests.append(body)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "id": "session-context-probe",
                            "name": "context probe",
                            "project_id": body.get("project_id", ""),
                            "working_dir": body.get("working_dir", ""),
                            "environment": {
                                "kind": "legacy_folder" if body.get("working_dir") else "general",
                                "cwd": body.get("working_dir", ""),
                            },
                            "model": body.get("model", ""),
                        }
                    ),
                )

            page.route("**/api/sessions", route_sessions)
            page.route(
                "**/api/sessions/session-context-probe/auto-name",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"name": "project context"}),
                ),
            )
            page.route(
                "**/api/models",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        [
                            {
                                "id": "context-endpoint",
                                "name": "local test",
                                "base_url": "http://127.0.0.1:11434",
                                "provider": "ollama",
                                "models": ["context-model"],
                                "image_models": [],
                                "unavailable_models": [],
                            },
                            {
                                "id": "deepseek-local",
                                "name": "local deepseek",
                                "base_url": "http://127.0.0.1:11434",
                                "provider": "ollama",
                                "models": ["deepseek-v4-pro"],
                                "image_models": [],
                                "unavailable_models": [],
                            },
                        ]
                    ),
                ),
            )
            page.route(
                "**/api/models/roles",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "aide_chat": {
                                "status": "ready",
                                "effective": {
                                    "endpoint_id": "context-endpoint",
                                    "model": "context-model",
                                    "reason": "role_default",
                                },
                            }
                        }
                    ),
                ),
            )

            def route_chat(route):
                chat_requests.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'data: {"context_provenance":{"owner_instructions":false,"project_instructions":false,"memories":[],"model":"context-model","endpoint":"local test"}}\n\n'
                        'data: {"delta":"project context ready"}\n\n'
                        'data: {"done":true,"usage":{}}\n\n'
                        "data: [DONE]\n\n"
                    ),
                )

            page.route("**/api/chat", route_chat)

            def route_reminders(route):
                if route.request.method == "POST":
                    body = json.loads(route.request.post_data or "{}")
                    reminder_requests.append(body)
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"id": f"reminder-{len(reminder_requests)}", **body}),
                    )
                    return
                route.fulfill(status=200, content_type="application/json", body="[]")

            page.route("**/api/reminders*", route_reminders)
            page.route(
                "**/api/appearance",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(LIGHT_APPEARANCE),
                ),
            )
            page.route(
                "**/api/projects",
                route_projects,
            )
            page.route("**/api/project-folders*", route_project_folders)
            page.goto(HOME, wait_until="networkidle")
            page.locator('[data-today-destination="chat"]').click()
            page.wait_for_selector("#chat:visible")

            page.wait_for_function("document.documentElement.dataset.theme === 'light'")
            assert (
                page.locator(".sidebar").evaluate("el => getComputedStyle(el).backgroundColor")
                != "rgb(16, 16, 16)"
            )
            assert (
                page.locator(".composer-box").evaluate("el => getComputedStyle(el).backgroundColor")
                != "rgb(18, 18, 18)"
            )
            assert page.locator("#composer-ta").evaluate(
                "el => el.getBoundingClientRect().height <= 160"
            )

            assert (
                page.locator("#space-rail").evaluate("el => getComputedStyle(el).display") == "none"
            )
            if width >= 700:
                assert page.locator(".sidebar").is_visible()
            else:
                assert not page.locator(".sidebar").is_visible()
                page.locator("#sidebar-toggle-btn").click()
                page.wait_for_selector(".sidebar:visible")
            brand = page.locator(".sidebar-brand")
            first_tool_icon = page.locator(".sidebar-nav .aide-tool-link svg").first
            assert int(brand.evaluate("el => getComputedStyle(el).fontWeight")) <= 400
            assert abs(brand.bounding_box()["x"] - first_tool_icon.bounding_box()["x"]) <= 1
            assert (
                int(
                    page.locator(".section-label").first.evaluate(
                        "el => getComputedStyle(el).fontWeight"
                    )
                )
                <= 400
            )
            assert page.locator("#aide-tools-link span").first.inner_text().strip() == "tools"
            page.locator("#aide-tools-link").click()
            assert page.locator("#aide-sidebar-menu").is_visible()
            assert page.locator("#aide-sidebar-menu [role=menuitem]").all_inner_texts() == [
                "settings",
            ]
            page.keyboard.press("Escape")
            assert not page.locator("#aide-sidebar-menu").is_visible()
            assert page.locator("#mode-chat, #mode-jarvis, #chat-behavior-select").count() == 0
            assert page.locator("select:visible").count() == 0
            assert page.locator(".sidebar-nav .aide-tool-link span").all_inner_texts() == [
                "new task",
                "scheduled",
                "brain",
                "skills",
                "reminders",
            ]
            for tool_view, route_view in (
                ("brain", "brain"),
                ("skills", "skills"),
                ("reminders", "aide-reminders"),
            ):
                if width < 700 and page.locator("body").evaluate(
                    "el => el.classList.contains('sidebar-hidden')"
                ):
                    page.locator("#sidebar-toggle-btn").click()
                page.locator(f'.sidebar-nav [data-view="{route_view}"]').click()
                page.wait_for_selector(f"#{tool_view}-view:visible")
                assert page.locator(f"#{tool_view}-view").evaluate(
                    "el => getComputedStyle(el).animationName === 'none'"
                )
                assert page.locator(f"#{tool_view}-view").evaluate(
                    "el => getComputedStyle(el).backgroundColor === getComputedStyle(document.body).backgroundColor"
                )
            assert page.locator("#brain-proxstats").count() == 0
            if width < 700 and page.locator("body").evaluate(
                "el => el.classList.contains('sidebar-hidden')"
            ):
                page.locator("#sidebar-toggle-btn").click()
            page.locator("#new-chat-btn").click()
            page.wait_for_selector("#chat:visible")
            if width < 700 and page.locator("body").evaluate(
                "el => el.classList.contains('sidebar-hidden')"
            ):
                page.locator("#sidebar-toggle-btn").click()
            page.locator("#aide-scheduled-link").click()
            page.wait_for_selector("#aide-scheduled-view:visible")
            if width < 700 and page.locator("body").evaluate(
                "el => el.classList.contains('sidebar-hidden')"
            ):
                page.locator("#sidebar-toggle-btn").click()
            page.locator('.sidebar-nav [data-view="aide-reminders"]').click()
            page.wait_for_selector("#reminders-view:visible")
            page.locator("#reminder-text").fill("one reminder")
            page.locator("#reminder-time").evaluate(
                """el => {
                  const value = new Date(Date.now() + 3600000);
                  const pad = number => String(number).padStart(2, '0');
                  el.value = `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
                }"""
            )
            page.locator("#reminder-add-btn").click()
            page.wait_for_timeout(500)
            assert len(reminder_requests) == 1, reminder_requests
            reminder_rows = page.locator("#reminder-list > [data-id]").count()
            assert reminder_rows == 1, {
                "rows": reminder_rows,
                "html": page.locator("#reminder-list").inner_html(),
            }
            assert page.locator("body").get_attribute("data-space") == "aide"
            if width < 700:
                page.locator("#sidebar-toggle-btn").click()
                page.wait_for_selector("body:not(.sidebar-hidden)")
            assert page.locator("#proactive-view").count() == 0
            page.locator("#new-chat-btn").click()
            page.wait_for_selector("#chat:visible")
            assert page.locator("body").get_attribute("data-space") == "aide"
            assert page.locator("#aide-current-context").inner_text().strip() == "new task"
            assert (
                page.locator(".aide-context-folder").evaluate("el => getComputedStyle(el).display")
                == "none"
            )
            assert page.locator("#perm-mode-btn").inner_text().strip() == "auto mode"
            if width >= 700:
                page.locator("#aide-model-choice").click()
                page.locator(
                    '#model-list .model-row[data-ep="deepseek-local"][data-model="deepseek-v4-pro"]'
                ).click()
                assert page.locator("#aide-model-choice-label").inner_text().strip() == "v4 pro"
                assert page.locator("#aide-model-choice").get_attribute("title") == (
                    "deepseek-v4-pro · local deepseek"
                )
                assert page.locator("#aide-model-choice").get_attribute("aria-label") == (
                    "model deepseek-v4-pro, provider local deepseek"
                )
                assert page.locator("#aide-model-choice-logo svg").evaluate(
                    """svg => {
                      const box = svg.getBoundingClientRect();
                      return svg.getAttribute('viewBox') === '0 0 24 24'
                        && svg.querySelectorAll('path').length > 0
                        && Math.abs(box.width - box.height) < 0.1
                        && box.width === 14;
                    }"""
                )
                page.locator("#aide-model-choice").click()
                page.locator(
                    '#model-list .model-row[data-ep="context-endpoint"][data-model="context-model"]'
                ).click()
                assert page.locator("#aide-model-choice-label").inner_text().strip() == (
                    "context model"
                )
            assert page.locator("#aide-new-context").is_visible()
            assert page.locator("#aide-project-context").inner_text().strip() == "tasks"
            assert not page.locator("#aide-branch-context").is_visible()
            assert "local" not in page.locator("#aide-new-context").inner_text().splitlines()
            assert page.locator("#aide-new-context").evaluate(
                "el => el.getBoundingClientRect().right <= document.querySelector('#composer-outer').getBoundingClientRect().right + 1"
            )
            page.locator("#more-tools-btn").click()
            page.wait_for_selector("#_more_tools_menu")
            assert page.locator("#_more_tools_menu").inner_text().splitlines() == [
                "upload file",
                "link an app",
            ]
            assert page.locator("#_more_tools_menu").locator('text="connections"').count() == 0
            page.locator('#_more_tools_menu [data-tool="app"]').click()
            page.wait_for_selector("#_more_tools_menu .app-link-menu")
            page.locator("#_more_tools_menu .app-link-menu button").first.click()
            page.wait_for_function(
                "() => document.querySelector('#composer-ta')?.value.includes('@')"
            )
            assert page.locator("#composer-ta").input_value().startswith("@")
            page.locator("#composer-ta").fill("")
            if width < 700:
                page.mouse.click(width - 12, height // 2)
                page.wait_for_selector("body.sidebar-hidden")
            composer_height = page.locator(".composer-box").bounding_box()["height"]
            page.locator("#file-input-hidden").set_input_files(
                [
                    {
                        "name": "layout.png",
                        "mimeType": "image/png",
                        "buffer": base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                        ),
                    },
                    {
                        "name": "notes.md",
                        "mimeType": "text/markdown",
                        "buffer": b"# layout notes\n",
                    },
                ]
            )
            page.wait_for_selector("#attachment-chips .attach-chip:nth-child(2)")
            assert page.locator(".composer-box > #attachment-chips").count() == 1
            assert page.locator("#attachment-preview").count() == 0
            assert page.locator("#attachment-chips .attach-chip-thumb").count() == 1
            assert page.locator(".composer-box").bounding_box()["height"] > composer_height + 40
            card_tops = page.locator("#attachment-chips .attach-chip").evaluate_all(
                "els => els.map(el => Math.round(el.getBoundingClientRect().top))"
            )
            assert len(set(card_tops)) == 1
            page.screenshot(path=f"/tmp/alles-aide-attachments-{label}.png", full_page=True)
            page.locator("#attachment-chips .attach-remove").first.click()
            page.locator("#attachment-chips .attach-remove").first.click()
            page.wait_for_selector("#attachment-chips", state="hidden")
            page.locator("#composer-ta").evaluate(
                """composer => {
                  const bytes = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='), value => value.charCodeAt(0));
                  const transfer = new DataTransfer();
                  transfer.items.add(new File([bytes], 'pasted.png', {type: 'image/png'}));
                  composer.dispatchEvent(new ClipboardEvent('paste', {
                    bubbles: true,
                    cancelable: true,
                    clipboardData: transfer,
                  }));
                }"""
            )
            page.wait_for_selector('#attachment-chips .attach-chip:has-text("pasted.png")')
            assert page.locator("#attachment-chips .attach-chip-thumb").count() == 1
            page.locator("#attachment-chips .attach-remove").click()
            page.wait_for_selector("#attachment-chips", state="hidden")
            mixed_not_prevented = page.locator("#composer-ta").evaluate(
                """composer => {
                  const bytes = new Uint8Array([1, 2, 3]);
                  const transfer = new DataTransfer();
                  transfer.items.add('pasted words', 'text/plain');
                  transfer.items.add(new File([bytes], 'mixed-paste.png', {type: 'image/png'}));
                  const event = new ClipboardEvent('paste', {
                    bubbles: true,
                    cancelable: true,
                    clipboardData: transfer,
                  });
                  composer.dispatchEvent(event);
                  return !event.defaultPrevented;
                }"""
            )
            assert mixed_not_prevented
            page.wait_for_selector('#attachment-chips .attach-chip:has-text("mixed-paste.png")')
            page.locator("#attachment-chips .attach-remove").click()
            page.wait_for_selector("#attachment-chips", state="hidden")

            page.evaluate(
                """() => {
                  window.__phase6RealXHR = window.XMLHttpRequest;
                  let attempt = 0;
                  window.XMLHttpRequest = class Phase6UploadXHR {
                    constructor() {
                      this.upload = new EventTarget();
                      this.listeners = new Map();
                      this.status = 0;
                      this.response = null;
                    }
                    open() {}
                    addEventListener(name, listener) { this.listeners.set(name, listener); }
                    emit(name) { this.listeners.get(name)?.call(this, new Event(name)); }
                    send() {
                      attempt += 1;
                      const current = attempt;
                      setTimeout(() => this.upload.dispatchEvent(new ProgressEvent('progress', {
                        lengthComputable: true,
                        loaded: 1,
                        total: 2,
                      })), 50);
                      setTimeout(() => {
                        this.status = current === 1 ? 500 : 200;
                        this.response = current === 1 ? {} : {
                          id: 'pending-retried-upload',
                          name: 'retry.png',
                          type: 'image/png',
                          size: 68,
                        };
                        this.emit('load');
                      }, 300);
                    }
                    abort() { this.emit('abort'); }
                  };
                }"""
            )
            page.locator("#file-input-hidden").set_input_files(
                {
                    "name": "retry.png",
                    "mimeType": "image/png",
                    "buffer": base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                    ),
                }
            )
            page.wait_for_selector(
                '#attachment-chips .attach-chip.uploading:has-text("uploading 50%")'
            )
            retry_chip = page.locator('#attachment-chips .attach-chip:has-text("retry.png")')
            assert retry_chip.locator(".attach-name").inner_text() == "retry.png"
            assert retry_chip.locator(".attach-thumb").evaluate(
                "el => el.getBoundingClientRect().width === 38 && el.getBoundingClientRect().height === 38"
            )
            page.wait_for_selector('#attachment-chips .attach-chip.failed:has-text("failed")')
            assert retry_chip.locator(".attach-retry").is_visible()
            retry_chip.locator(".attach-retry").click()
            page.wait_for_selector(
                '#attachment-chips .attach-chip.uploading:has-text("uploading 50%")'
            )
            page.wait_for_selector(
                '#attachment-chips .attach-chip:not(.uploading):not(.failed):has-text("68b")'
            )
            retry_chip = page.locator('#attachment-chips .attach-chip:has-text("retry.png")')
            assert retry_chip.locator(".attach-retry").count() == 0
            retry_chip.locator(".attach-remove").click()
            page.wait_for_selector("#attachment-chips", state="hidden")
            page.evaluate(
                """() => {
                  window.XMLHttpRequest = window.__phase6RealXHR;
                  delete window.__phase6RealXHR;
                }"""
            )
            if width < 700:
                page.locator("#sidebar-toggle-btn").click()
                page.wait_for_selector("body:not(.sidebar-hidden)")
            expected_icon_size = 44 if width < 700 else 32
            for selector in ("#sidebar-toggle-btn", "#aide-work-panel-toggle"):
                assert page.locator(selector).evaluate(
                    "(el, size) => el.getBoundingClientRect().width === size && el.getBoundingClientRect().height === size",
                    expected_icon_size,
                )

            head_bottom = page.locator(".sidebar-head").evaluate("el => el.getBoundingClientRect().bottom")
            search_box = page.locator(".search-wrap").evaluate("el => el.getBoundingClientRect().toJSON()")
            nav_top = page.locator(".sidebar-nav").evaluate("el => el.getBoundingClientRect().top")
            assert search_box["top"] >= head_bottom
            assert nav_top >= search_box["bottom"]
            assert page.locator("#aide-home-button").is_visible()
            page.locator("#session-search").click()
            assert page.locator("#session-search").evaluate("el => el === document.activeElement")
            page.locator("#session-search").fill("saved")
            page.keyboard.press("Escape")
            assert page.locator("#session-search").input_value() == ""
            assert page.locator(".sidebar-nav").evaluate(
                "(el, top) => Math.abs(el.getBoundingClientRect().top - top) < 1", nav_top
            )

            if width < 700:
                page.mouse.click(width - 12, height // 2)
                page.wait_for_selector("body.sidebar-hidden")

            page.locator("#aide-project-context").click()
            assert page.locator("#aide-project-context-menu").is_visible()
            assert page.locator(
                "#aide-project-context-menu [role=menuitemradio]"
            ).all_inner_texts() == [
                "tasks",
                "saved",
            ]
            page.locator('#aide-project-context-menu [data-project-id="project-saved"]').click()
            assert page.locator("#aide-project-context").inner_text().strip() == "saved"
            assert page.evaluate("window._pendingProjectId") == "project-saved"
            page.wait_for_selector("#aide-branch-context:visible")
            assert page.locator("#aide-branch-context-label").inner_text().strip() == "main"
            page.locator("#aide-branch-context").click()
            assert page.locator(
                "#aide-branch-context-menu [role=menuitemradio]"
            ).all_inner_texts() == [
                "main",
                "dev-afterlife",
            ]
            assert page.locator("#aide-branch-context-menu").evaluate(
                """menu => {
                  const anchor = document.querySelector('#aide-branch-context').getBoundingClientRect();
                  const box = menu.getBoundingClientRect();
                  return Math.abs(box.left - anchor.left) <= 1 && box.bottom <= anchor.top - 2;
                }"""
            )
            page.locator('#aide-branch-context-menu [data-branch="dev-afterlife"]').click()
            page.wait_for_function(
                "document.querySelector('#aide-branch-context-label')?.textContent === 'dev-afterlife'"
            )
            branch_state["reject_next"] = True
            page.locator("#aide-branch-context").click()
            page.locator('#aide-branch-context-menu [data-branch="main"]').click()
            page.wait_for_selector("#aide-branch-context-menu", state="hidden")
            conflict_toast = page.locator("#toast-container .toast.error").last
            assert conflict_toast.inner_text() == (
                "this branch would overwrite your changes. commit or stash them first."
            )
            assert conflict_toast.evaluate("el => el.getBoundingClientRect().width <= 448")
            errors[:] = [
                error
                for error in errors
                if error
                != "Failed to load resource: the server responded with a status of 409 (Conflict)"
            ]
            page.locator("#aide-project-context").click()
            page.keyboard.press("Escape")
            assert not page.locator("#aide-project-context-menu").is_visible()
            page.locator("#aide-project-context").click()
            page.locator(".aide-project-add-folder").click()
            page.wait_for_selector("#aide-project-context-menu.folder-mode")
            assert page.locator(".aide-folder-path input").input_value() == "/workspace"
            assert page.locator("#aide-project-context-menu").evaluate(
                "el => el.getBoundingClientRect().top >= 0 && el.getBoundingClientRect().bottom <= innerHeight"
            )
            page.screenshot(path=f"/tmp/alles-aide-folder-{label}.png", full_page=True)
            page.locator('.aide-folder-row[data-folder-path="/workspace/alles"]').click()
            page.wait_for_function(
                "document.querySelector('.aide-folder-path input')?.value === '/workspace/alles'"
            )
            page.locator(".aide-folder-use").click()
            page.wait_for_function(
                "document.querySelector('#aide-project-context-label')?.textContent === 'alles'"
            )
            assert page.evaluate("window._pendingProjectId") == ""
            assert page.evaluate("window._pendingWorkingDir") == "/workspace/alles"
            page.evaluate(
                """async () => {
                  const sessions = await import('/static/js/sessions.js?v=241');
                  await sessions.createSession('context-model', 'context-endpoint');
                }"""
            )
            assert session_requests[-1]["project_id"] == ""
            assert session_requests[-1]["working_dir"] == "/workspace/alles"

            page.locator("#perm-mode-btn").click()
            assert page.locator("#perm-menu button").all_inner_texts() == [
                "full access\nno approval; host shell is unrestricted unless sandboxed",
                "auto mode\nhandle safe work; ask at real risk",
                "ask for approval\nask before each change",
                "plan\nread-only — just make a plan, change nothing",
            ]
            page.locator('#perm-menu [data-v="full_access"]').click()
            assert page.locator("#perm-mode-btn").inner_text().strip() == "full access"
            assert page.locator("#perm-mode-btn").evaluate(
                """el => {
                  const probe = document.createElement('span');
                  probe.style.color = 'var(--signal)';
                  document.body.append(probe);
                  const matches = getComputedStyle(el).color === getComputedStyle(probe).color;
                  const accent = document.createElement('span');
                  accent.style.color = 'var(--accent)';
                  document.body.append(accent);
                  const differsFromPurple = getComputedStyle(el).color !== getComputedStyle(accent).color;
                  probe.remove();
                  accent.remove();
                  return matches && differsFromPurple;
                }"""
            )
            page.locator("#perm-mode-btn").click()
            page.locator('#perm-menu [data-v="full_auto"]').click()
            assert page.locator("#perm-mode-btn").inner_text().strip() == "auto mode"
            assert page.locator("#perm-mode-btn").evaluate(
                """el => {
                  const probe = document.createElement('span');
                  probe.style.color = 'var(--accent)';
                  document.body.append(probe);
                  const matches = getComputedStyle(el).color === getComputedStyle(probe).color;
                  probe.remove();
                  return matches;
                }"""
            )
            page.locator("#perm-mode-btn").click()
            page.locator('#perm-menu [data-v="plan"]').click()
            assert page.locator("#perm-mode-btn").inner_text().strip() == "plan"
            assert page.locator("#perm-mode-btn").evaluate(
                """el => {
                  const probe = document.createElement('span');
                  probe.style.color = 'var(--accent)';
                  document.body.append(probe);
                  const differs = getComputedStyle(el).color !== getComputedStyle(probe).color;
                  probe.remove();
                  return differs;
                }"""
            )
            page.locator("#perm-mode-btn").click()
            page.locator('#perm-menu [data-v="approve"]').click()

            page.locator("#effort-btn").click()
            effort_menu = page.locator("#perm-menu.effort-menu")
            assert effort_menu.get_attribute("role") == "menu"
            effort_items = effort_menu.locator('button[role="menuitemradio"]')
            assert effort_items.count() == 10
            assert effort_items.all_inner_texts() == [
                "low\nquick & minimal — fewest turns",
                "medium\nbalanced (default)",
                "high\nthorough — more turns",
                "xhigh\nvery thorough",
                "max\nmaximum turns",
                "deep work\n48 turns · thorough checks · bounded helpers",
                "custom\n1–64 turns · your verification and helper rules",
                "automatic\nuse the model and effort default",
                "on\nask the model to reason",
                "off\nkeep model reasoning disabled",
            ]
            effort_metrics = effort_menu.evaluate(
                """el => {
                  const box = el.getBoundingClientRect();
                  const style = getComputedStyle(el);
                  const head = el.querySelector('.perm-menu-head').getBoundingClientRect();
                  const first = el.querySelector('.perm-menu-item').getBoundingClientRect();
                  const second = el.querySelectorAll('.perm-menu-item')[1].getBoundingClientRect();
                  const anchor = document.querySelector('#effort-btn').getBoundingClientRect();
                  return {
                    viewport: [innerWidth, innerHeight],
                    box: [box.left, box.top, box.right, box.bottom],
                    anchorTop: anchor.top,
                    paddingLeft: parseFloat(style.paddingLeft),
                    headInset: [head.left - box.left, head.top - box.top],
                    headGap: first.top - head.bottom,
                    itemGap: second.top - first.bottom,
                  };
                }"""
            )
            assert (
                effort_metrics["box"][0] >= 10
                and effort_metrics["box"][2] <= effort_metrics["viewport"][0] - 10
                and effort_metrics["box"][1] >= 10
                and effort_metrics["box"][3] <= effort_metrics["viewport"][1] - 10
                and effort_metrics["box"][3] <= effort_metrics["anchorTop"] - 8
                and effort_metrics["paddingLeft"] >= 6
                and min(effort_metrics["headInset"]) > 0
                and effort_metrics["headGap"] >= 4
                and effort_metrics["itemGap"] >= 2
            ), effort_metrics
            assert effort_items.nth(1).get_attribute("aria-checked") == "true"
            page.screenshot(path=f"/tmp/alles-aide-effort-{label}.png", full_page=True)
            page.keyboard.press("ArrowDown")
            assert effort_items.nth(2).evaluate("el => el === document.activeElement")
            page.keyboard.press("Enter")
            assert page.locator("#effort-btn").inner_text().strip() == "high"

            page.locator("#composer-ta").fill("confirm the selected project")
            page.locator("#send-btn").click()
            page.wait_for_selector("#messages .ai-content")
            page.wait_for_timeout(200)
            assert not page.locator("#stop-btn").evaluate(
                "el => el.classList.contains('visible')"
            ), {"errors": errors, "chat_requests": chat_requests}
            assert (
                page.locator("#messages .ai-content").last.inner_text() == "project context ready"
            )
            assert session_requests[-1]["project_id"] == ""
            assert session_requests[-1]["working_dir"] == "/workspace/alles"
            assert chat_requests[-1]["mode"] == "agent"
            assert chat_requests[-1]["permission_mode"] == "approve"
            assert chat_requests[-1]["effort"] == "high"

            page.locator("#more-tools-btn").click()
            assert page.locator("#_more_tools_menu").is_visible()
            assert page.locator("#_more_tools_menu button").all_inner_texts() == [
                "upload file",
                "link an app",
            ]
            page.locator('#_more_tools_menu [data-tool="app"]').click()
            page.wait_for_selector("#_more_tools_menu .app-link-menu")
            assert page.locator('#_more_tools_menu [data-app-link="plan"]').inner_text() == "@plan"
            assert page.locator('#_more_tools_menu [data-app-link="calendar"]').count() == 0
            page.locator('#_more_tools_menu [data-app-link="plan"]').click()
            assert page.locator("#composer-ta").input_value() == "@plan "
            assert not page.locator("#_more_tools_menu").is_visible()
            page.locator("#composer-ta").fill("")

            for message_count in (3, 5, 20):
                page.evaluate(
                    """count => {
                      const messages = document.querySelector('#messages');
                      messages.style.display = 'flex';
                      messages.replaceChildren(...Array.from({length: count}, (_, i) => {
                        const row = document.createElement('div');
                        row.className = 'msg-row';
                        row.dataset.msgId = `rail-${count}-${i}`;
                        row.innerHTML = `<div class="user-wrap"><div class="user-bubble">message ${i + 1}</div></div>`;
                        return row;
                      }));
                    }""",
                    message_count,
                )
                page.wait_for_function(
                    "count => document.querySelectorAll('#aide-message-rail-track button').length === count",
                    arg=message_count,
                )
                rail_ticks = page.locator("#aide-message-rail-track button")
                assert rail_ticks.count() == message_count
                assert page.locator("#aide-message-rail-track button.current").count() == 1
                keys_before = rail_ticks.evaluate_all(
                    "els => els.map((el, index) => { el._railProbe = index + 1; return el.dataset.messageKey; })"
                )
                page.evaluate(
                    """() => {
                      const answer = document.createElement('div');
                      answer.className = 'msg-row';
                      answer.innerHTML = '<div class="ai-content">streaming</div>';
                      document.querySelector('#messages').append(answer);
                      answer.querySelector('.ai-content').append(' answer');
                    }"""
                )
                page.wait_for_timeout(80)
                assert (
                    rail_ticks.evaluate_all("els => els.map(el => el.dataset.messageKey)")
                    == keys_before
                )
                assert rail_ticks.evaluate_all("els => els.map(el => el._railProbe)") == list(
                    range(1, message_count + 1)
                )
                idle_transforms = rail_ticks.evaluate_all(
                    "els => els.map(el => getComputedStyle(el, '::before').transform)"
                )
                assert len(set(idle_transforms)) == 1

            rail_ticks = page.locator("#aide-message-rail-track button")
            idle_transforms = rail_ticks.evaluate_all(
                "els => els.map(el => getComputedStyle(el, '::before').transform)"
            )
            assert page.locator("#aide-message-rail").evaluate(
                "el => Math.abs((el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2) - innerHeight / 2) < 3"
            )
            target_tick = rail_ticks.last
            box = target_tick.bounding_box()
            page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(140)
            assert (
                target_tick.evaluate("el => getComputedStyle(el, '::before').transform")
                != idle_transforms[-1]
            )
            page.mouse.move(width - 10, 10)
            page.wait_for_timeout(140)
            assert (
                len(
                    set(
                        rail_ticks.evaluate_all(
                            "els => els.map(el => getComputedStyle(el, '::before').transform)"
                        )
                    )
                )
                == 1
            )

            page.evaluate(
                """
                async () => {
                  const {appendAiMsg} = await import('/static/js/sessions.js?v=235');
                  appendAiMsg('answer', 'thinking first', [{type:'tool', name:'check'}]);
                }
                """
            )
            answer_body = page.locator("#messages .ai-body").last
            children = answer_body.locator(":scope > *")
            classes = children.evaluate_all("els => els.map(el => el.className)")
            assert classes.index("ai-content") < classes.index("thinking-block")
            assert classes.index("ai-content") < next(
                i for i, value in enumerate(classes) if "agent-steps" in value
            )

            page.locator("#aide-work-panel-toggle").click()
            page.wait_for_selector("#aide-work-panel:not([hidden])")
            assert (
                page.locator("#aide-work-panel").evaluate(
                    "el => getComputedStyle(el).backgroundColor"
                )
                != "rgb(16, 16, 16)"
            )
            assert page.locator("#aide-task-tools [data-aide-tool]").count() == 5
            page.locator('[data-aide-tool="terminal"]').click()
            assert page.locator("#aide-terminal").is_visible()
            assert not page.locator("#aide-task-tools").is_visible()
            page.wait_for_selector("#aide-terminal-mount .xterm", state="visible")
            assert page.locator("#aide-terminal-mount .xterm").is_visible()
            page.locator("#aide-terminal-mount").click()
            page.keyboard.type("pwd")
            page.keyboard.press("Enter")
            page.wait_for_function(
                "document.querySelector('#aide-terminal-mount .xterm-rows')?.textContent.includes('/tmp/alles-test')"
            )
            assert any(event.get("type") == "resize" for event in terminal_messages)
            assert "pwd" in "".join(
                event.get("data", "") for event in terminal_messages if event.get("type") == "input"
            )
            page.locator("#aide-work-panel-back").click()
            assert page.locator("#aide-task-tools").is_visible()
            page.locator("#aide-work-panel-close").click()
            assert not page.locator("#aide-work-panel").is_visible()

            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.screenshot(path=f"/tmp/alles-aide-{label}.png", full_page=True)

            page.locator("#perm-mode-btn").click()
            page.locator('#perm-menu [data-v="plan"]').click()
            page.reload(wait_until="networkidle")
            if not page.locator("#chat").is_visible():
                page.locator('[data-today-destination="chat"]').click()
            page.wait_for_selector("#chat:visible")
            assert page.locator("#perm-mode-btn").inner_text().strip() == "plan"
            assert page.locator("#effort-btn").inner_text().strip() == "high"
            assert page.locator("#model-label").inner_text().strip() == "context model"

            # Aide's own subdomain must boot into a usable new task immediately.  This
            # catches startup-order bugs where the project context only appears after
            # pressing "new task" a second time.
            page.goto(f"http://aide.localhost:{PORT}/", wait_until="domcontentloaded")
            page.wait_for_selector("#composer-ta:visible")
            assert page.locator("body").get_attribute("data-space") == "aide"
            assert page.locator("#aide-new-context").is_visible()
            assert page.locator("#aide-project-context").inner_text().strip() == "tasks"

            if width >= 700:
                page.locator("#aide-work-panel-toggle").click()
                page.locator('[data-aide-tool="browser"]').click()
                page.wait_for_url(f"http://andromeda.localhost:{PORT}/")
            context.close()
        browser.close()

    if errors:
        raise AssertionError("browser console errors:\n" + "\n".join(errors))
    print("aide shell browser gate passed")


if __name__ == "__main__":
    run()
