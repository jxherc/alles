"""Owned Files previews and Gallery date-filter workflows in both motion modes."""

from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import struct
import sys
import traceback
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

PROFILES = [(w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")]
PROFILES += [(1440, t, True) for t in ("light", "dark")]
TEXT = "preview résumé — 会议\nthis is the selected synthetic file."
FIXTURE_DATE = datetime.now(UTC)
FIXTURE_MONTH = FIXTURE_DATE.strftime("%Y-%m")
FIXTURE_MONTH_LABEL = FIXTURE_DATE.strftime("%B %Y")
FILTER_DAY = f"{FIXTURE_MONTH}-22"


def image_bytes(color):
    stream = io.BytesIO()
    Image.new("RGB", (96, 64), color).save(stream, format="PNG")
    return stream.getvalue()


def run():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text() == run_id
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    require_server_ownership(base, run_id)
    database = Path(os.environ.get("ALLES_DB", data / "aide.db")).resolve()
    assert data in database.parents and database.is_file(), "Gallery fixture database must be owned"
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    files = data / "files"
    files.mkdir(exist_ok=True)
    (files / "preview-résumé.txt").write_text(TEXT)
    (files / "preview-photo.png").write_bytes(image_bytes("#325b82"))
    with wave.open(str(files / "preview-audio.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 1600)
    records, gallery_ids = [], {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in PROFILES:
                for motion in ("reduce", "no-preference"):
                    label = f"{width}-{theme}-{'native200-' if zoom else ''}{motion}"
                    row = {"profile": label, "status": "failed", "previews": []}
                    records.append(row)
                    options = dict(
                        viewport={"width": width, "height": 844 if width == 390 else 900},
                        timezone_id="UTC",
                        has_touch=width == 390,
                        service_workers="block",
                        reduced_motion=motion,
                    )
                    if zoom:
                        profile = data / ("preview-" + label)
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
                    events = {
                        key: []
                        for key in ("external", "websockets", "page", "console", "http", "failed")
                    }

                    def boundary(route):
                        target = urlsplit(route.request.url)
                        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                            events["external"].append(route.request.url)
                            return route.abort()
                        return route.continue_()

                    context.route("**/*", boundary)
                    context.route_web_socket(
                        "**/*", lambda ws: (events["websockets"].append(ws.url), ws.close())
                    )
                    page = context.new_page()
                    page.set_default_timeout(5000)
                    page.on("pageerror", lambda error: events["page"].append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            events["console"].append(message.text)
                            if message.type == "error"
                            else None
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: (
                            events["http"].append(
                                {
                                    "url": response.url,
                                    "status": response.status,
                                }
                            )
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: events["failed"].append(
                            {
                                "url": request.url,
                                "failure": request.failure,
                            }
                        ),
                    )

                    def api(method, path, payload=None, **kwargs):
                        assert path.startswith("/api/") and not path.startswith("//")
                        response = context.request.fetch(
                            base + path, method=method, data=payload, max_redirects=0, **kwargs
                        )
                        assert response.ok, (path, response.status, response.text())
                        return response

                    def capture(name):
                        session = context.new_cdp_session(page)
                        try:
                            raw = base64.b64decode(
                                session.send(
                                    "Page.captureScreenshot",
                                    {
                                        "format": "png",
                                        "captureBeyondViewport": False,
                                    },
                                )["data"]
                            )
                            assert struct.unpack(">II", raw[16:24]) == (
                                width,
                                844 if width == 390 else 900,
                            )
                            (out / f"{label}-{name}.png").write_bytes(raw)
                        finally:
                            session.detach()

                    def visible_hit(locator):
                        expect(locator).to_be_visible()
                        value = locator.evaluate("""e => {
                          const r=e.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
                          const hit=document.elementFromPoint(x,y);
                          return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
                            viewportWidth:innerWidth,viewportHeight:innerHeight,
                            hit:hit?.outerHTML,clear:!!hit&&(hit===e||e.contains(hit))};
                        }""")
                        assert value["left"] >= 0 and value["right"] <= value["viewportWidth"] + 1
                        assert value["top"] >= 0 and value["bottom"] <= value["viewportHeight"] + 1
                        assert value["clear"], value
                        return value

                    def gallery_result(expected, query):
                        expect(page.locator("#photos-grid .photos-cell")).to_have_count(
                            len(expected)
                        )
                        page.wait_for_function(
                            "ids => JSON.stringify([...document.querySelectorAll('#photos-grid .photos-cell')].map(e=>e.dataset.id).sort())===JSON.stringify(ids.sort())",
                            arg=list(expected),
                        )
                        response = api("GET", "/api/photos/list?" + query)
                        actual = {
                            item["id"]
                            for group in response.json()["moments"]
                            for item in group["items"]
                        }
                        assert actual == set(expected), response.json()
                        return {"query": query, "ids": sorted(actual), "readback": response.json()}

                    def pick_date(control_id, day):
                        control = page.locator("#" + control_id)
                        expect(control).to_have_attribute("role", "button")
                        expect(control).to_have_attribute("data-dp-ready", "1")
                        assert control.evaluate("e=>e.tagName") == "DIV"
                        control.press("Enter")
                        panel = page.get_by_role(
                            "dialog",
                            name=(
                                "photos from date"
                                if control_id.endswith("from")
                                else "photos to date"
                            ),
                            exact=True,
                        )
                        expect(panel).to_be_visible()
                        for _ in range(24):
                            if panel.locator(".dp-head span").inner_text() == FIXTURE_MONTH_LABEL:
                                break
                            panel.locator('[data-nav="-1"]').press("Enter")
                        else:
                            raise AssertionError("owned fixture month was not reachable")
                        panel.locator(f'.dp-day[data-d="{day}"]').press("Enter")
                        expect(panel).to_have_count(0)
                        expect(control).to_be_focused()
                        assert control.evaluate("e=>e.value") == f"{FIXTURE_MONTH}-{day:02}"

                    try:
                        api("POST", "/api/setup/dismiss")
                        api(
                            "PATCH",
                            "/api/settings",
                            {
                                "language": "en",
                                "region": "US",
                                "insights_enabled": False,
                                "user_model_distill": False,
                            },
                        )
                        api("PUT", "/api/appearance", from_legacy(theme, None))
                        if not gallery_ids:
                            for day, color in ((21, "#b76532"), (22, "#327452"), (23, "#325b82")):
                                result = api(
                                    "POST",
                                    "/api/photos/upload",
                                    multipart={
                                        "file": {
                                            "name": f"gallery-{day}.png",
                                            "mimeType": "image/png",
                                            "buffer": image_bytes(color),
                                        }
                                    },
                                ).json()
                                gallery_ids[day] = result["id"]
                            with sqlite3.connect(database) as db:
                                for day, photo_id in gallery_ids.items():
                                    db.execute(
                                        "UPDATE photos SET taken_at=? WHERE id=?",
                                        (
                                            f"{FIXTURE_MONTH}-{day:02} 12:00:00.000000",
                                            photo_id,
                                        ),
                                    )
                        page.goto(base + "/?view=files", wait_until="networkidle")
                        if zoom:
                            worker = (
                                context.service_workers[0]
                                if context.service_workers
                                else (context.wait_for_event("serviceworker"))
                            )
                            row["native_zoom"] = worker.evaluate(
                                """async base => {
                              const tab=(await chrome.tabs.query({})).find(t=>{try{return new URL(t.url).origin===base}catch{return false}});
                              await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);
                            }""",
                                base,
                            )
                            assert row["native_zoom"] == 2
                            page.wait_for_function(
                                "innerWidth===720&&innerHeight===450&&devicePixelRatio===2&&visualViewport.scale===1"
                            )
                        row["viewport"] = (
                            page.evaluate("""() => ({width:innerWidth,height:innerHeight,
                          dpr:devicePixelRatio,visualScale:visualViewport.scale,
                          cssZoom:getComputedStyle(document.documentElement).zoom,
                          theme:document.documentElement.dataset.theme,
                          paletteBg:getComputedStyle(document.documentElement).getPropertyValue("--bg").trim(),
                          paletteText:getComputedStyle(document.documentElement).getPropertyValue("--text").trim(),
                          reduced:matchMedia('(prefers-reduced-motion:reduce)').matches})""")
                        )
                        assert row["viewport"]["theme"] == ("light" if theme == "light" else None)
                        assert (
                            row["viewport"]["paletteBg"] == from_legacy(theme, None)["colors"]["bg"]
                        )
                        assert (
                            row["viewport"]["paletteText"]
                            == from_legacy(theme, None)["colors"]["text"]
                        )
                        assert row["viewport"]["reduced"] == (motion == "reduce")
                        for filename, selector in (
                            ("preview-résumé.txt", ".files-preview-pre"),
                            ("preview-photo.png", "img"),
                            ("preview-audio.wav", "audio"),
                        ):
                            entry = page.locator(f'.file-row[data-path="{filename}"]')
                            entry.locator("[data-file-select]").press("Space")
                            expect(entry.locator("[data-file-select]")).to_have_attribute(
                                "aria-checked", "true"
                            )
                            entry.locator("[data-file-open]").press("Enter")
                            details = page.locator("#files-detail-panel")
                            expect(details).to_be_visible()
                            expect(details.locator(".files-detail-name")).to_have_text(filename)
                            opener = details.locator('[data-detail-action="open"]')
                            opener.press("Enter")
                            modal = page.locator("#files-preview-modal")
                            expect(modal).to_be_visible()
                            expect(page.locator("#files-preview-close")).to_be_focused()
                            media = modal.locator("#files-preview-body").locator(selector)
                            if selector == "img":
                                page.wait_for_function(
                                    "document.querySelector('#files-preview-body img')?.naturalWidth>0"
                                )
                            elif selector == "audio":
                                page.wait_for_function(
                                    "document.querySelector('#files-preview-body audio')?.readyState>=2"
                                )
                            else:
                                expect(media).to_have_text(TEXT)
                            page.wait_for_timeout(1200)
                            observation = {"file": filename, "hit": visible_hit(media)}
                            capture(filename)
                            for _ in range(5):
                                page.keyboard.press("Tab")
                                assert page.evaluate(
                                    "document.querySelector('#files-preview-modal').contains(document.activeElement)"
                                )
                            page.keyboard.press("Escape")
                            expect(modal).to_be_hidden()
                            expect(opener).to_be_focused()
                            expect(details).to_be_visible()
                            expect(entry.locator("[data-file-select]")).to_have_attribute(
                                "aria-checked", "true"
                            )
                            observation["focus_return"] = True
                            row["previews"].append(observation)
                            page.locator("#files-detail-close").press("Enter")
                            expect(entry).to_be_focused()
                            entry.locator("[data-file-select]").press("Space")
                        page.goto(base + "/?view=photos", wait_until="networkidle")
                        page.locator("#photos-filter-btn").press("Enter")
                        expect(page.locator("#photos-filterbar")).to_be_visible()
                        assert page.locator('#photos-filterbar input[type="date"]').count() == 0
                        queries = []
                        page.on(
                            "request",
                            lambda request: (
                                queries.append(parse_qs(urlsplit(request.url).query))
                                if urlsplit(request.url).path == "/api/photos/list"
                                else None
                            ),
                        )
                        row["gallery"] = [gallery_result(gallery_ids.values(), "")]
                        for _ in range(30):
                            page.keyboard.press("Tab")
                            if page.locator("#photos-filt-from").evaluate(
                                "e=>document.activeElement===e"
                            ):
                                break
                        else:
                            raise AssertionError("from-date picker was not keyboard reachable")
                        row["date_control_hit"] = visible_hit(page.locator("#photos-filt-from"))
                        assert page.locator("#photos-filt-from").evaluate(
                            "e=>e.matches(':focus-visible')&&e.getBoundingClientRect().height>=44"
                        )
                        pick_date("photos-filt-from", 22)
                        row["gallery"].append(
                            gallery_result([gallery_ids[22], gallery_ids[23]], f"from={FILTER_DAY}")
                        )
                        page.keyboard.press("Tab")
                        expect(page.locator("#photos-filt-to")).to_be_focused()
                        pick_date("photos-filt-to", 22)
                        row["gallery"].append(
                            gallery_result([gallery_ids[22]], f"from={FILTER_DAY}&to={FILTER_DAY}")
                        )
                        assert any(
                            q.get("from") == [FILTER_DAY] and q.get("to") == [FILTER_DAY]
                            for q in queries
                        )
                        capture("gallery-range")
                        page.locator("#photos-filt-to").press("Space")
                        expect(page.locator(".date-panel")).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(page.locator("#photos-filt-to")).to_be_focused()
                        expect(page.locator("#photos-filt-to")).to_have_attribute(
                            "data-value", FILTER_DAY
                        )
                        page.locator("#photos-filt-from").press("Enter")
                        page.locator(".date-panel .dp-clear").press("Enter")
                        expect(page.locator("#photos-filt-from")).to_be_focused()
                        row["gallery"].append(
                            gallery_result([gallery_ids[21], gallery_ids[22]], f"to={FILTER_DAY}")
                        )
                        page.locator("#photos-filt-clear").press("Enter")
                        assert page.locator("#photos-filt-from").evaluate("e=>e.value") == ""
                        assert page.locator("#photos-filt-to").evaluate("e=>e.value") == ""
                        row["gallery"].append(gallery_result(gallery_ids.values(), ""))
                        capture("gallery-cleared")
                        assert not page.evaluate(
                            "document.documentElement.scrollWidth>innerWidth+1"
                        )
                        assert all(not value for value in events.values()), events
                        assert (files / "preview-résumé.txt").read_text() == TEXT
                        row["status"] = "passed"
                    except Exception:
                        row["failure"] = traceback.format_exc()
                        capture("failed")
                    finally:
                        row["events"] = events
                        context.close()
                        (out / "outcomes.json").write_text(json.dumps(records, indent=2) + "\n")
                    print(label, row["status"], flush=True)
        finally:
            browser.close()
    assert len(records) == 16 and all(row["status"] == "passed" for row in records), records


if __name__ == "__main__":
    run()
