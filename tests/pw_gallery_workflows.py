"""Gallery local persistence, recovery and keyboard workflows on owned fixtures."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from browser_gate_safety import require_server_ownership
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"])
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    out.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for profile, width, theme in [
            ("desktop-light", 1440, "light"),
            ("desktop-dark", 1440, "dark"),
            ("phone-light", 390, "light"),
            ("phone-dark", 390, "dark"),
        ]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                has_touch=width == 390,
                is_mobile=width == 390,
                reduced_motion="reduce",
                service_workers="block",
                timezone_id="UTC",
                locale="en-US",
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            events, expected_http, expected_reset = [], [], []
            page.on("pageerror", lambda error: events.append({"pageerror": str(error)}))
            page.on(
                "console",
                lambda msg: (
                    events.append({"console": msg.type, "text": msg.text})
                    if msg.type in ("warning", "error")
                    else None
                ),
            )
            page.on(
                "requestfailed",
                lambda req: events.append({"failed": req.url, "reason": req.failure}),
            )
            page.on(
                "response",
                lambda res: (
                    events.append({"http": res.status, "url": res.url})
                    if res.status >= 400
                    else None
                ),
            )
            active = None

            def begin(name):
                nonlocal active
                active = {"scenario_id": f"gallery.{name}", "profile": profile, "status": "failed"}
                records.append(active)

            def passed(**proof):
                active.update(status="passed", **proof)

            def shot(name):
                page.screenshot(path=str(out / f"{profile}-{name}.png"), full_page=True)

            def saved():
                response = context.request.get(base + "/api/photos/list?offset=0&limit=120")
                assert response.ok
                return [item for moment in response.json()["moments"] for item in moment["items"]]

            def albums():
                return context.request.get(base + "/api/photos/albums").json()

            def by_id(pid):
                return next(item for item in saved() if item["id"] == pid)

            def reload():
                page.reload(wait_until="networkidle")
                expect(page.get_by_role("tab", name="gallery", exact=True)).to_be_visible()

            def gallery():
                page.get_by_role("button", name="photos", exact=True).click()
                expect(page.locator(".photos-open").first).to_be_visible()

            def upload(paths):
                with page.expect_file_chooser() as picker:
                    page.get_by_role("button", name="upload", exact=True).click()
                picker.value.set_files([str(path) for path in paths])
                expect(page.locator("#photos-upload-btn")).to_be_enabled()

            def open_photo(name):
                page.get_by_role("button", name="open " + name, exact=True).click()
                expect(page.locator("#photos-lightbox")).to_be_visible()

            def select(name):
                page.get_by_role("button", name="select " + name, exact=True).click()

            def prompt_album(name):
                page.get_by_role("textbox", name="album name:", exact=True).fill(name)
                page.get_by_role("button", name="ok", exact=True).click()

            def choose_album(name):
                page.get_by_role("button", name="add to album", exact=True).click()
                page.get_by_role("dialog", name="add to album", exact=True).get_by_role(
                    "button", name=name, exact=True
                ).click()

            def reject(path, method="POST", status=503, payload=None):
                def handler(route):
                    if route.request.method != method:
                        route.continue_()
                        return
                    if status >= 400:
                        expected_http.append((route.request.url, status))
                    route.fulfill(
                        status=status,
                        content_type="application/json",
                        body=json.dumps(
                            {"detail": "explicit simulated rejection"}
                            if payload is None and status != 200
                            else payload
                        ),
                    )

                pattern = "**" + path
                page.route(pattern, handler)
                return pattern, handler

            def unroute(rule):
                page.unroute(*rule)

            try:
                begin("navigation-and-empty")
                page.goto(base + "/?view=today", wait_until="networkidle")
                if page.get_by_role("button", name="exit setup", exact=True).is_visible():
                    page.get_by_role("button", name="exit setup", exact=True).click()
                page.locator("#today-settings").click()
                page.locator('.s-nav-item[data-pane="themes"]').click()
                with page.expect_response(
                    lambda r: r.url.endswith("/api/appearance") and r.request.method == "PUT"
                ) as appearance:
                    page.locator(f'[data-theme-mode="{theme}"]').click()
                assert appearance.value.ok
                page.locator("#settings-modal-close").click()
                page.goto(base + "/?view=files", wait_until="networkidle")
                page.get_by_role("tab", name="gallery", exact=True).click()
                if not saved():
                    expect(page.locator("#photos-grid")).to_contain_text("gallery empty")
                shot("initial")
                passed(route=page.url)

                fixtures = []
                for index, color in enumerate(("#2479bb", "#228855", "#bd3333")):
                    name = (
                        f"{profile}-{index}-"
                        + ("紅色 résumé " + "long image name " * 7 if index == 2 else "study")
                        + ".png"
                    )
                    path = out / name
                    image = Image.new("RGB", (160, 120), color)
                    ImageDraw.Draw(image).rectangle((10, 10, 149, 109), outline="white", width=3)
                    image.save(path)
                    fixtures.append(path)
                names = [path.name for path in fixtures]
                begin("multiple-upload-bytes-and-reload")
                before = len(saved())
                upload(fixtures)
                expect(
                    page.get_by_role("button", name="open " + names[2], exact=True)
                ).to_be_visible()
                assert len(saved()) == before + 3
                reload()
                photos = [
                    next(item for item in saved() if item["original_name"] == name)
                    for name in names
                ]
                byte_proof = []
                for item, path in zip(photos, fixtures):
                    result = context.request.get(base + item["original"])
                    digest = hashlib.sha256(result.body()).hexdigest()
                    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
                    byte_proof.append({"id": item["id"], "name": path.name, "sha256": digest})
                shot("multi-upload")
                passed(originals=byte_proof)

                begin("keyboard-photo-entry-and-modal-focus")
                # Actual Tab traversal from a visible pointer-focused field, never forced focus.
                page.get_by_role("textbox", name="search photos…", exact=True).click()
                visited = []
                for _ in range(100):
                    page.keyboard.press("Tab")
                    current = page.evaluate(
                        "({cls:document.activeElement.className,aria:document.activeElement.getAttribute('aria-label')})"
                    )
                    visited.append(current)
                    if current["cls"] == "photos-check":
                        assert (
                            page.locator(":focus").evaluate("el=>getComputedStyle(el).opacity")
                            != "0"
                        )
                    if current["aria"] == "open " + names[2]:
                        break
                else:
                    raise AssertionError("image never reached by Tab")
                page.keyboard.press("Enter")
                expect(page.locator("#photos-close-btn")).to_be_focused()
                expect(page.locator("#photos-lightbox")).to_have_attribute("role", "dialog")
                expect(page.locator("#photos-lightbox")).to_have_attribute("aria-modal", "true")
                for _ in range(18):
                    page.keyboard.press("Tab")
                    assert page.evaluate("!!document.activeElement.closest('#photos-lightbox')")
                    assert not page.evaluate(
                        "!!document.activeElement.closest('#photos-lb-drawer')"
                    )
                page.keyboard.press("Escape")
                expect(
                    page.get_by_role("button", name="open " + names[2], exact=True)
                ).to_be_focused()
                shot("keyboard-return")
                passed(tab_path=visited)

                begin("album-create-failure-draft-retry")
                rule = reject("/api/photos/albums")
                page.get_by_role("button", name="new album", exact=True).click()
                album_name = profile + " research 秋季 " + "long name " * 15
                prompt_album(album_name)
                expect(page.get_by_role("textbox", name="album name:", exact=True)).to_have_value(
                    album_name
                )
                expect(page.locator("#toast-container")).to_contain_text(
                    "album could not be created"
                )
                assert not any(a["name"] == album_name.strip() for a in albums())
                shot("album-create-rejected")
                unroute(rule)
                page.get_by_role("button", name="ok", exact=True).click()
                expect(page.get_by_role("textbox", name="album name:", exact=True)).to_have_count(0)
                page.wait_for_load_state("networkidle")
                aid = next(a["id"] for a in albums() if a["name"] == album_name.strip())
                passed(album_id=aid)

                begin("album-choice-bounds-keyboard-and-membership")
                select(names[2])
                page.get_by_role("button", name="add to album", exact=True).click()
                dialog = page.get_by_role("dialog", name="add to album", exact=True)
                box = dialog.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width
                assert dialog.evaluate("el=>el.scrollWidth<=el.clientWidth")
                option = dialog.get_by_role("button", name=album_name.strip(), exact=True)
                assert option.bounding_box()["height"] >= 44
                shot("album-choice")
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(0)
                expect(page.get_by_role("button", name="add to album", exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                for _ in range(100):
                    page.keyboard.press("Tab")
                    if page.locator(":focus").inner_text().strip() == album_name.strip():
                        break
                else:
                    raise AssertionError("album option unreachable by Tab")
                page.keyboard.press("Enter")
                expect(page.locator("#photos-selbar")).to_be_hidden()
                reload()
                assert by_id(photos[2]["id"])["album_id"] == aid
                passed(album_id=aid, menu_box=box)

                begin("rejected-new-destination-preserves-membership")
                select(names[2])
                choose_album("new album…")
                rule = reject("/api/photos/albums")
                destination = profile + " new destination"
                prompt_album(destination)
                expect(page.get_by_role("textbox", name="album name:", exact=True)).to_have_value(
                    destination
                )
                assert by_id(photos[2]["id"])["album_id"] == aid
                shot("destination-rejected")
                unroute(rule)
                page.get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#photos-selbar")).to_be_visible()
                reload()
                assert by_id(photos[2]["id"])["album_id"] == aid
                # Both null and empty object acknowledgments must not become album removal.
                for payload in [None, {}]:
                    select(names[2])
                    choose_album("new album…")
                    rule = reject("/api/photos/albums", status=200, payload=payload)
                    prompt_album(destination)
                    expect(
                        page.get_by_role("textbox", name="album name:", exact=True)
                    ).to_have_value(destination)
                    assert by_id(photos[2]["id"])["album_id"] == aid
                    unroute(rule)
                    page.get_by_role("button", name="cancel", exact=True).click()
                    reload()
                passed(saved_album_id=aid, malformed_acknowledgments=[None, {}])

                begin("wrong-album-acknowledgement-preserves-membership")
                unrelated = context.request.post(
                    base + "/api/photos/albums",
                    data={"name": profile + " unrelated existing album"},
                ).json()
                destination = "  " + profile + " intended résumé 秋季  "
                acknowledgements, membership_requests = [], []

                def replay_stale_ack(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    requested = route.request.post_data_json
                    actual = route.fetch()
                    assert actual.ok
                    created = actual.json()
                    assert created["name"] == requested["name"] == destination.strip()
                    acknowledgements.append(
                        {
                            "requested": requested,
                            "created": created,
                            "replayed_acknowledgement": unrelated,
                        }
                    )
                    # Deliberate successful-response corruption after the real commit.
                    route.fulfill(response=actual, json=unrelated)

                def record_membership(request):
                    if request.method == "POST" and request.url.endswith("/api/photos/batch"):
                        membership_requests.append(request.post_data_json)

                page.on("request", record_membership)
                page.route("**/api/photos/albums", replay_stale_ack)
                select(names[2])
                choose_album("new album…")
                prompt_album(destination)
                page.wait_for_function("""() => document.querySelector('.dialog-input')
                  || !document.querySelector('#photos-selbar').getClientRects().length""")
                active.update(
                    original_album_id=aid,
                    photo_id=photos[2]["id"],
                    saved_album_after_ack=by_id(photos[2]["id"])["album_id"],
                    acknowledgements=acknowledgements,
                    membership_requests=membership_requests,
                    fault="replayed unrelated successful acknowledgement after real create",
                )
                shot("wrong-album-acknowledgement")
                if active["saved_album_after_ack"] != aid:
                    reload()
                    active["saved_album_after_reload"] = by_id(photos[2]["id"])["album_id"]
                assert active["saved_album_after_ack"] == aid, active
                assert membership_requests == [], membership_requests
                expect(page.get_by_role("textbox", name="album name:", exact=True)).to_have_value(
                    destination
                )
                expect(page.locator("#toast-container")).to_contain_text(
                    "album could not be created"
                )
                page.unroute("**/api/photos/albums", replay_stale_ack)
                page.get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#photos-selbar")).to_be_visible()
                reload()
                assert by_id(photos[2]["id"])["album_id"] == aid
                assert next(a for a in albums() if a["id"] == unrelated["id"])["count"] == 0
                # A new attempt after reload uses the trimmed name; album drafts
                # belong to the page session rather than durable recovery storage.
                select(names[2])
                choose_album("new album…")
                expect(page.get_by_role("textbox", name="album name:", exact=True)).to_have_value(
                    ""
                )
                recovered = "  " + profile + " recovered résumé 秋季  "
                prompt_album(recovered)
                expect(page.locator("#photos-selbar")).to_be_hidden()
                reload()
                correct = next(a for a in albums() if a["name"] == recovered.strip())
                assert by_id(photos[2]["id"])["album_id"] == correct["id"]
                assert membership_requests == [
                    {"ids": [photos[2]["id"]], "action": "album", "album_id": correct["id"]}
                ], membership_requests
                page.remove_listener("request", record_membership)
                # Preserve neighboring scenarios' original fixture membership.
                select(names[2])
                choose_album(album_name.strip())
                expect(page.locator("#photos-selbar")).to_be_hidden()
                reload()
                assert by_id(photos[2]["id"])["album_id"] == aid
                passed(
                    saved_album_id=aid,
                    recovered_album_id=correct["id"],
                    preserved_after_cancel_and_reload=True,
                )

                begin("caption-rejected-and-malformed-draft-retention")
                open_photo(names[2])
                page.get_by_role("button", name="info", exact=True).click()
                draft = profile + " caption retained 秋季"
                page.locator("#photos-caption").fill(draft)
                page.locator("#photos-keywords").fill("Study, Autumn, study")
                rule = reject("/api/photos/" + photos[2]["id"], method="PATCH")
                page.get_by_role("button", name="save caption & keywords", exact=True).click()
                expect(page.locator("#photos-meta-status")).to_contain_text("save failed")
                expect(page.locator("#photos-caption")).to_have_value(draft)
                assert by_id(photos[2]["id"])["caption"] == ""
                unroute(rule)
                for payload in [None, {}]:
                    rule = reject(
                        "/api/photos/" + photos[2]["id"],
                        method="PATCH",
                        status=200,
                        payload=payload,
                    )
                    page.get_by_role("button", name="save caption & keywords", exact=True).click()
                    expect(page.locator("#photos-meta-status")).to_contain_text("save failed")
                    expect(page.locator("#photos-caption")).to_have_value(draft)
                    unroute(rule)
                page.get_by_role("button", name="close", exact=True).click()
                expect(
                    page.get_by_role("alertdialog", name="discard unsaved caption and keywords?")
                ).to_be_visible()
                page.get_by_role("button", name="cancel", exact=True).click()
                expect(page.locator("#photos-caption")).to_have_value(draft)
                shot("caption-rejected")
                page.get_by_role("button", name="save caption & keywords", exact=True).click()
                expect(page.locator("#photos-meta-status")).to_have_text("saved")
                page.get_by_role("button", name="close", exact=True).click()
                reload()
                assert by_id(photos[2]["id"])["caption"] == draft
                assert by_id(photos[2]["id"])["keywords"] == ["study", "autumn"]
                open_photo(names[2])
                expect(page.locator("#photos-caption")).to_have_value(draft)
                page.get_by_role("button", name="close", exact=True).click()
                passed(photo=by_id(photos[2]["id"]))

                begin("viewer-editor-reentry-neighbor")
                for _ in range(2):
                    open_photo(names[2])
                    page.get_by_role("button", name="edit", exact=True).click()
                    expect(page.locator("#imgeditor-modal")).to_be_visible()
                    page.locator('#imgeditor-modal [data-act="close"]').click()
                    expect(page.locator("#imgeditor-modal")).to_be_hidden()
                    if page.locator("#photos-lightbox").is_visible():
                        page.get_by_role("button", name="close", exact=True).click()
                passed(editor_open_close_cycles=2)

                begin("list-rejection-and-owned-retry")
                rule = reject("/api/photos/list?*", method="GET")
                reload()
                expect(page.locator("#photos-load-status")).to_contain_text("photos could not load")
                expect(page.locator("#photos-grid")).not_to_contain_text("gallery empty")
                assert by_id(photos[2]["id"])["caption"] == draft
                shot("list-error")
                unroute(rule)
                page.get_by_role("button", name="photos", exact=True).click()
                expect(page.locator("#photos-load-status")).to_be_hidden()
                expect(page.locator("#files-view > .specialist-state")).to_be_hidden()
                expect(
                    page.get_by_role("button", name="open " + names[2], exact=True)
                ).to_be_visible()
                passed(saved_count=len(saved()))

                begin("optional-album-metadata-recovery")
                rule = reject("/api/photos/albums", method="GET")
                reload()
                expect(page.locator("#photos-load-status")).to_contain_text("albums could not load")
                expect(
                    page.get_by_role("button", name="open " + names[2], exact=True)
                ).to_be_visible()
                assert by_id(photos[2]["id"])["album_id"] == aid
                shot("album-metadata-error")
                unroute(rule)
                page.locator("#photos-load-retry").click()
                expect(page.locator("#photos-load-status")).to_be_hidden()
                expect(page.locator("#files-view > .specialist-state")).to_be_hidden()
                assert by_id(photos[2]["id"])["album_id"] == aid
                passed(saved_album_id=aid)

                begin("delete-restore-rejection-and-reload")
                open_photo(names[0])
                page.get_by_role("button", name="delete", exact=True).click()
                page.get_by_role("button", name="cancel", exact=True).click()
                assert by_id(photos[0]["id"])
                page.get_by_role("button", name="delete", exact=True).click()
                page.get_by_role("button", name="confirm", exact=True).click()
                expect(page.locator("#photos-lightbox")).to_be_hidden()
                page.get_by_role("button", name="trash", exact=True).click()
                expect(page.get_by_role("button", name="restore", exact=True)).to_be_visible()
                rule = reject("/api/photos/" + photos[0]["id"] + "/restore")
                page.get_by_role("button", name="restore", exact=True).click()
                expect(page.locator("#toast-container")).to_contain_text("restore failed")
                assert any(
                    x["id"] == photos[0]["id"]
                    for x in context.request.get(base + "/api/photos/trash").json()
                )
                shot("restore-error")
                unroute(rule)
                page.get_by_role("button", name="restore", exact=True).click()
                expect(page.locator("#photos-grid")).to_contain_text("trash is empty")
                page.get_by_role("link", name="gallery", exact=True).click()
                reload()
                assert by_id(photos[0]["id"])["original_name"] == names[0]
                passed(restored_id=photos[0]["id"])

                begin("upload-interruption-and-visible-retry")
                before = len(saved())

                def abort_upload(route):
                    expected_reset.append(route.request.url)
                    route.abort("connectionreset")

                page.route("**/api/photos/upload", abort_upload)
                upload([fixtures[0]])
                expect(page.locator("#photos-upload-status")).to_contain_text(
                    "your files are kept for retry"
                )
                assert len(saved()) == before
                shot("upload-error")
                page.unroute("**/api/photos/upload", abort_upload)
                page.get_by_role("button", name="retry upload", exact=True).click()
                expect(page.locator("#photos-upload-status")).to_be_hidden()
                reload()
                assert len(saved()) == before + 1
                passed(before=before, after=len(saved()))

                begin("search-filter-album-remove-touch-return")
                page.get_by_role("textbox", name="search photos…", exact=True).fill(names[1])
                expect(page.locator(".photos-open")).to_have_count(1)
                expect(
                    page.get_by_role("button", name="open " + names[1], exact=True)
                ).to_be_visible()
                page.get_by_role("textbox", name="search photos…", exact=True).fill("")
                expect(page.locator(".photos-open").nth(2)).to_be_visible()
                page.get_by_role("button", name="filter", exact=True).click()
                page.get_by_role("button", name="videos", exact=True).click()
                expect(page.locator("#photos-grid")).to_contain_text("no photos match")
                page.get_by_role("button", name="clear", exact=True).click()
                page.get_by_role("button", name="filter", exact=True).click()
                page.get_by_role("button", name=album_name.strip() + " 1", exact=True).click()
                select(names[2])
                choose_album("remove from album")
                expect(page.locator("#photos-grid")).to_contain_text("gallery empty")
                reload()
                assert by_id(photos[2]["id"])["album_id"] is None
                if width == 390:
                    page.get_by_role("button", name="open " + names[2], exact=True).tap()
                    page.get_by_role("button", name="close", exact=True).tap()
                    page.get_by_role("button", name="← files", exact=True).tap()
                else:
                    page.get_by_role("tab", name="files", exact=True).click()
                expect(page.get_by_role("tab", name="files", exact=True)).to_have_attribute(
                    "aria-selected", "true"
                )
                page.get_by_role("tab", name="gallery", exact=True).click()
                shot("final-populated")
                passed(removed_album_id=aid, photo_id=photos[2]["id"])

                begin("exact-error-accounting")
                observed_http = Counter((e["url"], e["http"]) for e in events if "http" in e)
                assert observed_http == Counter(expected_http), (observed_http, expected_http)
                assert not [e for e in events if "pageerror" in e], events
                failed = [e for e in events if "failed" in e]
                assert Counter(e["failed"] for e in failed) == Counter(expected_reset)
                assert all(e["reason"] == "net::ERR_CONNECTION_RESET" for e in failed)
                console = Counter((e["console"], e["text"]) for e in events if "console" in e)
                assert console.pop(
                    (
                        "error",
                        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
                    ),
                    0,
                ) == len(expected_http)
                assert console.pop(
                    ("error", "Failed to load resource: net::ERR_CONNECTION_RESET"), 0
                ) == len(expected_reset)
                console.pop(("warning", "Service Worker registration blocked by Playwright"), 0)
                assert not console, console
                passed(
                    simulated_http=expected_http,
                    simulated_connection_resets=expected_reset,
                    unexpected_errors=[],
                )
            except Exception as error:
                if active is not None:
                    active["error"] = str(error)
                shot("failure")
                raise
            finally:
                (out / f"{profile}-events.json").write_text(json.dumps(events, indent=2))
                (out / "scenarios.json").write_text(
                    json.dumps(records, indent=2, ensure_ascii=False)
                )
                context.tracing.stop(path=str(out / f"{profile}-trace.zip"))
                context.close()
        browser.close()
    print(f"{len(records)}/{len(records)} Gallery scenarios passed")


if __name__ == "__main__":
    run()
