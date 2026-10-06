"""Saved search -> confirmed Library record -> reload and browser back.

Only search output is synthetic. Search snapshots and reading records use the
owned application's real APIs. Run through an owned browser gate runner.
"""

import json
import os
import struct
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy

PROFILES = [(w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")]
PROFILES += [(1440, t, True) for t in ("light", "dark")]
PROFILES = [
    (width, theme, zoom, category)
    for width, theme, zoom in PROFILES
    for category in ("all", "news")
]


def owned_context(pw, width, theme, zoom, label):
    root = Path(os.environ["ALLES_DATA"]) / label
    root.mkdir()
    extension = root / "extension"
    extension.mkdir()
    (extension / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "name": "owned native zoom",
                "version": "1.0",
                "permissions": ["tabs"],
                "background": {"service_worker": "zoom.js"},
            }
        )
    )
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
        root / "browser",
        channel="chromium",
        headless=True,
        viewport={"width": width, "height": 844 if width == 390 else 900},
        device_scale_factor=1,
        color_scheme=theme,
        service_workers="block",
        reduced_motion="reduce",
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
            "--disable-background-networking",
            "--disable-component-update",
            "--no-first-run",
        ],
    )


def run(configure_context=None, profiles=PROFILES):
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert (data / ".alles-test-owner").read_text() == os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        for width, theme, zoom, category in profiles:
            label = (
                f"{width}-{theme}"
                + ("-native200" if zoom else "")
                + ("-news" if category == "news" else "")
            )
            context = owned_context(pw, width, theme, zoom, label)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            errors, console, denied, writes, searches = [], [], [], [], []
            title = "Synthetic local reading result"
            excerpt = "Explicit synthetic result for UI review. No web search was performed."
            result_url = base + "/synthetic-result?profile=" + label
            fixture = {
                "query": "synthetic reading",
                "status": "partial",
                "provider": "explicit local fixture",
                "normal_results_enabled": True,
                "category": category,
                "overview_requested": False,
                "used_no_ai": True,
                "elapsed_ms": 0,
                "has_more": False,
                "results": [
                    {
                        "title": title,
                        "url": result_url,
                        "snippet": excerpt,
                        "source": "local fixture",
                    }
                ],
            }
            row = {"profile": label, "status": "failed", "fixture": fixture, "category": category}
            rows.append(row)

            def boundary(route):
                request = route.request
                url = urlsplit(request.url)
                if (url.scheme, url.netloc) != (origin.scheme, origin.netloc):
                    denied.append(request.url)
                    return route.abort()
                if url.path.startswith("/synthetic-result") or url.path.endswith("/fetch-text"):
                    denied.append(request.url)
                    return route.abort()
                if url.path == "/api/andromeda/search":
                    searches.append(request.post_data_json)
                    return route.fulfill(
                        json={**fixture, "category": request.post_data_json["category"]}
                    )
                if url.path.startswith("/api/andromeda/") and not (
                    url.path.startswith("/api/andromeda/saved")
                    or url.path == "/api/andromeda/providers"
                ):
                    denied.append(request.url)
                    return route.abort()
                if url.path in {"/api/read/save-result", "/api/read/save-news"}:
                    writes.append(request.post_data_json)
                return route.continue_()

            context.route("**/*", boundary)
            context.route_web_socket("**/*", lambda ws: ws.close())
            if configure_context:
                configure_context(context)
            page = context.new_page()
            page.set_default_timeout(4500)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
            )
            api = context.request

            def records():
                items = []
                for suffix in ("", "?filter=archived"):
                    response = api.get(base + "/api/read" + suffix, max_redirects=0)
                    assert response.ok
                    items.extend(response.json()["items"])
                return [item for item in items if item["url"] == result_url]

            def capture(name):
                path = out / f"{label}-{name}.png"
                page.screenshot(path=str(path))
                assert struct.unpack(">II", path.read_bytes()[16:24]) == (
                    width,
                    844 if width == 390 else 900,
                )

            def open_record(identity):
                button = page.get_by_role("button", name="open in Library: " + title, exact=True)
                expect(button).to_be_visible()
                button.focus()
                expect(button).to_be_focused()
                assert button.bounding_box()["height"] >= 44
                focus = button.evaluate("""button => {
                    const r = button.getBoundingClientRect(), s = getComputedStyle(button);
                    return {x:r.x, y:r.y, width:r.width, height:r.height,
                        viewportWidth:innerWidth, viewportHeight:innerHeight,
                        outlineStyle:s.outlineStyle, outlineWidth:s.outlineWidth};
                }""")
                assert focus["x"] >= 0 and focus["y"] >= 0
                assert focus["x"] + focus["width"] <= focus["viewportWidth"] + 1
                assert focus["y"] + focus["height"] <= focus["viewportHeight"] + 1
                row.setdefault("focus_checks", []).append(focus)
                capture("focused-open-" + str(len(row["focus_checks"])))
                page.keyboard.press("Enter")
                expect(page.locator(".read-article h1")).to_have_text(title)
                expect(page.locator(".read-article")).to_contain_text(excerpt)
                assert parse_qs(urlsplit(page.url).query)["record"] == [identity]
                expect(page.locator("#read-back")).to_be_focused()

            try:
                assert api.post(base + "/api/setup/dismiss", max_redirects=0).ok
                assert api.put(
                    base + "/api/appearance", data=from_legacy(theme, None), max_redirects=0
                ).ok
                page.goto(base + "/?view=andromeda", wait_until="networkidle")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    row["native_zoom"] = worker.evaluate(
                        """async base => {
                        const tab = (await chrome.tabs.query({})).find(t => new URL(t.url).origin === base);
                        await chrome.tabs.setZoom(tab.id, 2);
                        return chrome.tabs.getZoom(tab.id);
                    }""",
                        base,
                    )
                    assert row["native_zoom"] == 2
                    page.wait_for_function(
                        "innerWidth === 720 && innerHeight === 450 && devicePixelRatio === 2"
                    )
                result_title = page.locator(
                    ".andromeda-news-title" if category == "news" else ".andromeda-result-title"
                )
                field = page.locator("#andromeda-query")
                field.fill("synthetic reading !ai")
                field.press("Enter")
                expect(page.locator(".andromeda-result-title")).to_have_text(title)
                if category == "news":
                    news = page.locator('[data-andromeda-category="news"]')
                    expect(news).to_be_visible()
                    news.focus()
                    page.keyboard.press("Enter")
                    expect(news).to_have_attribute("aria-current", "page")
                expect(result_title).to_have_text(title)
                expected_categories = ["all", "news"] if category == "news" else ["all"]
                assert [request["category"] for request in searches] == expected_categories
                assert not records(), "search output is a proposal, not a saved reading item"
                page.locator("#andromeda-save").click()
                page.locator("#andromeda-save-open").click()
                expect(result_title).to_have_text(title)
                page.wait_for_function("new URL(location.href).searchParams.has('saved')")
                saved_url = page.url
                saved_id = parse_qs(urlsplit(saved_url).query)["saved"][0]
                saved_search = api.get(
                    base + "/api/andromeda/saved/" + saved_id, max_redirects=0
                ).json()
                assert saved_search["request"]["category"] == category
                row["saved_search_id"] = saved_id
                assert not records(), "saving a search must not save its reading proposals"
                save = page.get_by_role("button", name="save to Library: " + title, exact=True)
                save.focus()
                page.keyboard.press("Enter")
                opened = page.get_by_role("button", name="open in Library: " + title, exact=True)
                expect(opened).to_be_focused()
                items = records()
                assert len(items) == 1 and not items[0]["read"]
                assert items[0]["source_kind"] == (
                    "saved_news" if category == "news" else "saved_search"
                )
                identity = items[0]["id"]
                stored = api.get(base + "/api/read/" + identity, max_redirects=0).json()
                assert stored["text"] == excerpt and stored["url"] == result_url
                row["record_id"] = identity
                row["before_reload"] = {"items": items, "saved_search": saved_search}
                capture("saved")
                open_record(identity)
                capture("exact-record")
                page.go_back(wait_until="networkidle")
                assert page.url == saved_url
                expect(opened).to_be_visible()
                page.reload(wait_until="networkidle")
                expect(result_title).to_have_text(title)
                row["after_reload_records"] = records()
                assert len(row["after_reload_records"]) == 1
                assert (
                    api.get(base + "/api/andromeda/saved/" + saved_id, max_redirects=0).json()
                    == saved_search
                )
                capture("reload")
                expect(opened).to_be_visible()
                assert len(writes) == 1, "restore must only read; no reconfirmation POST"
                open_record(identity)
                capture("reloaded-exact-record")
                page.go_back(wait_until="networkidle")
                assert page.url == saved_url
                expect(opened).to_be_visible()
                capture("browser-back")
                # Archived records are still saved and must retain their exact destination.
                assert api.patch(
                    base + "/api/read/" + identity, data={"archived": True}, max_redirects=0
                ).ok
                page.reload(wait_until="networkidle")
                expect(opened).to_be_visible()
                open_record(identity)
                page.go_back(wait_until="networkidle")
                assert page.url == saved_url
                assert len(writes) == 1 and len(records()) == 1
                assert [request["category"] for request in searches] == expected_categories
                current = api.get(base + "/api/read/" + identity, max_redirects=0).json()
                assert (
                    current["archived"]
                    and not current["read"]
                    and current["text"] == stored["text"]
                )
                # Deleting a saved record removes the destination on the next reload.
                assert api.delete(base + "/api/read/" + identity, max_redirects=0).ok
                page.reload(wait_until="networkidle")
                expect(save).to_be_visible()
                expect(opened).to_have_count(0)
                assert not records() and len(writes) == 1
                assert [request["category"] for request in searches] == expected_categories
                assert (
                    api.get(base + "/api/andromeda/saved/" + saved_id, max_redirects=0).json()
                    == saved_search
                )
                row["rendered"] = page.evaluate("""() => ({
                    width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
                    theme: document.documentElement.dataset.theme || 'dark',
                    overflow: document.documentElement.scrollWidth > innerWidth + 1,
                    reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
                    appWorker: !!navigator.serviceWorker.controller,
                })""")
                assert row["rendered"]["theme"] == theme
                assert row["rendered"]["reduced"] and not row["rendered"]["overflow"]
                assert not row["rendered"]["appWorker"]
                assert not errors and not console and not denied, (errors, console, denied)
                row["status"] = "passed"
            except Exception:
                row["traceback"] = traceback.format_exc()
            finally:
                row.update(
                    errors=errors, console=console, denied=denied, writes=writes, searches=searches
                )
                capture("final")
                context.tracing.stop(path=str(out / f"{label}.zip"))
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows))
    return all(row["status"] == "passed" for row in rows)


if __name__ == "__main__":
    raise SystemExit(not run())
