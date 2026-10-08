"""Compact sidebar exit, Docs navigation density and Library first actions."""

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


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390, 320]:
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
                    if urlsplit(route.request.url).netloc == urlsplit(base).netloc:
                        return route.continue_()
                    external.append(route.request.url)
                    route.abort()

                context.route("**/*", local_only)
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(7000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console.append(message.text) if message.type == "error" else None
                    ),
                )
                result = {
                    "scenario_id": "product.navigation-clarity",
                    "profile": label,
                    "status": "failed",
                }
                results.append(result)
                paths = []

                def document(path):
                    response = context.request.post(
                        base + "/api/vault-md/file",
                        data={"path": path, "content": "# " + path + "\nowned document"},
                    )
                    assert response.ok, response.text()
                    paths.append(path)

                def open_docs():
                    page.goto(base + "/?view=wiki", wait_until="networkidle")
                    toggle = page.locator("#wiki-tree-toggle")
                    if toggle.get_attribute("aria-expanded") == "false":
                        toggle.click()
                    expect(page.locator(".docs-nav-panel")).to_be_visible()

                try:
                    assert context.request.post(base + "/api/setup/dismiss").ok
                    assert context.request.put(
                        base + "/api/appearance", data=from_legacy(theme, None)
                    ).ok
                    page.goto(base + "/?view=chat", wait_until="networkidle")
                    trigger = page.locator("#sidebar-toggle-btn")
                    close = page.get_by_role("button", name="close sidebar", exact=True)
                    if width == 1440:
                        expect(close).to_be_hidden()
                        page.set_viewport_size({"width": 390, "height": 900})
                    expect(trigger).to_have_attribute("aria-expanded", "false")
                    trigger.press("Enter")
                    expect(close).to_be_visible()
                    close.click(trial=True)
                    close.focus()
                    expect(close).to_be_focused()
                    box = close.bounding_box()
                    assert box and box["width"] >= 44 and box["height"] >= 44
                    page.screenshot(path=str(out / f"{label}-sidebar.png"))
                    close.tap() if width <= 390 else close.press("Enter")
                    expect(trigger).to_have_attribute("aria-expanded", "false")
                    expect(trigger).to_be_focused()
                    trigger.press("Enter")
                    page.keyboard.press("Escape")
                    expect(trigger).to_be_focused()
                    expect(trigger).to_have_attribute("aria-expanded", "false")
                    trigger.press("Enter")
                    close.focus()
                    page.set_viewport_size({"width": 1440, "height": 900})
                    expect(close).to_be_hidden()
                    expect(trigger).to_be_focused()
                    page.set_viewport_size({"width": width, "height": 900})

                    document("alpha.md")
                    document("beta.md")
                    open_docs()
                    recent_section = page.locator("#docs-recent-section")
                    expect(recent_section).to_be_hidden()
                    expect(page.locator("#wiki-tree [data-file]")).to_have_count(2)
                    page.screenshot(path=str(out / f"{label}-small-docs.png"))
                    alpha = page.locator('#wiki-tree [data-file="alpha.md"]')
                    expect(alpha).to_be_visible()
                    alpha.tap() if width <= 390 else alpha.press("Enter")
                    expect(page.locator("#wiki-current")).to_have_text("alpha")
                    for path in ["gamma.md", "delta.md", "epsilon.md"]:
                        document(path)
                    open_docs()
                    expect(recent_section).to_be_visible()
                    expect(page.locator("#docs-recent [data-file]")).to_have_count(4)
                    page.locator("#docs-recent-label").press("Enter")
                    expect(page.locator("#docs-recent")).to_be_hidden()
                    page.reload(wait_until="networkidle")
                    if page.locator("#wiki-tree-toggle").get_attribute("aria-expanded") == "false":
                        page.locator("#wiki-tree-toggle").click()
                    expect(page.locator("#docs-recent-label")).to_have_attribute(
                        "aria-expanded", "false"
                    )
                    page.locator("#docs-recent-label").click()
                    for path in ["gamma.md", "delta.md", "epsilon.md"]:
                        assert context.request.delete(
                            base + "/api/vault-md/file", params={"path": path}
                        ).ok
                        paths.remove(path)
                    document("nested/linked.md")
                    open_docs()
                    expect(recent_section).to_be_visible()
                    nested = page.locator('#docs-recent [data-file="nested/linked.md"]')
                    expect(nested).to_be_visible()
                    nested.press("Enter")
                    expect(page.locator("#wiki-current")).to_have_text("linked")
                    expect(page.locator("#wiki-path")).to_have_text("nested/linked.md")

                    page.goto(base + "/?view=library", wait_until="networkidle")
                    queue = page.locator(".specialist-workbench-library .specialist-message-list")
                    add = queue.get_by_role("button", name="add a book", exact=True)
                    expect(add).to_be_visible()
                    add.press("Enter")
                    expect(page.locator("#book-title")).to_be_focused()
                    title = "local reading " + label
                    page.locator("#book-title").fill(title)
                    page.locator("#book-author").fill("owned author")
                    page.locator("#book-create").press("Enter")
                    expect(page.locator("#book-create-open")).to_be_visible()
                    page.locator("#book-create-open").click()
                    page.locator('#library-tabs [data-group-section="overview"]').click()
                    expect(queue).to_contain_text(title)
                    expect(
                        queue.get_by_role("button", name="add a book", exact=True)
                    ).to_have_count(0)
                    page.reload(wait_until="networkidle")
                    expect(queue).to_contain_text(title)
                    overview = context.request.get(base + "/api/books/overview").json()
                    created = [
                        book
                        for shelf in overview["shelves"].values()
                        for book in shelf
                        if book["title"] == title
                    ]
                    assert len(created) == 1, created
                    saved_filter = page.get_by_role("group", name="Library material").get_by_role(
                        "button", name="saved · 0", exact=True
                    )
                    saved_filter.click()
                    save = queue.get_by_role("button", name="save reading", exact=True)
                    save.press("Enter")
                    expect(page.locator("#read-url")).to_be_focused()
                    # No external reading URL is submitted; existing saved-reading
                    # workflow gates cover capture using local synthetic sources.
                    assert context.request.delete(base + "/api/books/" + created[0]["id"]).ok
                    page.goto(base + "/?view=library", wait_until="networkidle")
                    expect(
                        queue.get_by_role("button", name="add a book", exact=True)
                    ).to_be_visible()
                    page.screenshot(path=str(out / f"{label}-library-empty.png"))
                    assert not errors and not console and not external, (errors, console, external)
                    result.update(
                        status="passed",
                        page_errors=errors,
                        console_errors=console,
                        external_attempts=external,
                    )
                except Exception as error:
                    result.update(error=str(error), traceback=traceback.format_exc())
                    page.screenshot(path=str(out / f"{label}-failed.png"))
                finally:
                    for path in paths:
                        assert context.request.delete(
                            base + "/api/vault-md/file", params={"path": path}
                        ).ok
                    # The synthetic empty folder would otherwise make the next
                    # profile's two-root-file case a nested library.
                    folder = Path(os.environ["ALLES_DATA"]) / "vault" / "nested"
                    if folder.exists():
                        folder.rmdir()
                    context.close()
                    (out / "scenarios.json").write_text(json.dumps(results, indent=2) + "\n")
        browser.close()
    assert all(row["status"] == "passed" for row in results), results


if __name__ == "__main__":
    run()
