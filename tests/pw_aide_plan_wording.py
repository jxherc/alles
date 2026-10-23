"""Owned saved reply -> reviewed Plan task, without a model or external service."""

import base64
import hashlib
import json
import os
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

from services.appearance import from_legacy


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    require_server_ownership(base, run_id)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert data != Path("data").resolve() and (data / ".alles-test-owner").read_text() == run_id
    from core.database import DB_PATH, Message, Session, SessionLocal

    assert Path(DB_PATH).resolve().is_relative_to(data)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    origin = urlsplit(base)
    rows = []
    profiles = [(w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme, zoom in profiles:
            profile = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = dict(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
                timezone_id="UTC",
            )
            if zoom:
                root = data / profile
                extension = root / "extension"
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
                    root / "browser",
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
            page = context.new_page()
            page.set_default_timeout(7000)
            errors, console, external, writes = [], [], [], []

            def boundary(route):
                u = urlsplit(route.request.url)
                if (u.scheme, u.netloc) == (origin.scheme, origin.netloc):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort("blockedbyclient")

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda ws: (external.append(ws.url), ws.close()))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            api = context.request
            assert api.post(base + "/api/setup/dismiss").ok
            assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
            assert api.patch(base + "/api/settings", data={"language": "en", "timezone": "UTC"}).ok
            answer = (
                f"owned next step {profile}\n\nprepare the owned checklist; keep résumé and 秋季."
            )
            with SessionLocal() as db:
                source = Session(name="new task")
                db.add(source)
                db.flush()
                msg = Message(
                    session_id=source.id,
                    role="assistant",
                    content=answer,
                    meta=json.dumps(
                        {
                            "context_provenance": {"reply_id": "owned-source-" + profile},
                            "source_citations": {"status": "uncited"},
                        }
                    ),
                )
                db.add(msg)
                source.message_count = 1
                db.commit()
                sid, mid = source.id, msg.id
            row = dict(scenario_id="aide.plan-wording.recovery", profile=profile, status="failed")
            rows.append(row)
            mode = "fail"

            def accepted(route):
                nonlocal mode
                if route.request.method != "POST":
                    route.continue_()
                    return
                writes.append(route.request.post_data_json)
                if mode == "fail":
                    mode = "pass"
                    route.fulfill(status=503, json={"detail": "owned acceptance interruption"})
                elif mode == "lost":
                    mode = "pass"
                    response = route.fetch()
                    assert response.ok
                    route.abort("failed")
                else:
                    route.continue_()

            page.route(base + "/api/tasks", accepted)

            def tasks():
                return (
                    api.get(base + "/api/tasks").json() + api.get(base + "/api/tasks/done").json()
                )

            def capture(state):
                path = output / f"{profile}-{state}.png"
                if zoom:
                    cdp = context.new_cdp_session(page)
                    blob = base64.b64decode(
                        cdp.send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )["data"]
                    )
                    cdp.detach()
                    assert struct.unpack("!II", blob[16:24]) == (1440, 900)
                    path.write_bytes(blob)
                else:
                    page.screenshot(path=str(path), full_page=True)

            def open_source():
                page.goto(base + "/?app=aide#" + sid, wait_until="networkidle")
                expect(page.locator("#aide-conversation-name")).to_have_text("new task")
                expect(page.locator("#aide-sidebar-toggle-label")).to_have_text("aide tasks")
                expect(page.locator("#new-chat-btn")).to_have_text("new aide task")
                expect(page.locator("#session-search")).to_have_attribute(
                    "aria-label", "search aide tasks…"
                )
                return page.locator(".ai-wrap").get_by_role("button", name="+plan task", exact=True)

            try:
                before = {t["id"] for t in tasks()}
                button = open_source()
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    assert (
                        worker.evaluate(
                            "async base=>{const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}",
                            base,
                        )
                        == 2
                    )
                    page.wait_for_function("innerWidth===720 && devicePixelRatio===2")
                    row["native_zoom"] = dict(factor=2, css_width=720, dpr=2)
                expect(button).to_have_attribute("title", "review this reply as a plan task")
                help_button = page.locator("#aide-help")
                help_button.press("Enter")
                help_dialog = page.locator("#aide-help-dialog")
                expect(help_dialog.locator('[data-help-guide="task"]')).to_contain_text(
                    "make a plan task from an aide reply"
                )
                expect(help_dialog.locator('[data-help-guide="task"]')).to_contain_text(
                    "+plan task"
                )
                capture("help")
                page.keyboard.press("Escape")
                expect(help_button).to_be_focused()
                # Explicit pending-source UI fixture; history/recovery and Plan writes are real local paths.
                page.locator(".ai-wrap").evaluate(
                    "(wrap,id)=>{wrap.pendingSourceReply=true;wrap.sourceReplyId=id}",
                    "owned-source-" + profile,
                )
                page.route(
                    base + "/api/sessions/" + sid + "/history",
                    lambda route: route.fulfill(
                        status=503, json={"detail": "owned source read interruption"}
                    ),
                    times=1,
                )
                button.press("Enter")
                expect(page.locator("#aide-task-recovery")).to_contain_text("try +plan task again")
                expect(button).to_have_text("+plan task")
                assert not writes and {t["id"] for t in tasks()} == before
                capture("source-retry")
                button.press("Enter")
                dialog = page.get_by_role("dialog", name="review task for plan", exact=True)
                expect(dialog).to_be_visible()
                expect(page.locator("#capture-notes")).to_have_value(answer)
                capture("review")
                page.keyboard.press("Escape")
                expect(dialog).to_be_hidden()
                expect(button).to_be_focused()
                assert not writes and {t["id"] for t in tasks()} == before
                button.press("Enter")
                title = "reviewed Plan result " + profile
                notes = answer + "\nreviewed details"
                page.locator("#capture-title").fill(title)
                page.locator("#capture-notes").fill(notes)
                page.locator("#capture-accept").press("Enter")
                expect(page.locator(".capture-status")).to_contain_text("will not add a duplicate")
                expect(page.locator("#capture-accept")).to_have_text("retry confirmation")
                assert {t["id"] for t in tasks()} == before
                capture("retry")
                page.locator("#capture-accept").press("Enter")
                expect(page.locator("#capture-open")).to_be_visible()
                assert len(writes) == 2 and writes[0] == writes[1]
                saved = [t for t in tasks() if t["id"] not in before]
                assert len(saved) == 1 and saved[0]["title"] == title and saved[0]["notes"] == notes
                saved = saved[0]
                assert saved["source"]["session_id"] == sid and saved["source"]["message_id"] == mid
                assert saved["source"]["excerpt"] == answer
                assert saved["source"]["fingerprint"] == hashlib.sha256(answer.encode()).hexdigest()
                page.locator("#capture-open").press("Enter")
                expect(page.locator("#te-title")).to_have_value(title)
                expect(page.locator("#te-notes")).to_have_value(notes)
                assert page.locator(".task-editor-ov").get_attribute("data-task-id") == saved["id"]
                capture("saved-plan")
                page.reload(wait_until="networkidle")
                expect(page.locator("#te-title")).to_have_value(title)
                page.locator("#te-source").press("Enter")
                page.wait_for_function("id=>window._currentSession?.id===id", arg=sid)
                expect(page.locator(f'.msg-row[data-msg-id="{mid}"]')).to_contain_text(
                    answer.splitlines()[0]
                )
                assert (
                    api.get(base + "/api/sessions/" + sid + "/history").json()["session"]["name"]
                    == "new task"
                )
                button = page.locator(".ai-wrap").get_by_role(
                    "button", name="+plan task", exact=True
                )
                # A new, explicit acceptance whose actual reply is lost still cannot duplicate on retry.
                before_lost = {t["id"] for t in tasks()}
                button.press("Enter")
                page.locator("#capture-title").fill("interrupted Plan result " + profile)
                mode = "lost"
                page.locator("#capture-accept").press("Enter")
                expect(page.locator("#capture-accept")).to_have_text("retry confirmation")
                page.reload(wait_until="networkidle")
                page.get_by_role("button", name="review pending capture", exact=True).press("Enter")
                expect(dialog).to_be_visible()
                page.locator("#capture-accept").press("Enter")
                expect(page.locator("#capture-open")).to_be_visible()
                assert writes[-2] == writes[-1]
                assert len([t for t in tasks() if t["id"] not in before_lost]) == 1
                page.locator("#capture-cancel").press("Enter")
                expect(dialog).to_be_hidden()
                capture("recovered-aide")
                # Exercise all real locale catalogues, including RTL, without renaming stored content.
                languages = []
                if (width, theme, zoom) in [(1440, "light", False), (390, "dark", False)]:
                    for lang in ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar"):
                        messages = json.loads(
                            (Path("static/locales") / (lang + ".json")).read_text()
                        )["messages"]
                        assert api.patch(base + "/api/settings", data={"language": lang}).ok
                        page.reload(wait_until="networkidle")
                        expect(page.locator("#new-chat-btn")).to_have_text(
                            messages["aide.new_task"]
                        )
                        expect(page.locator("#aide-sidebar-toggle-label")).to_have_text(
                            messages["aide.tasks"]
                        )
                        expect(page.locator("#aide-conversation-name")).to_have_text("new task")
                        expect(
                            page.locator(".ai-wrap").get_by_role(
                                "button", name=messages["aide.add_plan_task"], exact=True
                            )
                        ).to_be_attached()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        if width == 390:
                            bounds = page.locator("#aide-sidebar-toggle-label").bounding_box()
                            button_bounds = page.locator("#sidebar-toggle-btn").bounding_box()
                            assert bounds["height"] <= 14 and button_bounds["height"] >= 44
                            assert (
                                bounds["x"] >= button_bounds["x"]
                                and bounds["x"] + bounds["width"]
                                <= button_bounds["x"] + button_bounds["width"] + 1
                            )
                            assert (
                                page.locator("#aide-conversation-name").bounding_box()["height"]
                                <= 21
                            )
                        languages.append(lang)
                        if lang in ("ar", "zh-Hant"):
                            capture("locale-" + lang)
                    assert api.patch(base + "/api/settings", data={"language": "en"}).ok
                assert not errors and not external, (errors, external)
                unexpected = [
                    e
                    for e in console
                    if e
                    not in (
                        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                        "Failed to load resource: net::ERR_FAILED",
                    )
                ]
                assert not unexpected, unexpected
                row.update(
                    status="passed",
                    fixture="synthetic stored ORM reply; actual local Plan writes",
                    writes=writes,
                    source_id=sid,
                    message_id=mid,
                    saved=saved,
                    locale_checks=languages,
                    console_errors=console,
                    page_errors=errors,
                    external=external,
                )
            except Exception as e:
                row.update(
                    error=str(e),
                    traceback=traceback.format_exc(),
                    console_errors=console,
                    page_errors=errors,
                    external=external,
                )
                capture("failed")
            finally:
                page.unroute_all(behavior="ignoreErrors")
                context.close()
                (output / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert len(rows) == 8 and all(r["status"] == "passed" for r in rows), rows


if __name__ == "__main__":
    run()
