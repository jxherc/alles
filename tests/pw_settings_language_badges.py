"""Language availability badges after localization refresh, save and reload.

The owned server reads a public manifest copy from its disposable ALLES_DATA.
Marking Japanese pending changes only that fixture's backend eligibility; the
normal catalog, source files and owner preferences remain untouched.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from pw_settings_helpers import choose_settings_section  # noqa: E402
from run_browser_gates import (  # noqa: E402
    free_port,
    isolated_environment,
    owned_data,
    stop_process,
    wait_for_server,
)

from services.appearance import from_legacy  # noqa: E402


def exercise(page, api, dest, profile, records, data):
    observations = []
    options = api.get("/api/settings/localization/options").json()
    assert all(item["available"] for item in options["languages"])

    def pane(name="notifications", reload=False):
        if reload or page.url == "about:blank":
            page.goto("/?view=today")
            expect(page.locator("#setup-wizard")).to_be_hidden()
        if not page.locator("#settings-modal").is_visible():
            page.locator("#today-settings").click()
        choose_settings_section(page, name)
        if name == "notifications":
            expect(page.locator("#locale-settings-workbench")).to_have_attribute(
                "aria-busy", "false"
            )

    def observe(name, language, unavailable=False):
        # Scroll with real Tab traversal to the selected language before capture.
        target = page.locator("[data-locale-language][aria-checked=true]")
        expect(target).to_have_attribute("data-locale-language", language)
        for _ in range(160):
            if target.evaluate("e=>e===document.activeElement"):
                break
            page.keyboard.press("Tab")
        expect(target).to_be_focused()
        expect(target).to_be_in_viewport()
        actual = page.locator("[data-locale-language]").evaluate_all("""es=>es.map(e=>({
          id:e.dataset.localeLanguage,disabled:e.getAttribute('aria-disabled'),selected:e.getAttribute('aria-checked'),
          label:e.querySelector('em').textContent,key:e.querySelector('em').dataset.i18n
        }))""")
        translations = json.loads((ROOT / "static" / "locales" / f"{language}.json").read_text())[
            "messages"
        ]
        mismatches = []
        for row in actual:
            disabled = unavailable and row["id"] == "ja"
            assert row["disabled"] == str(disabled).lower()
            key = "locale.catalog_reviewed_pending" if disabled else "common.reviewed"
            if row["label"] != translations[key] or row["key"] != key:
                mismatches.append(
                    {"id": row["id"], "expected_key": key, "expected_label": translations[key]}
                )
        page.screenshot(path=str(dest / (name + ".png")), full_page=True)
        observations.append(
            {
                "state": name,
                "language": language,
                "unavailable_ja": unavailable,
                "rows": actual,
                "mismatches": mismatches,
            }
        )
        (dest / "observations.json").write_text(json.dumps(observations, indent=2))
        assert not mismatches, mismatches

    def save(language):
        page.locator(f'[data-locale-language="{language}"]').click()
        page.locator("#s-locale-save").click()
        expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
        assert api.get("/api/settings").json()["language"] == language
        expect(page.locator("html")).to_have_attribute("dir", "rtl" if language == "ar" else "ltr")

    pane(reload=True)
    observe("01-initial-enabled", "en")
    save("fr")
    observe("02-save-selected-french", "fr")
    pane("ai")
    pane()
    observe("03-pane-refresh-french", "fr")
    pane(reload=True)
    observe("04-reload-french", "fr")
    save("en")
    observe("05-save-english", "en")
    save("ar")
    observe("06-save-arabic", "ar")
    pane(reload=True)
    observe("07-reload-arabic", "ar")
    save("en")
    # Only this owned backend's fixture manifest changes. Product catalog files stay intact.
    manifest_path = data / "test-locale-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    next(item for item in manifest["languages"] if item["id"] == "ja")["release_state"] = "pending"
    manifest_path.write_text(json.dumps(manifest))
    changed = api.get("/api/settings/localization/options").json()
    assert next(item for item in changed["languages"] if item["id"] == "ja")["available"] is False
    rejected = api.patch("/api/settings", data={"language": "ja"})
    assert rejected.status == 400, rejected.text()
    assert api.get("/api/settings").json()["language"] == "en"
    pane(reload=True)
    observe("08-unavailable-english", "en", True)
    unavailable = page.locator('[data-locale-language="ja"]')
    unavailable.scroll_into_view_if_needed()
    rect = unavailable.bounding_box()
    assert unavailable.evaluate(
        "e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}"
    )
    page.mouse.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    expect(page.locator('[data-locale-language="en"]')).to_have_attribute("aria-checked", "true")
    expect(page.locator("#locale-settings-save-state")).to_contain_text("Japanese")
    page.screenshot(path=str(dest / "08-unavailable-click.png"), full_page=True)
    selected = page.locator('[data-locale-language="en"]')
    for _ in range(160):
        if selected.evaluate("e=>e===document.activeElement"):
            break
        page.keyboard.press("Tab")
    expect(selected).to_be_focused()
    for value in ("fr", "es", "zh-Hans", "zh-Hant", "ko"):
        page.keyboard.press("ArrowDown")
        expect(page.locator(f'[data-locale-language="{value}"]')).to_be_focused()
    expect(unavailable).to_have_attribute("aria-checked", "false")
    page.screenshot(path=str(dest / "08-unavailable-keyboard-skip.png"), full_page=True)
    page.keyboard.press("Home")
    expect(selected).to_be_focused()
    assert api.get("/api/settings").json()["language"] == "en"
    save("en")
    observe("09-unavailable-after-save", "en", True)
    save("ar")
    observe("10-unavailable-arabic", "ar", True)
    pane("ai")
    pane()
    observe("11-unavailable-pane-refresh-arabic", "ar", True)
    pane(reload=True)
    observe("12-unavailable-reload-arabic", "ar", True)
    records.append(
        {
            "scenario_id": "settings.language-availability-badges",
            "profile": profile,
            "status": "passed",
            "states": len(observations),
            "mismatching_states": sum(bool(o["mismatches"]) for o in observations),
            "unavailable_backend_status": rejected.status,
        }
    )


def run():
    output = Path(
        os.environ.get("ALLES_BROWSER_ARTIFACTS")
        or tempfile.mkdtemp(prefix="alles-settings-language-badges-")
    )
    output.mkdir(parents=True, exist_ok=True)
    records, cleanup = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for profile in ("desktop", "phone"):
                    dest = output / profile
                    dest.mkdir(exist_ok=True)
                    with owned_data() as (data, run_id):
                        port = free_port()
                        env = isolated_environment(data, run_id, port, dest)
                        fixture = {
                            "profile": profile,
                            "data_root": str(data),
                            "port": port,
                            "run_id": run_id,
                            "server_stopped": True,
                        }
                        cleanup.append(fixture)
                        process = None
                        (data / "test-locale-manifest.json").write_bytes(
                            (ROOT / "static/locales/manifest.json").read_bytes()
                        )
                        with (dest / "server.log").open("w") as log:

                            def start():
                                child = subprocess.Popen(
                                    [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; import os, runpy; import services.localization as loc; loc.CATALOG_MANIFEST_PATH=Path(os.environ['ALLES_DATA'])/'test-locale-manifest.json'; runpy.run_path('app.py',run_name='__main__')",
                                    ],
                                    cwd=ROOT,
                                    env=env,
                                    stdout=log,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=False,
                                )
                                try:
                                    wait_for_server(child, port, run_id, 90)
                                except BaseException:
                                    stop_process(child, process_group=False)
                                    raise
                                return child

                            process = start()
                            fixture["server_stopped"] = False
                            fixture["server_pid"] = process.pid
                            try:
                                context = browser.new_context(
                                    base_url=f"http://127.0.0.1:{port}",
                                    viewport={
                                        "width": 390 if profile == "phone" else 1440,
                                        "height": 844 if profile == "phone" else 900,
                                    },
                                    is_mobile=profile == "phone",
                                    has_touch=profile == "phone",
                                    locale="en-CA",
                                    timezone_id="America/Toronto",
                                    reduced_motion="reduce",
                                    service_workers="block",
                                )
                                events = {
                                    "pageerrors": [],
                                    "console": [],
                                    "responses": [],
                                    "failed_requests": [],
                                }
                                page = None
                                try:
                                    context.tracing.start(
                                        screenshots=True, snapshots=True, sources=True
                                    )
                                    api = context.request
                                    assert api.post("/api/setup/dismiss").ok
                                    assert api.put(
                                        "/api/appearance", data=from_legacy("dark", None)
                                    ).ok
                                    assert api.patch(
                                        "/api/settings",
                                        data={
                                            "language": "en",
                                            "region": "",
                                            "timezone": "",
                                            "currency": "",
                                            "clock_format": "auto",
                                            "week_start": "auto",
                                            "context_limit": 40,
                                            "stream_thinking": True,
                                        },
                                    ).ok
                                    page = context.new_page()
                                    page.set_default_timeout(12000)
                                    page.on(
                                        "pageerror", lambda e: events["pageerrors"].append(str(e))
                                    )
                                    page.on(
                                        "console",
                                        lambda m: events["console"].append(
                                            {"type": m.type, "text": m.text}
                                        ),
                                    )
                                    page.on(
                                        "response",
                                        lambda r: (
                                            events["responses"].append(
                                                {
                                                    "path": r.url,
                                                    "method": r.request.method,
                                                    "status": r.status,
                                                }
                                            )
                                            if r.status >= 400
                                            else None
                                        ),
                                    )
                                    page.on(
                                        "requestfailed",
                                        lambda r: events["failed_requests"].append(
                                            {
                                                "path": r.url,
                                                "method": r.method,
                                                "failure": r.failure,
                                            }
                                        ),
                                    )
                                    exercise(page, api, dest, profile, records, data)
                                    assert events["pageerrors"] == []
                                    assert events["responses"] == []
                                    assert events["failed_requests"] == []
                                    assert [
                                        e for e in events["console"] if e["type"] == "error"
                                    ] == []
                                except BaseException:
                                    if page is not None:
                                        page.screenshot(
                                            path=str(dest / "failure.png"), full_page=True
                                        )
                                    raise
                                finally:
                                    (dest / "events.json").write_text(json.dumps(events, indent=2))
                                    context.tracing.stop(path=str(dest / "trace.zip"))
                                    context.close()
                            finally:
                                stop_process(process, process_group=False)
                                fixture["server_stopped"] = process.poll() is not None
            finally:
                browser.close()
    finally:
        for fixture in cleanup:
            fixture["data_removed"] = not Path(fixture["data_root"]).exists()
            with socket.socket() as sock:
                sock.settimeout(0.2)
                fixture["port_closed"] = sock.connect_ex(("127.0.0.1", fixture["port"])) != 0
        (output / "scenarios.json").write_text(json.dumps(records, indent=2))
        (output / "owned-fixtures.json").write_text(json.dumps(cleanup, indent=2))
    assert all(f["server_stopped"] and f["data_removed"] and f["port_closed"] for f in cleanup), (
        cleanup
    )
    print(json.dumps({"status": "passed", "scenarios": len(records), "cleanup": cleanup}))


if __name__ == "__main__":

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    run()
