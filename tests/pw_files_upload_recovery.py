"""Real local upload decisions, version recovery, and readable transfer failures."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

DATA = Path(os.environ["ALLES_DATA"]).resolve()
BASE = f"http://files.localhost:{os.environ['PORT']}"
OUTPUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
SCENARIOS = []


def run_profile(browser, profile):
    phone = profile == "phone"
    root = DATA / "files" if not phone else DATA / "connected-recovery"
    root.mkdir(exist_ok=True)
    names = {
        key: f"{profile}-{key}.txt"
        for key in ("review", "race", "ack", "retry", "interrupted", "transfer")
    }
    original = "original 原始 résumé\n".encode()
    replacement = "replacement 第二版\n".encode()
    for key in ("review", "race", "ack", "transfer"):
        (root / names[key]).write_bytes(original)
    large_name = f"{profile}-large.bin"
    large = root / large_name
    with large.open("wb") as handle:
        handle.write(b"L" * (25 * 1024 * 1024 + 1))
    large_digest = hashlib.sha256(large.read_bytes()).hexdigest()
    for index in range(12):
        (root / f"{profile}-{index:02}-会议记录-long-research-notes-résumé.txt").write_text(
            "synthetic"
        )
    destination = DATA / f"{profile}-destination"
    destination.mkdir()
    (destination / names["transfer"]).write_bytes(b"destination retained")
    context = browser.new_context(
        viewport={"width": 390 if phone else 1440, "height": 844 if phone else 920},
        is_mobile=phone,
        has_touch=phone,
        reduced_motion="reduce",
        service_workers="block",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    events, expected_faults, observations = [], [], []

    def capture(page):
        page.set_default_timeout(12_000)
        page.on("pageerror", lambda error: events.append({"kind": "pageerror", "text": str(error)}))
        page.on(
            "console",
            lambda message: (
                events.append(
                    {
                        "kind": "console",
                        "text": message.text,
                        "url": message.location.get("url", ""),
                    }
                )
                if message.type == "error"
                else None
            ),
        )
        page.on(
            "response",
            lambda response: (
                events.append(
                    {"kind": "http", "path": urlsplit(response.url).path, "status": response.status}
                )
                if response.status >= 400
                else None
            ),
        )
        page.on(
            "requestfailed",
            lambda request: events.append(
                {"kind": "failed", "path": urlsplit(request.url).path, "failure": request.failure}
            ),
        )

    context.on("page", capture)
    page = context.new_page()
    location_id = "default-local"

    def mark(scenario, detail):
        SCENARIOS.append(
            {
                "scenario_id": "files." + scenario,
                "profile": profile,
                "status": "passed",
                "evidence": [f"{profile}-trace.zip", f"{profile}-observations.json"],
                "detail": detail,
            }
        )
        (OUTPUT / "scenarios.json").write_text(json.dumps(SCENARIOS, indent=2))

    def add_location(name, path):
        page.locator("#files-add-location").click()
        page.locator("#files-location-name").fill(name)
        page.locator("#files-location-root").fill(str(path))
        page.locator('#files-location-access [data-value="managed"]').click()
        page.locator('#files-location-form button[type="submit"]').click()
        expect(page.locator("#files-location-dialog")).to_be_hidden()
        response = context.request.get(BASE + "/api/storage-locations")
        assert response.ok, response.text()
        return next(row["id"] for row in response.json()["locations"] if row["name"] == name)

    def activate(control):
        control.tap() if phone else control.click()

    def upload(target, name, content, status=409):
        if status >= 400:
            expected_faults.append(("http", "/api/files/upload", status))
        with target.expect_file_chooser() as chooser:
            activate(target.locator("#files-upload-btn"))
        chooser.value.set_files(
            {"name": name, "mimeType": "application/octet-stream", "buffer": content}
        )
        if status >= 400 or status == 0:
            expect(target.locator(".files-upload-review")).to_be_visible()
        else:
            expect(target.locator("#files-upload-btn")).to_be_enabled()
            expect(target.locator(f'.file-row[data-path="{name}"]')).to_be_visible()

    def bytes_are(name, value):
        result = context.request.get(
            BASE + "/api/files/raw?" + urlencode({"path": name, "location_id": location_id})
        )
        assert result.ok, result.text()
        assert result.body() == value
        assert (root / name).read_bytes() == value
        observations.append(
            {"name": name, "size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        )

    def versions(name):
        result = context.request.get(
            BASE + "/api/files/versions?" + urlencode({"path": name, "location_id": location_id})
        )
        assert result.ok, result.text()
        return result.json()

    def open_current(target=page):
        target.goto(BASE + "/?" + urlencode({"location": location_id}), wait_until="networkidle")
        expect(target.locator("#files-view")).to_be_visible()
        expect(target.locator(f'.file-row[data-path="{names["review"]}"]')).to_be_visible()

    def details(name):
        activate(page.locator(f'.file-row[data-path="{name}"] [data-file-open]'))
        expect(page.locator("#files-detail-panel")).to_be_visible()
        expect(page.locator(".files-version-history summary")).to_be_visible()

    def tab_to(selector, limit=30):
        control = page.locator(selector)
        for _ in range(limit):
            if control.evaluate("element => element === document.activeElement"):
                return
            page.keyboard.press("Tab")
        raise AssertionError(
            f"keyboard could not reach {selector}; active={page.evaluate('document.activeElement.outerHTML')}"
        )

    def closed_review(target=page):
        expect(target.locator(".files-upload-review")).to_have_count(0)
        expect(target.locator("#files-upload-btn")).to_be_enabled()

    try:
        page.goto(BASE, wait_until="networkidle")
        expect(page.locator("#files-view")).to_be_visible()
        if phone:
            location_id = add_location("phone connected files", root)
        destination_id = add_location(profile + " destination", destination)
        open_current()

        # Real keyboard traversal starts from a pointer-reachable search field.
        activate(page.locator("#files-search"))
        tab_to("#files-upload-btn")
        with page.expect_file_chooser() as chooser:
            page.keyboard.press("Enter")
        expected_faults.append(("http", "/api/files/upload", 409))
        chooser.value.set_files(
            {"name": names["review"], "mimeType": "text/plain", "buffer": replacement}
        )
        expect(page.locator("[data-upload-cancel]")).to_be_focused()
        expect(page.locator("[data-upload-submit]")).to_have_text("replace file")
        bytes_are(names["review"], original)
        assert versions(names["review"]) == []
        page.screenshot(path=str(OUTPUT / f"{profile}-collision.png"), full_page=True)
        page.keyboard.press("Escape")
        closed_review()
        expect(page.locator("#files-upload-btn")).to_be_focused()
        bytes_are(names["review"], original)
        mark(
            "upload-collision-cancel",
            "real Tab/Enter picker, Escape cancel, unchanged bytes and no version",
        )

        upload(page, names["review"], replacement)
        renamed = f"{profile}-kept-both-保留.txt"
        page.locator("#files-upload-review-name").fill(renamed)
        activate(page.locator("[data-upload-submit]"))
        closed_review()
        bytes_are(names["review"], original)
        bytes_are(renamed, replacement)
        mark("upload-keep-both", "explicit filename keeps original and new bytes after reload")

        upload(page, names["review"], replacement)
        activate(page.locator("[data-upload-submit]"))
        closed_review()
        bytes_are(names["review"], replacement)
        assert len(versions(names["review"])) == 1
        page.reload(wait_until="networkidle")
        details(names["review"])
        tab_to(".files-version-history summary")
        page.keyboard.press("Enter")
        tab_to("[data-version-id]")
        page.keyboard.press("Enter")
        expect(page.locator("[data-dialog-cancel]")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("[data-version-id]")).to_be_focused()
        bytes_are(names["review"], replacement)
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        expect(page.locator("[data-dialog-confirm]")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator(".files-version-feedback")).to_contain_text("version restored")
        expect(page.locator(".files-version-feedback")).to_be_focused()
        for restore_button in page.locator("[data-version-id]").all():
            label = restore_button.evaluate(
                "element => { const r=document.createRange(); r.selectNodeContents(element); return {lines:r.getClientRects().length, width:element.getBoundingClientRect().width, height:element.getBoundingClientRect().height}; }"
            )
            assert label["lines"] == 1 and label["width"] >= 44 and label["height"] >= 44, label
        bytes_are(names["review"], original)
        assert len(versions(names["review"])) == 2
        page.screenshot(path=str(OUTPUT / f"{profile}-version-restored.png"), full_page=True)
        with page.expect_download() as download:
            activate(page.locator("#files-detail-content a[download]"))
        assert Path(download.value.path()).read_bytes() == original
        page.locator("#files-detail-close").click()
        page.reload(wait_until="networkidle")
        bytes_are(names["review"], original)
        mark(
            "version-recovery",
            "pointer and keyboard restore/cancel, focus return, download and reload, previous current version retained",
        )

        upload(page, large_name, b"tiny replacement")
        expect(page.locator("[data-upload-submit]")).to_be_disabled()
        expect(page.locator("#files-upload-review-message")).to_contain_text(
            "cannot be kept in version history"
        )
        page.screenshot(path=str(OUTPUT / f"{profile}-large-blocked.png"), full_page=True)
        page.locator("#files-upload-review-name").fill(f"{profile}-large-new.bin")
        activate(page.locator("[data-upload-submit]"))
        closed_review()
        assert large.stat().st_size == 25 * 1024 * 1024 + 1
        assert hashlib.sha256(large.read_bytes()).hexdigest() == large_digest
        assert versions(large_name) == []
        bytes_are(f"{profile}-large-new.bin", b"tiny replacement")
        mark(
            "upload-large-preservation",
            "actual cap+1 original blocked; explicit new name preserves exact original",
        )

        second = context.new_page()
        open_current(second)
        upload(page, names["race"], b"first tab draft")
        upload(second, names["race"], b"second tab saved")
        activate(second.locator("[data-upload-submit]"))
        closed_review(second)
        bytes_are(names["race"], b"second tab saved")
        expected_faults.append(("http", "/api/files/upload", 409))
        activate(page.locator("[data-upload-submit]"))
        expect(page.locator("#files-upload-review-message")).to_contain_text("file changed")
        expect(page.locator("#files-upload-review-name")).to_have_value(names["race"])
        bytes_are(names["race"], b"second tab saved")
        activate(page.locator("[data-upload-cancel]"))
        closed_review()
        page.reload(wait_until="networkidle")
        bytes_are(names["race"], b"second tab saved")
        assert len(versions(names["race"])) == 1
        mark(
            "upload-stale-decision",
            "second real tab save invalidates first tab review; rejected file retained for retry, cancel preserves other save",
        )
        second.close()

        # Restore uses the list identity; a later mutation requires another decision.
        details(names["race"])
        page.locator(".files-version-history summary").click()
        other = context.new_page()
        open_current(other)
        upload(other, names["race"], b"third tab saved")
        activate(other.locator("[data-upload-submit]"))
        closed_review(other)
        expected_faults.append(("http", "/api/files/versions/restore", 409))
        page.locator("[data-version-id]").click()
        page.locator("[data-dialog-confirm]").click()
        expect(page.locator('[role="alertdialog"]')).to_contain_text("file changed")
        page.locator("[data-dialog-cancel]").click()
        expect(page.locator("[data-version-id]")).to_be_focused()
        bytes_are(names["race"], b"third tab saved")
        page.locator("#files-detail-close").click()
        other.close()
        mark(
            "version-stale-decision",
            "stale restore explicitly reconfirms changed current file; cancel keeps later bytes",
        )

        upload(page, names["ack"], replacement)
        intercepted = []

        def lose_ack(route):
            response = route.fetch()
            assert response.ok, response.text()
            intercepted.append(response.json())
            route.abort("failed")

        page.route("**/api/files/upload", lose_ack, times=1)
        expected_faults.append(("failed", "/api/files/upload", "net::ERR_FAILED"))
        activate(page.locator("[data-upload-submit]"))
        expect(page.locator("#files-upload-review-message")).to_contain_text("Failed to fetch")
        assert len(intercepted) == 1
        bytes_are(names["ack"], replacement)
        assert len(versions(names["ack"])) == 1
        activate(page.locator("[data-upload-submit]"))
        closed_review()
        assert len(versions(names["ack"])) == 1
        page.reload(wait_until="networkidle")
        bytes_are(names["ack"], replacement)
        mark(
            "upload-lost-ack",
            "simulated lost HTTP acknowledgement after real committed upload; retained File retries as unchanged without duplicate version",
        )

        def fail_upload(route):
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"synthetic destination unavailable"}',
            )

        page.route("**/api/files/upload", fail_upload, times=1)
        upload(page, names["retry"], replacement, status=503)
        assert not (root / names["retry"]).exists()
        renamed_retry = f"{profile}-retry-重试.txt"
        page.locator("#files-upload-review-name").fill(renamed_retry)
        page.route("**/api/files/upload", fail_upload, times=1)
        expected_faults.append(("http", "/api/files/upload", 503))
        activate(page.locator("[data-upload-submit]"))
        expect(page.locator("#files-upload-review-message")).to_contain_text(
            "synthetic destination unavailable"
        )
        expect(page.locator("#files-upload-review-name")).to_have_value(renamed_retry)
        expect(page.locator("#files-upload-review-message")).to_be_focused()
        activate(page.locator("[data-upload-submit]"))
        closed_review()
        bytes_are(renamed_retry, replacement)
        assert not (root / names["retry"]).exists()
        mark(
            "upload-failed-retry",
            "two simulated 503s before writes; File and chosen name survive; successful retry persists",
        )

        page.route("**/api/files/upload", lambda route: route.abort("failed"), times=1)
        expected_faults.append(("failed", "/api/files/upload", "net::ERR_FAILED"))
        upload(page, names["interrupted"], replacement, status=0)
        expect(page.locator(".files-upload-review")).to_be_visible()
        assert not (root / names["interrupted"]).exists()
        activate(page.locator("[data-upload-cancel]"))
        closed_review()
        page.reload(wait_until="networkidle")
        assert not (root / names["interrupted"]).exists()
        mark(
            "upload-interrupted-cancel",
            "simulated transport failure before dispatch; cancel and reload leave no destination",
        )

        page.locator(f'.file-row[data-path="{names["transfer"]}"] [data-file-select]').click()
        page.locator('[data-files-bulk="copy"]').click()
        page.locator(f'#files-transfer-locations [data-value="{destination_id}"]').click()
        # This is a real backend collision, not a simulated response.
        with page.expect_response(
            lambda response: (
                "/api/files/operations/" in response.url and response.url.endswith("/run")
            )
        ) as run_response:
            page.locator('#files-transfer-form button[type="submit"]').click()
        operation_path = urlsplit(run_response.value.url).path
        assert run_response.value.status == 409
        expected_faults.append(("http", operation_path, 409))
        error = page.locator(".files-operation-error").filter(has_text="destination already exists")
        expect(error).to_be_visible()
        assert (destination / names["transfer"]).read_bytes() == b"destination retained"
        bytes_are(names["transfer"], original)
        for theme in ("light", "dark"):
            # Existing appearance engine, not only a data-theme attribute change.
            page.evaluate(
                "theme => import('/static/js/theme.js').then(m => m.resetToDefault(theme))", theme
            )
            metrics = error.evaluate(
                "element => { const s=getComputedStyle(element), r=element.getBoundingClientRect(); return {text:element.textContent, whiteSpace:s.whiteSpace, textOverflow:s.textOverflow, width:element.clientWidth, scrollWidth:element.scrollWidth, left:r.left, right:r.right, height:r.height}; }"
            )
            assert metrics["text"] == "destination already exists", metrics
            assert metrics["whiteSpace"] != "nowrap" and metrics["textOverflow"] != "ellipsis", (
                metrics
            )
            assert metrics["scrollWidth"] <= metrics["width"] + 1, metrics
            assert 0 <= metrics["left"] < metrics["right"] <= (390 if phone else 1440), metrics
            observations.append({"theme": theme, "transfer_error": metrics})
            page.screenshot(path=str(OUTPUT / f"{profile}-transfer-{theme}.png"), full_page=True)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        mark(
            "transfer-visible-failure",
            "real connected copy collision; full reason wraps in light/dark, source and destination unchanged",
        )

        faults = [
            (event["kind"], event["path"], event.get("status", event.get("failure")))
            for event in events
            if event["kind"] in ("http", "failed")
        ]
        assert Counter(faults) == Counter(expected_faults), {
            "expected": expected_faults,
            "actual": faults,
        }
        assert not [event for event in events if event["kind"] == "pageerror"], events
        expected_console = Counter((path, str(code)) for _, path, code in expected_faults)
        console = []
        for event in events:
            if event["kind"] != "console":
                continue
            text = event["text"]
            code = (
                "net::ERR_FAILED"
                if "net::ERR_FAILED" in text
                else "409"
                if "409 (Conflict)" in text
                else "503"
                if "503 (Service Unavailable)" in text
                else "unexpected"
            )
            console.append((urlsplit(event["url"]).path, code))
        assert Counter(console) == expected_console, {
            "expected": list(expected_console.items()),
            "actual": console,
        }
        # Clear this profile's deliberate failed transfer through the visible UI.
        page.locator('[data-operation-action="discard"]').click()
        expect(page.locator("#files-operation-dock")).to_be_hidden()
        mark(
            "upload-network-contract",
            "every HTTP/transport/console fault matches the exact intentional endpoint and count; no page errors",
        )
        mark(
            "upload-collision-recovery",
            "completed explicit cancel/new-name/replace decisions, stale-identity rejection, exact reload bytes, usable restore history and blocked oversized originals",
        )
    finally:
        (OUTPUT / f"{profile}-events.json").write_text(json.dumps(events, indent=2))
        (OUTPUT / f"{profile}-observations.json").write_text(json.dumps(observations, indent=2))
        for index, current in enumerate(context.pages):
            current.screenshot(path=str(OUTPUT / f"{profile}-{index}-final.png"), full_page=True)
        context.tracing.stop(path=str(OUTPUT / f"{profile}-trace.zip"))
        context.close()


def run():
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert (DATA / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(BASE, run_id)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for profile in ("desktop", "phone"):
                run_profile(browser, profile)
        finally:
            (OUTPUT / "environment.json").write_text(
                json.dumps(
                    {
                        "browser": "Chromium",
                        "version": browser.version,
                        "profiles": ["desktop", "phone emulation"],
                        "integration": "fresh owned local and connected local roots; simulated 503 and transport faults labeled in scenarios",
                    },
                    indent=2,
                )
            )
            browser.close()
    print("Files upload recovery and transfer failure checks passed")


if __name__ == "__main__":
    run()
