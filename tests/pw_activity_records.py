"""Activity opens exact documents and the saved conversation behind an agent run."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    from core.database import Message, SessionLocal
    from services import agent_state
    from services.appearance import from_legacy

    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 768, 390, 320]:
            for theme in ["dark", "light"]:
                label = f"{width}-{theme}"
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    has_touch=width <= 390,
                    reduced_motion="reduce" if theme == "dark" else "no-preference",
                )
                errors, console, external = [], [], []

                def local_only(route):
                    if urlparse(route.request.url).netloc == urlparse(base).netloc:
                        return route.continue_()
                    external.append(route.request.url)
                    route.abort()

                context.route("**/*", local_only)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(6000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                steps = []
                row = {
                    "scenario_id": "activity.exact-record",
                    "profile": label,
                    "status": "failed",
                    "steps": steps,
                }
                rows.append(row)

                def activity():
                    page.evaluate("window._navigateTo('activity')")
                    expect(page.locator("#activity-view")).to_be_visible()
                    expect(page.locator(".activity-row").first).to_be_visible()

                def open_activity(identity):
                    target = page.locator(f'.activity-row[data-id="{identity}"]')
                    expect(target).to_be_visible()
                    if width <= 390:
                        target.tap()
                    else:
                        target.focus()
                        page.keyboard.press("Enter")

                def document(path, text):
                    expect(page.locator("#docs-workbench-view")).to_have_attribute(
                        "aria-busy", "false"
                    )
                    expect(page.locator("#docs-workbench-view > .specialist-state")).to_be_hidden()
                    expect(page.locator("#wiki-path")).to_have_text(path)
                    expect(page.locator("#wiki-current")).to_have_text(Path(path).stem)
                    expect(page.locator("#wiki-preview")).to_have_text(text)
                    assert parse_qs(urlparse(page.url).query)["record"] == [path]
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

                try:
                    assert context.request.post(base + "/api/setup/dismiss").ok
                    assert context.request.put(
                        base + "/api/appearance", data=from_legacy(theme, None)
                    ).ok
                    original = f"original-{label}.md"
                    first = f"cooking-{label}/meal #2 & 文.md"
                    second = f"other-{label}/meal #2 & 文.md"
                    for path, content in [
                        (original, "original document"),
                        (first, "meal instructions"),
                        (second, "different same-name document"),
                    ]:
                        response = context.request.post(
                            base + "/api/vault-md/file", data={"path": path, "content": content}
                        )
                        assert response.ok, response.text()
                    page.goto(base + "/?view=wiki&doc=" + original, wait_until="networkidle")
                    expect(page.locator("#wiki-preview")).to_have_text("original document")
                    for path, text in [
                        (first, "meal instructions"),
                        (second, "different same-name document"),
                    ]:
                        activity()
                        open_activity(path)
                        document(path, text)
                        page.reload(wait_until="networkidle")
                        document(path, text)
                        page.go_back(wait_until="networkidle")
                        expect(page.locator("#activity-view")).to_be_visible()
                        page.go_forward(wait_until="networkidle")
                        document(path, text)
                    steps.append(
                        "two same-named nested documents keep exact path, heading and body across reload/back/forward"
                    )
                    page.screenshot(path=str(out / f"{label}-document.png"))

                    # Manual selection and rename must not leave the activity URL
                    # pointing at the previously opened record.
                    if width <= 760:
                        page.locator("#wiki-tree-toggle").click()
                    search = page.locator("#wiki-search")
                    search.fill(Path(original).stem)
                    target = page.locator("#wiki-tree .docs-search-hit").filter(
                        has_text=Path(original).stem
                    )
                    target.click()
                    document(original, "original document")
                    page.reload(wait_until="networkidle")
                    document(original, "original document")
                    page.locator("#wiki-more-btn").click()
                    page.locator("#wiki-rename-btn").click()
                    page.locator("#docs-dialog-input").fill("renamed-" + label)
                    page.locator('#docs-dialog-actions [data-dialog-action="confirm"]').click()
                    renamed = "renamed-" + label + ".md"
                    document(renamed, "original document")
                    page.reload(wait_until="networkidle")
                    document(renamed, "original document")
                    steps.append("manual selection and rename update the linked record")

                    activity()
                    assert context.request.delete(
                        base + "/api/vault-md/file", params={"path": first}
                    ).ok
                    missing = context.request.get(
                        base + "/api/vault-md/file", params={"path": first}
                    )
                    assert missing.status == 200 and missing.json()["exists"] is False
                    open_activity(first)
                    expect(
                        page.locator("#toast-container .toast.error").filter(has_text=first)
                    ).to_be_visible()
                    expect(page.locator("#wiki-path")).to_have_text(renamed)
                    steps.append(
                        "deleted document identifies the failed path and preserves the previous document"
                    )

                    jobs = []
                    for suffix in ["one", "two"]:
                        response = context.request.post(
                            base + "/api/sessions",
                            data={"name": f"failed activity {label} {suffix}"},
                        )
                        assert response.ok, response.text()
                        sid = response.json()["id"]
                        job = agent_state.start_run(sid, "synthetic-local", 2)
                        agent_state.finish_run(job["id"], "error")
                        with SessionLocal() as db:
                            message = Message(
                                session_id=sid,
                                role="assistant",
                                content=f"synthetic failed reply {suffix}",
                                meta=json.dumps({"agent_run_id": job["id"]}),
                            )
                            db.add(message)
                            db.commit()
                            mid = message.id
                        jobs.append((job["id"], sid, mid, suffix))
                    for rid, sid, mid, suffix in jobs:
                        activity()
                        open_activity(rid)
                        page.wait_for_function("(id) => window._currentSession?.id === id", arg=sid)
                        message = page.locator(f'.msg-row[data-msg-id="{mid}"]')
                        expect(message).to_contain_text("synthetic failed reply " + suffix)
                        expect(message).to_be_focused()
                        assert parse_qs(urlparse(page.url).query)["message"] == [mid]
                        page.reload(wait_until="networkidle")
                        page.wait_for_function("(id) => window._currentSession?.id === id", arg=sid)
                        expect(message).to_be_focused()
                    steps.append(
                        "two failed runs select their actual saved session and matching reply after reload"
                    )
                    page.screenshot(path=str(out / f"{label}-agent.png"))

                    rid, sid, mid, suffix = jobs[0]
                    activity()
                    held = []
                    pattern = base + "/api/agent/runs/" + rid
                    page.route(pattern, lambda route: held.append(route))
                    open_activity(rid)
                    page.wait_for_timeout(50)
                    assert len(held) == 1
                    page.evaluate("window._navigateTo('today')")
                    response = held[0].fetch()
                    held[0].fulfill(response=response)
                    page.unroute(pattern)
                    page.wait_for_timeout(150)
                    expect(page.locator("#today-view")).to_be_visible()
                    steps.append("late run read cannot navigate after leaving activity")

                    activity()
                    count = len(console)
                    page.route(
                        pattern,
                        lambda route: route.fulfill(
                            status=404, json={"detail": "synthetic unavailable run"}
                        ),
                    )
                    open_activity(rid)
                    expect(page.locator("#toast-container .toast.error").last).to_contain_text(
                        "this run is no longer available"
                    )
                    expect(page.locator("#activity-view")).to_be_visible()
                    page.unroute(pattern)
                    assert all("404" in error for error in console[count:]), console[count:]
                    del console[count:]
                    open_activity(rid)
                    page.wait_for_function("(id) => window._currentSession?.id === id", arg=sid)
                    steps.append("unavailable run stays in activity and selecting again recovers")
                    assert not errors and not console and not external, (errors, console, external)
                    row.update(
                        status="passed",
                        page_errors=errors,
                        console_errors=console,
                        external_attempts=external,
                    )
                except Exception as error:
                    row.update(
                        error=str(error),
                        traceback=traceback.format_exc(),
                        page_errors=errors,
                        console_errors=console,
                        external_attempts=external,
                    )
                    page.screenshot(path=str(out / f"{label}-failed.png"))
                finally:
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        browser.close()
    assert all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
