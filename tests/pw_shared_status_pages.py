"""Public share access/recovery: owned server, both themes, touch, keyboard and browser zoom."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_gate_safety import require_server_ownership


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    profiles = [(w, theme, False) for w in (1440, 768, 390) for theme in ("dark", "light")]
    profiles += [(1440, theme, True) for theme in ("dark", "light")]
    if "--red" in sys.argv:
        profiles = [(390, "dark", False)]
    rows = []
    with sync_playwright() as pw:
        for width, theme, zoom in profiles:
            label = f"{width}-{theme}" + ("-native200" if zoom else "")
            profile = out / label
            profile.mkdir()
            options = {
                "viewport": {"width": width, "height": 900},
                "color_scheme": theme,
                "reduced_motion": "reduce",
                "service_workers": "block",
                "is_mobile": width == 390,
                "has_touch": width == 390,
            }
            browser = None
            if zoom:
                extension = profile / "extension"
                extension.mkdir()
                (extension / "manifest.json").write_text(
                    json.dumps(
                        {
                            "manifest_version": 3,
                            "name": "owned share zoom check",
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
                browser = pw.chromium.launch()
                context = browser.new_context(**options)
            try:
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if urlparse(route.request.url).netloc == urlparse(base).netloc
                        else route.abort()
                    ),
                )
                context.route_web_socket("**/*", lambda socket: socket.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                errors = []
                failed_requests = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("requestfailed", lambda request: failed_requests.append(request.url))
                console_errors = []
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )

                def mint(ref, **extra):
                    response = context.request.post(
                        base + "/api/share", data={"kind": "doc", "ref": ref, **extra}
                    )
                    assert response.ok, response.text()
                    return response.json()["token"]

                token = mint(f"protected-{label}.md", password="synthetic-reader-password")
                expired = mint(f"expired-{label}.md", expires_at="2000-01-01T00:00:00Z")
                normal = mint(f"normal-{label}.md")
                # Owned synthetic files only: the server ownership sentinel was verified above.
                vault = Path(os.environ["ALLES_DATA"]) / "vault"
                vault.mkdir(exist_ok=True)
                for ref in (f"protected-{label}.md", f"normal-{label}.md"):
                    (vault / ref).write_text("# Shared document\n\nSynthetic reader content.")
                page.goto(base + "/s/missing", wait_until="domcontentloaded")
                if zoom:
                    worker = (
                        context.service_workers[0]
                        if context.service_workers
                        else context.wait_for_event("serviceworker")
                    )
                    actual_zoom = worker.evaluate(
                        "async () => {const tab=(await chrome.tabs.query({})).find(t=>t.url.startsWith('http://127.0.0.1:'));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}"
                    )
                    assert actual_zoom == 2
                    page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")

                def capture(state, status, form=False):
                    measurements = page.evaluate("""() => {
                        const controls = [...document.querySelectorAll('input,button')].map(el => {
                            const box=el.getBoundingClientRect(), style=getComputedStyle(el);
                            return {tag:el.tagName, width:box.width, height:box.height, fontSize:style.fontSize};
                        });
                        return {viewport:document.querySelector('meta[name=viewport]')?.content,
                            width:innerWidth, clientWidth:document.documentElement.clientWidth,
                            scrollWidth:document.documentElement.scrollWidth, dpr:devicePixelRatio,
                            background:getComputedStyle(document.body).backgroundColor,
                            lang:document.documentElement.lang, title:document.title,
                            main:document.querySelectorAll('main').length, controls,
                            reducedMotion:matchMedia('(prefers-reduced-motion:reduce)').matches};
                    }""")
                    checks = {
                        "status": status,
                        "viewport": measurements["viewport"]
                        == "width=device-width,initial-scale=1",
                        "no_overflow": measurements["scrollWidth"] <= measurements["clientWidth"],
                        "actual_layout_width": measurements["width"]
                        == (width // 2 if zoom else width),
                        "reduced_motion": measurements["reducedMotion"],
                    }
                    if state != "normal-document":
                        checks.update(
                            {
                                "landmark": measurements["main"] == 1,
                                "language": measurements["lang"] == "en",
                                "title": bool(measurements["title"]),
                                "theme": measurements["background"]
                                == ("rgb(18, 16, 14)" if theme == "dark" else "rgb(248, 246, 243)"),
                            }
                        )
                    if form:
                        password = page.locator("input[type=password]")
                        checks["minimal_input_border"] = password.evaluate(
                            "el=>getComputedStyle(el).borderTopColor === 'rgba(0, 0, 0, 0)'"
                        )
                        password.focus()
                        checks["input_focus_edge"] = password.evaluate(
                            "el=>getComputedStyle(el).outlineStyle === 'none' && getComputedStyle(el).boxShadow.includes('inset')"
                        )
                        checks["named_password"] = (
                            page.get_by_label("password", exact=True).count() == 1
                        )
                        checks["touch_targets"] = all(
                            c["height"] >= 44 and c["width"] >= 44 for c in measurements["controls"]
                        )
                        checks["readable_input"] = all(
                            float(c["fontSize"].removesuffix("px")) >= 16
                            for c in measurements["controls"]
                        )
                    page.screenshot(path=str(out / f"{label}-{state}.png"), full_page=not zoom)
                    row = {
                        "scenario_id": f"share.{state}",
                        "profile": label,
                        "checks": checks,
                        "measurements": measurements,
                        "status": "passed" if all(checks.values()) else "failed",
                    }
                    rows.append(row)
                    return row

                capture(
                    "missing",
                    page.locator("body").inner_text().find("not found or link revoked") >= 0,
                )
                response = page.goto(base + f"/s/{expired}", wait_until="domcontentloaded")
                capture("expired", response.status == 410)
                response = page.goto(base + f"/s/{token}", wait_until="domcontentloaded")
                locked = capture("password", response.status == 401, form=True)
                field = page.locator("input[type=password]")
                field.fill("wrong-password")
                field.press("Tab")
                locked["checks"]["keyboard_button"] = page.locator("button").evaluate(
                    "el=>el===document.activeElement"
                )
                locked["checks"]["visible_focus"] = page.locator("button").evaluate(
                    "el=>getComputedStyle(el).outlineStyle !== 'none'"
                )
                page.screenshot(path=str(out / f"{label}-focus.png"), full_page=not zoom)
                with page.expect_navigation(wait_until="domcontentloaded") as wrong_response:
                    page.keyboard.press("Enter")
                wrong = capture("wrong-password", wrong_response.value.status == 401, form=True)
                wrong["checks"]["associated_error"] = field.evaluate(
                    "el=>el.getAttribute('aria-invalid')==='true' && document.getElementById(el.getAttribute('aria-describedby'))?.getAttribute('role')==='alert'"
                )
                wrong["checks"]["secret_not_echoed"] = field.input_value() == ""
                field.fill("synthetic-reader-password")
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.locator("button").click()
                expect(page.locator(".doc")).to_contain_text("Synthetic reader content")
                wrong["checks"]["retry_succeeds"] = True
                response = page.goto(base + f"/s/{normal}", wait_until="domcontentloaded")
                capture("normal-document", response.status == 200)
                expected_status_errors = ("401 (Unauthorized)", "404 (Not Found)", "410 (Gone)")
                unexpected_console = [
                    msg
                    for msg in console_errors
                    if not any(code in msg for code in expected_status_errors)
                ]
                for row in rows:
                    if row["profile"] == label:
                        row["checks"]["no_runtime_errors"] = (
                            not errors and not failed_requests and not unexpected_console
                        )
                        row["status"] = "passed" if all(row["checks"].values()) else "failed"
                (profile / "errors.json").write_text(
                    json.dumps(
                        {
                            "page_errors": errors,
                            "failed_requests": failed_requests,
                            "unexpected_console": unexpected_console,
                            "expected_http_console": console_errors,
                        },
                        indent=2,
                    )
                )
            finally:
                context.close()
                if browser:
                    browser.close()
    report = {
        "status": "passed" if all(row["status"] == "passed" for row in rows) else "failed",
        "scenarios": rows,
    }
    (out / "scenarios.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "status": report["status"],
                "scenarios": len(rows),
                "passed": sum(row["status"] == "passed" for row in rows),
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run())
