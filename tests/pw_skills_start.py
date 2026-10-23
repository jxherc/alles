"""Skills starting choices, complete catalogue and personal choices on owned local data."""

import base64
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
profiles = [(w, t, False) for w in [1440, 820, 390] for t in ["dark", "light"]]
profiles += [(1280, t, True) for t in ["dark", "light"]]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            options = {
                "viewport": {"width": width, "height": 900 if zoom else 844},
                "is_mobile": width == 390,
                "has_touch": width == 390,
                "service_workers": "block",
                "reduced_motion": "reduce",
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
            external = []

            def guard(route):
                parsed = urlparse(route.request.url)
                owned = urlparse(base)
                if (parsed.scheme, parsed.netloc) == (owned.scheme, owned.netloc):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()

            context.route("**/*", guard)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            row = {
                "scenario_id": "aide.skills-start",
                "profile": label,
                "status": "failed",
            }
            rows.append(row)
            name = (
                "owned personal procedure: compare lesson notes and create a clear "
                "study guide for the next assessment 草稿 " + label
            )
            purpose = (
                "compare the supplied local lesson notes, identify the topics that need "
                "practice, explain the differences, and save a clear study guide with "
                "specific next steps before the next assessment."
            )
            saved_body = "keep the exact local study guide and receipt 草稿\n"

            def shot(suffix):
                capture = context.new_cdp_session(page).send(
                    "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                )
                (out / f"{label}-{suffix}.png").write_bytes(base64.b64decode(capture["data"]))

            def choices():
                geometry = page.locator("#skl-grid .skl-card").evaluate_all(
                    """nodes => nodes.map(card => {
                        const title = card.querySelector('.skl-card-name');
                        const desc = card.querySelector('.skl-card-desc');
                        return {
                            title: [title.clientWidth,title.scrollWidth,title.clientHeight,title.scrollHeight],
                            purpose: [desc.clientWidth,desc.scrollWidth,desc.clientHeight,desc.scrollHeight],
                            targets: [...card.querySelectorAll('button')].map(button => {
                                const r=button.getBoundingClientRect();
                                return {name:button.getAttribute('aria-label'),width:r.width,height:r.height};
                            }),
                            width:card.getBoundingClientRect().width,
                            x:card.getBoundingClientRect().x
                        };
                    })"""
                )
                for card in geometry:
                    for key in ("title", "purpose"):
                        w, sw, h, sh = card[key]
                        assert sw <= w + 1 and sh <= h + 1, (key, card)
                    assert all(
                        t["width"] >= 44 and t["height"] >= 44 and t["name"]
                        for t in card["targets"]
                    ), card
                if page.evaluate("innerWidth") <= 720:
                    assert len({round(card["x"]) for card in geometry}) == 1, geometry
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), geometry
                return geometry

            original = context.request.get(base + "/api/skills/plan-my-day").json()
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=skills", wait_until="networkidle")
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
                    page.wait_for_function("innerWidth === 640 && devicePixelRatio === 2")

                starters = [
                    "plan-my-day",
                    "break-down-project",
                    "email-draft",
                    "explain-simply",
                    "compare-options",
                    "proofread-polish",
                ]
                cards = page.locator("#skl-grid .skl-card")
                start = page.locator('[data-cat="start"]')
                all_skills = page.locator('[data-cat="all"]')
                search = page.locator("#skl-search")
                installed = context.request.get(base + "/api/skills").json()
                count = len(installed)
                expect(start).to_have_attribute("aria-pressed", "true")
                expect(cards).to_have_count(6)
                expect(page.locator("#skl-rail [data-cat]")).to_have_count(2)
                assert cards.evaluate_all("nodes=>nodes.map(n=>n.dataset.slug)") == starters
                row["installed_at_start"] = count
                shot("start")
                opener = page.get_by_role("button", name="open Plan My Day", exact=True)
                opener.press("Enter")
                drawer = page.get_by_role("dialog", name="edit skill", exact=True)
                expect(drawer).to_be_visible()
                assert len(page.locator("#skl-d-body").input_value()) > 20
                page.keyboard.press("Escape")
                expect(opener).to_be_focused()
                all_skills.press("Enter")
                expect(cards).to_have_count(count)
                expect(all_skills).to_be_focused()
                coding = page.locator('[data-cat="coding"]')
                coding.press("Enter")
                expect(cards).to_have_count(
                    sum(skill.get("category") == "coding" for skill in installed)
                )
                expect(coding).to_be_focused()
                start.press("Enter")
                expect(cards).to_have_count(6)
                expect(start).to_be_focused()
                expect(coding).to_have_count(0)
                search.fill("Accessibility Pass")
                other = page.locator('.skl-card[data-slug="accessibility-pass"]')
                expect(other).to_be_visible()
                expect(search).to_be_focused()
                other.get_by_role("button", name="open Accessibility Pass", exact=True).press(
                    "Enter"
                )
                expect(drawer).to_be_visible()
                page.keyboard.press("Escape")
                search.fill("")
                expect(cards).to_have_count(6)
                page.locator("#skl-new").press("Enter")
                page.locator("#skl-d-name").fill(name)
                page.locator("#skl-d-desc").fill(purpose)
                page.locator("#skl-d-when").fill("before leaving home")
                page.locator("#skl-d-body").fill("check the list and keep the receipt")
                page.locator("#skl-d-save").press("Enter")
                expect(page.locator("#skl-d-heading")).to_have_text("edit skill")
                own = page.get_by_role("button", name="open " + name, exact=True)
                expect(own).to_have_count(1)
                slug = own.locator("../..").get_attribute("data-slug")
                page.keyboard.press("Escape")
                expect(page.locator("#skl-new")).to_be_focused()
                page.reload(wait_until="networkidle")
                expect(own).to_be_visible()
                expect(cards).to_have_count(7)
                own_card = page.locator(f'.skl-card[data-slug="{slug}"]')
                expect(own_card.locator(".skl-card-desc")).to_have_text(purpose)
                row["long_choices"] = choices()
                own.scroll_into_view_if_needed()
                shot("full-choice")
                own.press("Enter")
                expect(drawer).to_be_visible()
                expect(page.locator("#skl-d-name")).to_have_value(name)
                expect(page.locator("#skl-d-desc")).to_have_value(purpose)
                page.locator("#skl-d-body").fill(saved_body)
                save = page.locator("#skl-d-save")
                edit_endpoint = base + "/api/skills/" + slug

                def refused_save(route):
                    route.fulfill(status=503, json={"detail": "synthetic local save unavailable"})

                page.route(edit_endpoint, refused_save)
                save.press("Enter")
                expect(page.locator(".toast.error").last).to_contain_text("save failed")
                expect(save).to_be_focused()
                expect(page.locator("#skl-d-body")).to_have_value(saved_body)
                expect(page.locator("#skl-d-desc")).to_have_value(purpose)
                assert (
                    context.request.get(edit_endpoint).json()["body"]
                    == "check the list and keep the receipt"
                )
                shot("edit-rejected")
                page.unroute(edit_endpoint, refused_save)
                save.press("Enter")
                expect(page.locator("#skl-d-status")).to_have_text("saved")
                expect(own).to_have_count(1)
                page.keyboard.press("Escape")
                expect(own).to_be_focused()
                assert context.request.get(edit_endpoint).json()["body"] == saved_body
                page.reload(wait_until="networkidle")
                own.press("Enter")
                expect(page.locator("#skl-d-body")).to_have_value(saved_body)
                expect(page.locator("#skl-d-desc")).to_have_value(purpose)
                page.keyboard.press("Escape")
                expect(own).to_be_focused()
                delete = own_card.get_by_role("button", name="delete skill " + name, exact=True)
                delete.press("Enter")
                page.get_by_role("alertdialog").get_by_role(
                    "button", name="cancel", exact=True
                ).press("Enter")
                expect(delete).to_be_focused()
                assert context.request.get(edit_endpoint).json()["body"] == saved_body
                row["edit_recovery"] = (
                    "read full title and purpose, exact fields, local refusal retains draft/focus, retry same record, reload, delete cancel without write/source focus"
                )
                shot("saved-choice")
                all_skills.press("Enter")
                pin = page.locator('.skl-card[data-slug="accessibility-pass"] .skl-pin')
                search.fill("Accessibility Pass")
                expect(cards).to_have_count(1)
                endpoint = base + "/api/skills/accessibility-pass/pin"

                def fail_pin(route):
                    route.fulfill(status=503, json={"detail": "synthetic pin unavailable"})

                page.route(endpoint, fail_pin)
                pin.press("Enter")
                expect(page.locator(".toast.error").last).to_have_text(
                    "pin not confirmed. try again."
                )
                expect(pin).to_be_focused()
                expect(pin).to_have_attribute("aria-disabled", "false")
                page.unroute(endpoint, fail_pin)
                held = []

                def hold_pin(route):
                    held.append(route)

                page.route(endpoint, hold_pin)
                pin.press("Enter")
                expect(pin).to_have_attribute("aria-busy", "true")
                search.fill("Accessibilit")
                pin.focus()
                page.wait_for_timeout(250)  # let search replace the card while the pin is pending
                expect(pin).to_be_focused()
                expect(pin).to_have_attribute("aria-disabled", "true")
                pin.press("Enter")
                assert len(held) == 1
                response = held[0].fetch()
                assert response.ok
                held.pop().fulfill(response=response)
                page.unroute(endpoint, hold_pin)
                expect(pin).to_have_attribute("aria-pressed", "true")
                expect(pin).to_be_focused()
                expect(pin).to_have_attribute("aria-disabled", "false")
                start.press("Enter")
                search.fill("")
                expect(cards).to_have_count(8)
                expect(pin).to_be_visible()
                expect(own).to_be_visible()
                shot("personal-and-pinned")
                pin.press("Enter")
                expect(pin).to_have_count(0)
                expect(start).to_be_focused()
                expect(cards).to_have_count(7)
                library = page.locator('.skl-rail-act[data-act="library"]')
                library.press("Enter")
                expect(page.locator('[data-src="builtin"]')).to_be_visible()
                expect(library).to_be_focused()
                expect(cards).to_have_count(count)
                preview = page.get_by_role("button", name="open Plan My Day", exact=True)
                preview.press("Enter")
                expect(page.get_by_role("dialog", name="Plan My Day", exact=True)).to_be_visible()
                page.keyboard.press("Escape")
                expect(preview).to_be_focused()
                library.press("Enter")
                expect(start).to_be_visible()
                expect(library).to_be_focused()
                start.press("Enter")
                search.fill("no such owned procedure 991122")
                expect(cards).to_have_count(0)
                expect(page.locator(".skl-empty")).to_have_text("no matches")
                expect(search).to_be_focused()
                search.fill("")
                expect(own).to_be_visible()
                assert (
                    context.request.get(base + "/api/skills/" + slug).json()["body"] == saved_body
                )
                assert context.request.delete(base + "/api/skills/" + slug).ok
                assert context.request.delete(base + "/api/skills/plan-my-day").ok
                page.reload(wait_until="networkidle")
                expect(cards).to_have_count(5)
                assert all(
                    s["slug"] != "plan-my-day"
                    for s in context.request.get(base + "/api/skills").json()
                )
                assert context.request.post(
                    base + "/api/skills",
                    data={k: original[k] for k in ["name", "description", "when_to_use", "body"]},
                ).ok
                partial = [skill for skill in installed if skill["slug"] not in starters]
                page.route(base + "/api/skills", lambda route: route.fulfill(json=partial))
                page.reload(wait_until="networkidle")
                expect(cards).to_have_count(0)
                expect(page.locator(".skl-empty")).to_contain_text("choose all, search, or create")
                all_skills.press("Enter")
                expect(cards).to_have_count(len(partial))
                expect(all_skills).to_be_focused()
                page.unroute(base + "/api/skills")
                page.reload(wait_until="networkidle")
                expect(cards).to_have_count(6)
                assert len(context.request.get(base + "/api/skills").json()) == count
                assert not errors, errors
                assert len(console) == 2 and all("503" in message for message in console), console
                assert not external, external
                row.update(status="passed", starting_count=6, personal_count=7, pinned_count=8)
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
                shot("failure")
            finally:
                try:
                    remaining = context.request.get(base + "/api/skills").json()
                    for skill in remaining:
                        if skill["name"] == name:
                            assert context.request.delete(base + "/api/skills/" + skill["slug"]).ok
                    assert context.request.post(
                        base + "/api/skills/accessibility-pass/pin", data={"pinned": False}
                    ).ok
                    if not any(skill["slug"] == "plan-my-day" for skill in remaining):
                        assert context.request.post(
                            base + "/api/skills",
                            data={
                                key: original[key]
                                for key in ["name", "description", "when_to_use", "body"]
                            },
                        ).ok
                except Exception as error:
                    row.update(status="failed", cleanup_error=str(error))
                row.update(page_errors=errors, console_errors=console, external=external)
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
