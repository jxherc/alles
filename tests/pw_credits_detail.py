"""Selected Credits detail stays reachable with the full public manifest."""

import base64
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from pw_settings_helpers import choose_settings_section  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

METRICS = """() => {
  const rect = el => { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}; };
  const detail=document.querySelector('#credits-detail'), row=document.querySelector('.credits-row[aria-current="true"]'),
    content=document.querySelector('#settings-modal .s-content'), heading=detail.querySelector('h3');
  return {compact:matchMedia('(max-width:860px)').matches, viewport:[innerWidth,innerHeight,devicePixelRatio],
    rows:document.querySelectorAll('.credits-row').length, parent:detail.parentElement.id,
    adjacent:row?.nextElementSibling===detail, row:row&&rect(row), detail:rect(detail), heading:heading&&rect(heading),
    content:rect(content), focused:document.activeElement===row,
    horizontalOverflow:document.documentElement.scrollWidth>innerWidth || content.scrollWidth>content.clientWidth};
}"""


def owned_context(pw, width, theme, zoom):
    profile = Path(os.environ["ALLES_DATA"]) / f"credits-{width}-{theme}-{zoom}"
    options = {
        "viewport": {"width": width, "height": 900},
        "service_workers": "block",
        "reduced_motion": "reduce" if theme == "dark" else "no-preference",
        "has_touch": width == 390,
        "is_mobile": width == 390,
    }
    args = []
    if zoom:
        extension = profile / "extension"
        extension.mkdir(parents=True)
        (extension / "manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": 3,
                    "name": "owned zoom",
                    "version": "1.0",
                    "permissions": ["tabs"],
                    "background": {"service_worker": "zoom.js"},
                }
            )
        )
        (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
        args = [f"--disable-extensions-except={extension}", f"--load-extension={extension}"]
    return pw.chromium.launch_persistent_context(
        profile / "browser", channel="chromium", headless=True, args=args, **options
    )


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    count = len(json.loads((ROOT / "credits/manifest.json").read_text())["entries"])
    assert count >= 496
    profiles = [(w, t, False) for w in (1440, 768, 390) for t in ("light", "dark")]
    profiles += [(1440, t, True) for t in ("light", "dark")]
    rows = []
    with sync_playwright() as pw:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            row = {
                "profile": label,
                "status": "failed",
                "page_errors": [],
                "console_errors": [],
                "external": [],
                "checkpoints": [],
            }
            rows.append(row)
            context = owned_context(pw, width, theme, zoom)
            held = []
            mode = {"failure": "", "hold": ""}

            def boundary(route):
                url = urlsplit(route.request.url)
                if url.scheme + "://" + url.netloc != base:
                    row["external"].append(route.request.url)
                    return route.abort()
                if mode["failure"] and url.path.endswith("/" + mode["failure"]):
                    mode["failure"] = ""
                    return route.fulfill(
                        status=503, json={"detail": "owned credit detail unavailable"}
                    )
                if mode["hold"] and url.path.endswith("/" + mode["hold"]):
                    held.append(route)
                    return None
                return route.continue_()

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda err: row["page_errors"].append(str(err)))
            page.on(
                "console",
                lambda msg: row["console_errors"].append(msg.text) if msg.type == "error" else None,
            )

            def capture(name):
                metrics = page.evaluate(METRICS)
                assert not metrics["horizontalOverflow"], metrics
                row["checkpoints"].append({"name": name, **metrics})
                cdp = context.new_cdp_session(page)
                try:
                    png = base64.b64decode(
                        cdp.send(
                            "Page.captureScreenshot",
                            {"format": "png", "captureBeyondViewport": False},
                        )["data"]
                    )
                finally:
                    cdp.detach()
                (out / f"{label}-{name}.png").write_bytes(png)
                return metrics

            def select(target, keyboard=False):
                name = target.locator("strong").inner_text()
                target.press(
                    "Enter"
                ) if keyboard else target.tap() if width == 390 else target.click()
                expect(target).to_be_focused()
                expect(target).to_have_attribute("aria-controls", "credits-detail")
                return name

            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                assert context.request.put(
                    base + "/api/appearance", data=from_legacy(theme, None)
                ).ok
                page.goto(base + "/?view=today", wait_until="networkidle")
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
                    page.wait_for_function(
                        "innerWidth===720 && innerHeight===450 && devicePixelRatio===2"
                    )
                page.locator("#today-settings").click()
                choose_settings_section(page, "credits", touch=width == 390)
                expect(page.locator("#credits-settings-workbench")).to_have_attribute(
                    "aria-busy", "false"
                )
                expect(page.locator(".credits-row")).to_have_count(count)
                expect(page.locator("#credits-detail h3")).to_have_count(1)
                second = page.locator(".credits-row").nth(1)
                name = select(second, keyboard=width != 390)
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                state = capture("selected")
                if state["compact"]:
                    assert state["adjacent"] and state["parent"] == "credits-list", state
                assert state["heading"]["y"] >= state["content"]["y"] - 1, state
                assert state["heading"]["bottom"] <= state["content"]["bottom"] + 1, state
                # The next Tab reaches this selected detail, not the next 494 rows.
                if state["compact"]:
                    page.keyboard.press("Tab")
                    expect(page.locator("#credits-detail .credits-source")).to_be_focused()
                search = page.locator("#credits-search")
                search.fill("xterm")
                expect(search).to_be_focused()
                expect(page.locator(".credits-row")).to_have_count(2)
                name = select(page.locator('[data-credit-id="xterm-js"]'))
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                page.locator("#credits-detail .credits-license summary").first.press("Enter")
                expect(page.locator("#credits-detail .credits-license pre").first).to_be_visible()
                capture("license")
                search.fill("no such dependency")
                expect(search).to_be_focused()
                expect(page.locator(".credits-row")).to_have_count(0)
                expect(page.locator("#credits-detail")).to_contain_text(
                    "No credits match this search."
                )
                search.fill("")
                expect(page.locator(".credits-row")).to_have_count(count)
                all_tab = page.locator('[data-credit-category="all"]')
                all_tab.press("ArrowRight")
                expect(page.locator('[data-credit-category="code"]')).to_be_focused()
                page.keyboard.press("Home")
                expect(all_tab).to_be_focused()
                expect(page.locator(".credits-row")).to_have_count(count)
                third = page.locator(".credits-row").nth(2)
                mode["failure"] = third.get_attribute("data-credit-id")
                name = select(third)
                expect(page.locator("[data-credit-detail-retry]")).to_be_visible()
                page.locator("[data-credit-detail-retry]").press("Enter")
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                fourth = page.locator(".credits-row").nth(3)
                entry_id = fourth.get_attribute("data-credit-id")
                saved_detail = context.request.get(base + "/api/credits/" + entry_id).json()
                mode["hold"] = entry_id
                select(fourth)
                expect(page.locator("#credits-detail")).to_contain_text("loading")
                assert len(held) == 1
                fifth = page.locator(".credits-row").nth(4)
                name = select(fifth)
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                mode["hold"] = ""
                held.pop().fulfill(json=saved_detail)
                page.wait_for_load_state("networkidle")
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                capture("recovered")
                page.locator("#settings-modal-close").click()
                expect(page.locator("#today-settings")).to_be_focused()
                page.locator("#today-settings").click()
                choose_settings_section(page, "credits", touch=width == 390)
                expect(page.locator("#credits-settings-workbench")).to_have_attribute(
                    "aria-busy", "false"
                )
                expect(page.locator("#credits-detail h3")).to_have_text(name)
                assert not row["page_errors"] and not row["external"], row
                assert len(row["console_errors"]) == 1 and "503" in row["console_errors"][0], row
                row["status"] = "passed"
            except Exception:
                row["error"] = traceback.format_exc()
                try:
                    capture("failure")
                except Exception:
                    pass
                raise
            finally:
                for route in held:
                    route.abort()
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    run()
