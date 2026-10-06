"""Gallery mutations belong to the selected photo, including after viewer changes."""

import io
import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from PIL import Image
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    from core.database import Photo, SessionLocal
    from services.appearance import from_legacy

    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    buttons = {"favorite": "fav", "archive": "archive", "hide": "hide", "delete": "del"}
    columns = {
        "favorite": "favorite",
        "archive": "archived",
        "hide": "hidden",
        "delete": "deleted_at",
    }
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
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok

                def seed(name, index):
                    content = io.BytesIO()
                    Image.new("RGB", (41 + index, 31), ["#b05937", "#376db0"][index]).save(
                        content, format="PNG"
                    )
                    response = context.request.post(
                        base + "/api/photos/upload",
                        multipart={
                            "file": {
                                "name": name,
                                "mimeType": "image/png",
                                "buffer": content.getvalue(),
                            },
                        },
                    )
                    assert response.ok, response.text()
                    return response.json()

                def open_photo(photo):
                    button = page.get_by_role(
                        "button", name="open " + photo["original_name"], exact=True
                    )
                    if width <= 390:
                        button.tap()
                    else:
                        button.focus()
                        page.keyboard.press("Enter")
                    expect(page.locator("#photos-lightbox")).to_have_attribute(
                        "aria-label", photo["original_name"]
                    )
                    expect(page.locator("#photos-lightbox")).to_be_visible()

                def activate(action):
                    if action in ("archive", "hide", "delete"):
                        more = page.locator("#photos-viewer-more-btn")
                        if width <= 390:
                            more.tap()
                        else:
                            more.press("Enter")
                        expect(more).to_have_attribute("aria-expanded", "true")
                        expect(page.locator("#photos-viewer-more-menu")).to_be_visible()
                    button = page.locator("#photos-" + buttons[action] + "-btn")
                    if width <= 390:
                        button.tap()
                    else:
                        button.focus()
                        page.keyboard.press("Enter")
                    if action == "delete":
                        page.get_by_role("alertdialog").get_by_role(
                            "button", name="confirm", exact=True
                        ).click()

                cases = [(a, m) for a in buttons for m in ["close", "switch"]]
                cases += [("favorite", "reopen"), ("favorite", "stay")]
                try:
                    for action, mode in cases:
                        name = f"{label}-{action}-{mode}"
                        row = {
                            "scenario_id": "gallery.pending-" + action + "-" + mode,
                            "profile": label,
                            "status": "failed",
                        }
                        rows.append(row)
                        first = seed(name + "-first.png", 0)
                        second = seed(name + "-second.png", 1)
                        page.goto(base + "/?view=photos", wait_until="networkidle")
                        open_photo(first)
                        held = []
                        method = "DELETE" if action == "delete" else "PATCH"
                        pattern = base + "/api/photos/" + first["id"]
                        page.route(
                            pattern,
                            lambda route: (
                                held.append(route)
                                if route.request.method == method
                                else route.continue_()
                            ),
                        )
                        activate(action)
                        page.wait_for_timeout(50)
                        assert len(held) == 1
                        if action == "favorite":
                            expect(page.locator("#photos-fav-btn")).to_have_attribute(
                                "aria-busy", "true"
                            )
                            # A repeated keyboard activation must not queue another write.
                            page.locator("#photos-fav-btn").focus()
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(30)
                            assert len(held) == 1
                        if mode != "stay":
                            page.locator("#photos-close-btn").click()
                            expect(page.locator("#photos-lightbox")).to_be_hidden()
                        if mode in ["switch", "reopen"]:
                            open_photo(second if mode == "switch" else first)
                        response = held[0].fetch()
                        assert response.ok, response.text()
                        held[0].fulfill(response=response)
                        page.unroute(pattern)
                        if action == "favorite":
                            expect(
                                page.locator(f'.photos-cell[data-id="{first["id"]}"]')
                            ).to_have_class(re.compile(r"\bfav\b"))
                        else:
                            expect(
                                page.locator(f'.photos-cell[data-id="{first["id"]}"]')
                            ).to_have_count(0)
                        with SessionLocal() as db:
                            saved = db.get(Photo, first["id"])
                            untouched = db.get(Photo, second["id"])
                            assert getattr(saved, columns[action])
                            assert (
                                not untouched.favorite
                                and not untouched.archived
                                and not untouched.hidden
                                and not untouched.deleted_at
                            )
                        if mode == "switch":
                            expect(page.locator("#photos-lightbox")).to_be_visible()
                            expect(page.locator("#photos-lightbox")).to_have_attribute(
                                "aria-label", second["original_name"]
                            )
                            expect(page.locator("#photos-fav-btn")).to_have_text("favorite")
                            expect(page.locator("#photos-fav-btn")).to_have_attribute(
                                "aria-busy", "false"
                            )
                        elif mode in ["reopen", "stay"]:
                            expect(page.locator("#photos-fav-btn")).to_have_text("favorited")
                            expect(page.locator("#photos-fav-btn")).to_have_attribute(
                                "aria-busy", "false"
                            )
                            if mode == "stay":
                                expect(page.locator("#photos-fav-btn")).to_be_focused()
                            page.screenshot(path=str(out / f"{name}.png"))
                        else:
                            expect(page.locator("#photos-lightbox")).to_be_hidden()
                        assert not errors and not console and not external, (
                            errors,
                            console,
                            external,
                        )
                        row.update(
                            status="passed",
                            intended_only_saved=True,
                            page_errors=list(errors),
                            console_errors=list(console),
                            external_attempts=list(external),
                        )
                        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

                    # Explicit failures and malformed replies retain the current
                    # photo and allow a confirmed retry without optimistic state.
                    for action in ["favorite", "archive", "hide"]:
                        name = f"{label}-{action}-recovery"
                        row = {
                            "scenario_id": "gallery." + action + "-recovery",
                            "profile": label,
                            "status": "failed",
                        }
                        rows.append(row)
                        photo = seed(name + ".png", 0)
                        page.goto(base + "/?view=photos", wait_until="networkidle")
                        open_photo(photo)
                        pattern = base + "/api/photos/" + photo["id"]
                        for status, payload in [
                            (503, {"detail": "synthetic write rejection"}),
                            (200, {"id": "different-photo"}),
                        ]:
                            count = len(console)
                            page.route(
                                pattern,
                                lambda route: (
                                    route.fulfill(status=status, json=payload)
                                    if route.request.method == "PATCH"
                                    else route.continue_()
                                ),
                            )
                            activate(action)
                            expect(
                                page.locator("#toast-container .toast.error").last
                            ).to_contain_text("could not be saved")
                            page.wait_for_timeout(50)
                            expect(page.locator("#photos-lightbox")).to_be_visible()
                            expect(page.locator("#photos-lightbox")).to_have_attribute(
                                "aria-label", photo["original_name"]
                            )
                            with SessionLocal() as db:
                                assert not getattr(db.get(Photo, photo["id"]), columns[action])
                            assert all("503" in error for error in console[count:]), console[count:]
                            del console[count:]
                            page.unroute(pattern)
                        activate(action)
                        if action == "favorite":
                            expect(page.locator("#photos-fav-btn")).to_have_text("favorited")
                            expect(page.locator("#photos-fav-btn")).to_have_attribute(
                                "aria-busy", "false"
                            )
                        else:
                            expect(page.locator("#photos-lightbox")).to_be_hidden()
                        with SessionLocal() as db:
                            assert getattr(db.get(Photo, photo["id"]), columns[action])
                        assert not errors and not console and not external, (
                            errors,
                            console,
                            external,
                        )
                        row.update(status="passed", saved_after_retry=True)
                        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
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
    assert len(rows) == 78 and all(row["status"] == "passed" for row in rows), "see scenarios.json"


if __name__ == "__main__":
    run()
