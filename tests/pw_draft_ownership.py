"""Pending save ownership across Docs, Notes, Skills, and Memory on disposable local data."""

import json
import os
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright
from pw_settings_helpers import choose_settings_section


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(1440, "dark"), (390, "light")]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(12000)
            errors, console, held, writes, external = [], [], [], [], []
            state = {"hold_path": "", "hold_method": "", "malformed_path": ""}
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def guard(route):
                request = route.request
                url = urlsplit(request.url)
                if url.netloc != urlsplit(base).netloc:
                    external.append(request.url)
                    route.abort("blockedbyclient")
                    return
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    writes.append(
                        {"path": url.path, "method": request.method, "body": request.post_data_json}
                    )
                if url.path == state["hold_path"] and request.method == state["hold_method"]:
                    state["hold_path"] = ""
                    held.append(route)
                elif url.path == state["malformed_path"] and request.method in {
                    "PATCH",
                    "PUT",
                    "POST",
                }:
                    state["malformed_path"] = ""
                    route.fulfill(status=200, content_type="application/json", body="{}")
                else:
                    route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda ws: ws.close())
            api = context.request
            row = {"profile": f"{width}-{theme}", "status": "failed", "checks": []}
            records.append(row)

            def hold(path, method):
                assert not held
                state.update(hold_path=path, hold_method=method)

            def release():
                assert len(held) == 1
                request = held.pop()
                response = request.fetch()
                assert response.ok, response.text()
                request.fulfill(response=response)
                return response.json()

            def shot(name):
                page.screenshot(path=str(output / f"{width}-{name}.png"))

            def open_document(name):
                file = page.locator(f'#wiki-tree [data-file="{name}"]')
                if not file.is_visible():
                    page.locator("#wiki-tree-toggle").click()
                file.click()

            try:
                assert api.post(base + "/api/setup/dismiss").ok
                assert api.patch(
                    base + "/api/settings",
                    data={"theme": theme, "language": "en", "memory_policy": "ask"},
                ).ok
                a, b = f"draft-a-{width}.md", f"draft-b-{width}.md"
                for name in [a, b]:
                    assert api.post(
                        base + "/api/vault-md/file",
                        data={"path": name, "content": "# " + name + "\noriginal\n"},
                    ).ok
                page.goto(base + "/?view=wiki", wait_until="networkidle")
                open_document(a)
                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                source = page.locator("#wiki-source")
                source.fill("# submitted A\nfirst save\n")
                hold("/api/vault-md/safety/save", "POST")
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-btn")).to_be_disabled()
                source.fill("# newer A\nkeep exact 草稿\n")
                open_document(b)
                assert len(held) == 1
                release()
                expect(page.locator("#wiki-preview")).to_contain_text(b)
                page.locator("#wiki-edit-btn").click()
                page.locator("#wiki-source-btn").click()
                source.fill("# B independent draft\n")
                page.locator("#wiki-save-btn").click()
                expect(page.locator("#wiki-save-state")).to_have_text("saved")
                disk_a = api.get(base + "/api/vault-md/file", params={"path": a}).json()
                draft_a = api.get(base + "/api/vault-md/safety/draft", params={"path": a}).json()[
                    "draft"
                ]
                assert (
                    disk_a["content"] == "# newer A\nkeep exact 草稿\n"
                    or draft_a["content"] == "# newer A\nkeep exact 草稿\n"
                )
                assert (
                    api.get(base + "/api/vault-md/file", params={"path": b}).json()["content"]
                    == "# B independent draft\n"
                )
                row["checks"].append(
                    "Docs: switch waits for queued A writes; newer A survives; B saves to its own file"
                )
                shot("docs")

                # Notes waits for its save before New, including edits entered while waiting.
                note = api.post(
                    base + "/api/notes", data={"title": f"note-a-{width}", "content": "original A"}
                ).json()
                page.goto(base + "/?view=wiki", wait_until="networkidle")
                notes_tab = page.locator('.docs-sec-btn[data-section="notes"]')
                if not notes_tab.is_visible():
                    page.locator("#wiki-tree-toggle").click()
                notes_tab.click()
                title_button = page.locator(f'.note-card[data-id="{note["id"]}"] .note-title')
                expect(title_button).to_have_attribute("type", "button")
                assert title_button.bounding_box()["height"] >= 44
                shot("notes-board")
                title_button.click()
                page.locator("#note-edit-body").fill("submitted note A")
                hold("/api/notes/" + note["id"], "PATCH")
                page.locator("#note-save-btn").click()
                expect(page.locator("#note-save-btn")).to_have_attribute("aria-busy", "true")
                page.locator("#note-edit-body").fill("newer note A 草稿")
                page.locator("#note-new-btn").click()
                expect(page.locator("#note-edit-body")).to_have_value("newer note A 草稿")
                release()
                expect(page.locator("#note-edit-body")).to_have_value("")
                page.locator("#note-edit-title").fill(f"note-b-{width}")
                page.locator("#note-edit-body").fill("B independent note draft")
                page.locator("#note-save-btn").click()
                expect(page.locator("#note-save-btn")).not_to_have_attribute("aria-busy", "true")
                notes = api.get(base + "/api/notes").json()
                assert (
                    next(item for item in notes if item["id"] == note["id"])["content"]
                    == "newer note A 草稿"
                )
                assert (
                    next(item for item in notes if item["title"] == f"note-b-{width}")["content"]
                    == "B independent note draft"
                )
                row["checks"].append(
                    "Notes: New waits for pending Save; newer A flushes first; retitled B saves independently"
                )
                shot("notes")
                page.locator("#note-back-btn").click()
                title_button.focus()
                page.keyboard.press("Enter")
                expect(page.locator("#note-edit-body")).to_have_value("newer note A 草稿")
                row["checks"].append(
                    "Notes: title opens by pointer and keyboard without hitting actions"
                )

                # A late create cannot change the identity or content of the next skill drawer.
                page.goto(base + "/?view=skills", wait_until="networkidle")
                page.locator("#skl-new").click()
                page.locator("#skl-d-name").fill(f"skill A {width}")
                page.locator("#skl-d-body").fill("A procedure")
                hold("/api/skills", "POST")
                page.locator("#skl-d-save").click()
                expect(page.locator("#skl-d-save")).to_have_attribute("aria-busy", "true")
                page.locator("#skl-d-close").click()
                page.locator("#skl-new").click()
                page.locator("#skl-d-name").fill(f"skill B {width}")
                page.locator("#skl-d-body").fill("B independent procedure 草稿")
                saved_a = release()
                expect(page.locator("#skl-d-heading")).to_have_text("new skill")
                expect(page.locator("#skl-d-body")).to_have_value("B independent procedure 草稿")
                page.locator("#skl-d-save").click()
                expect(page.locator("#skl-d-heading")).to_have_text("edit skill")
                skills = api.get(base + "/api/skills").json()
                saved_b = next(item for item in skills if item["name"] == f"skill B {width}")
                assert saved_b["slug"] != saved_a["slug"]
                assert (
                    api.get(base + "/api/skills/" + saved_b["slug"]).json()["body"]
                    == "B independent procedure 草稿"
                )
                row["checks"].append(
                    "Skills: closing pending create A and editing B keeps B unbound to A; both persist separately"
                )
                shot("skills")

                # A pending add must not clear a newer add or another memory's edit dialog.
                existing = api.post(
                    base + "/api/memories",
                    data={"text": f"memory B {width}", "category": "general"},
                ).json()
                page.goto(base + "/?view=today", wait_until="networkidle")
                page.locator("#today-settings").click()
                choose_settings_section(page, "memory")
                expect(page.locator("#mem-add-input")).to_be_visible()
                page.locator("#mem-add-input").fill(f"memory A pending {width}")
                hold("/api/memories", "POST")
                page.locator("#mem-add-btn").click()
                expect(page.locator("#mem-add-btn")).to_be_disabled()
                page.locator("#mem-add-input").fill("newer memory C 草稿")
                page.locator(f'.mem-edit-btn[data-id="{existing["id"]}"]').click()
                edit = page.get_by_role("dialog", name="edit memory", exact=True)
                edit.locator("input").fill("B independent memory draft")
                release()
                expect(edit.locator("input")).to_have_value("B independent memory draft")
                expect(page.locator("#mem-add-input")).to_have_value("newer memory C 草稿")
                state["malformed_path"] = "/api/memories/" + existing["id"]
                edit.get_by_role("button", name="save", exact=True).click()
                expect(edit).to_contain_text("could not confirm memory change")
                expect(edit.locator("input")).to_have_value("B independent memory draft")
                edit.get_by_role("button", name="save", exact=True).click()
                expect(edit).to_have_count(0)
                memories = api.get(base + "/api/memories").json()
                assert (
                    next(item for item in memories if item["id"] == existing["id"])["text"]
                    == "B independent memory draft"
                )
                assert any(item["text"] == f"memory A pending {width}" for item in memories)
                expect(page.locator("#mem-add-input")).to_have_value("newer memory C 草稿")
                row["checks"].append(
                    "Memory: late add keeps newer input and B edit; malformed edit acknowledgment keeps draft; retry persists exact B"
                )
                shot("memory")
                assert not errors and not console and not external, (errors, console, external)
                row["status"] = "passed"
            except Exception:
                row["error"] = traceback.format_exc()
                shot("failure")
            finally:
                for request in held:
                    request.abort()
                row.update(errors=errors, console=console, external=external, writes=writes)
                (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                context.tracing.stop(path=str(output / f"draft-{width}-trace.zip"))
                context.close()
        browser.close()
    print(json.dumps(records, indent=2))
    assert all(row["status"] == "passed" for row in records)


if __name__ == "__main__":
    run()
