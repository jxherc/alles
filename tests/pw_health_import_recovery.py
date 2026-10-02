"""Real CSV batches and stable-record edits/deletes survive rejected and lost replies."""

import json
import os
import re
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    scenarios = []
    csv = "date,kind,value,unit\n2026-10-01,weight,74.25,kg\n2026-10-01,sleep,8,h\n"
    cases = [
        "import-rejected",
        "import-lost",
        "import-invalid",
        "import-extra",
        "import-date-suffix",
        "import-cancel",
        "import-later-rejected",
        "import-malformed-ack",
        "import-pending-focus",
        "delete-rejected",
        "delete-lost",
        "delete-refresh",
        "delete-other",
        "delete-reused-id",
        "delete-stale",
        "edit-stale",
        "read-order",
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            for case in cases:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    timezone_id="UTC",
                    reduced_motion="reduce",
                    service_workers="block",
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
                page = context.new_page()
                page.set_default_timeout(6000)
                errors, console, expected_status, posts, writes, held = [], [], [], [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console", lambda msg: console.append(msg.text) if msg.type == "error" else None
                )
                page.on(
                    "request",
                    lambda req: (
                        posts.append(req.post_data_json)
                        if req.url == base + "/api/health/import" and req.method == "POST"
                        else None
                    ),
                )
                result = {
                    "scenario_id": "health.recovery." + case,
                    "feature_id": "health.logs-and-habits",
                    "profile": "desktop" if width == 1440 else "phone",
                    "status": "failed",
                }
                scenarios.append(result)

                def rows():
                    return context.request.get(base + "/api/health").json()["entries"]

                def fail(route, *, status=503):
                    expected_status.append(str(status))
                    route.fulfill(
                        status=status,
                        content_type="application/json",
                        body=json.dumps({"detail": "synthetic unavailable"}),
                    )

                def wait_held():
                    deadline = time.monotonic() + 3
                    while not held and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert len(held) == 1, "expected exactly one held request"

                def choose(text=csv):
                    with page.expect_file_chooser() as chooser:
                        page.locator("#health-import").click()
                    chooser.value.set_files(
                        {"name": "readings.csv", "mimeType": "text/csv", "buffer": text.encode()}
                    )

                def confirm_delete(item):
                    page.locator(
                        f'.health-row[data-record-id="{item["record_id"]}"] [data-act="del"]'
                    ).click()
                    page.locator(".dialog-overlay [data-dialog-confirm]").press("Enter")

                def replace(item):
                    assert context.request.delete(base + f"/api/health/{item['id']}").ok
                    response = context.request.post(
                        base + "/api/health",
                        data={"kind": "sleep", "value": 8, "unit": "h", "date": "2026-10-01"},
                    )
                    assert response.ok, response.text()
                    replacement = response.json()
                    assert (
                        replacement["id"] == item["id"]
                        and replacement["record_id"] != item["record_id"]
                    )
                    return replacement

                try:
                    assert context.request.post(base + "/api/setup/dismiss").ok
                    item = None
                    if case.startswith(("delete-", "edit-")) or case == "read-order":
                        response = context.request.post(
                            base + "/api/health",
                            data={
                                "kind": "weight",
                                "value": 74.25,
                                "unit": "kg",
                                "date": "2026-10-01",
                            },
                        )
                        assert response.ok, response.text()
                        item = response.json()
                    other = None
                    if case == "delete-other":
                        response = context.request.post(
                            base + "/api/health",
                            data={"kind": "med", "value": 1, "unit": "dose", "date": "2026-10-01"},
                        )
                        assert response.ok
                        other = response.json()
                    page.goto(base + "/?view=health-log", wait_until="networkidle")
                    expect(
                        page.locator('#health-body [data-kokuen-state="loading"]')
                    ).to_have_count(0)
                    if case.startswith("import-"):
                        endpoint = base + "/api/health/import"
                        if case in {"import-invalid", "import-extra", "import-date-suffix"}:
                            expected_status.append("400")
                            invalid = csv.replace("2026-10-01,sleep", "2026-02-30,sleep")
                            message = "line 3 needs a valid date"
                            if case == "import-extra":
                                invalid = csv.replace("8,h", "8,25,h")
                                message = "line 3 has more cells than the header"
                            elif case == "import-date-suffix":
                                invalid = csv.replace("2026-10-01,sleep", "2026-10-011,sleep")
                            choose(invalid)
                            expect(page.locator("#health-import-error")).to_contain_text(message)
                            assert rows() == [], "a rejected file partly imported"
                            page.locator("#health-import-close").press("Enter")
                            expect(page.locator("#health-import-form")).to_have_count(0)
                            choose()
                            expect(page.locator("#health-import-form")).to_contain_text(
                                "imported 2 entries"
                            )
                            assert posts[0]["request_id"] != posts[1]["request_id"]
                        elif case == "import-pending-focus":
                            page.route(endpoint, lambda route: held.append(route))
                            choose()
                            expect(page.locator("#health-import-close")).to_be_disabled()
                            wait_held()
                            page.locator("#health-add-toggle").click()
                            page.locator("#health-value").fill("18.75")
                            page.locator("#health-note").fill("independent draft")
                            route = held.pop()
                            response = route.fetch()
                            route.fulfill(response=response)
                            expect(page.locator("#health-import-form")).to_contain_text(
                                "imported 2 entries"
                            )
                            expect(page.locator("#health-value")).to_have_value("18.75")
                            expect(page.locator("#health-note")).to_be_focused()
                            page.locator("#health-cancel").click()
                        else:

                            def intercept(route):
                                if case != "import-rejected":
                                    response = route.fetch()
                                    assert response.ok, response.text()
                                if case == "import-malformed-ack":
                                    route.fulfill(
                                        status=200,
                                        content_type="application/json",
                                        body='{"imported":null}',
                                    )
                                else:
                                    fail(route)

                            page.route(endpoint, intercept)
                            choose()
                            expect(page.locator("#health-import-error")).to_contain_text(
                                "could not confirm"
                            )
                            assert len(rows()) == (0 if case == "import-rejected" else 2)
                            expect(page.locator("#health-import-retry")).to_be_focused()
                            page.screenshot(
                                path=str(output / f"{case}-{width}-error.png"), full_page=True
                            )
                            page.unroute(endpoint, intercept)
                            if case == "import-later-rejected":
                                page.route(endpoint, lambda route: fail(route, status=400))
                                page.locator("#health-import-retry").press("Enter")
                                expect(page.locator("#health-import-error")).to_contain_text(
                                    "may already be saved"
                                )
                                expect(page.locator("#health-import-error")).to_contain_text(
                                    "synthetic unavailable"
                                )
                                page.unroute(endpoint)
                            if case in {"import-cancel", "import-later-rejected"}:
                                page.locator("#health-import-close").press("Enter")
                                expect(page.locator(".dialog-card")).to_contain_text(
                                    "may already be imported"
                                )
                                page.locator(".dialog-overlay [data-dialog-cancel]").press("Enter")
                                expect(page.locator("#health-import-error")).to_be_visible()
                                page.locator("#health-import-close").press("Enter")
                                page.locator(".dialog-overlay [data-dialog-confirm]").press("Enter")
                                expect(page.locator("#health-import-form")).to_have_count(0)
                                expect(page.locator(".health-row")).to_have_count(2)
                            else:
                                page.locator("#health-import-retry").press("Enter")
                                expect(page.locator("#health-import-form")).to_contain_text(
                                    "imported 2 entries"
                                    if case == "import-rejected"
                                    else "already imported (2 entries)"
                                )
                                assert posts[0]["request_id"] == posts[1]["request_id"]
                        assert len(rows()) == 2 and sorted(row["value"] for row in rows()) == [
                            8,
                            74.25,
                        ]
                        assert all(body["strict"] for body in posts)
                        if case == "import-lost":
                            page.locator("#health-import-close").press("Enter")
                            choose()
                            expect(page.locator("#health-import-form")).to_contain_text(
                                "imported 2 entries"
                            )
                            assert (
                                len(rows()) == 4
                                and posts[-1]["request_id"] != posts[0]["request_id"]
                            )
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".health-row")).to_have_count(
                            4 if case == "import-lost" else 2
                        )
                    elif case.startswith(("delete-", "edit-")):
                        endpoint = re.compile(re.escape(base) + r"/api/health/\d+(?:\?.*)?$")
                        replacement = None
                        if case == "edit-stale":
                            page.locator(
                                f'.health-row[data-id="{item["id"]}"] [data-act="edit"]'
                            ).click()
                            replacement = replace(item)
                            page.locator("#health-value").fill("72.125")
                            expected_status.append("409")
                            page.locator("#health-create").press("Enter")
                            expect(page.locator("#health-entry-error")).to_contain_text(
                                "different entry"
                            )
                            expect(page.locator("#health-value")).to_have_value("72.125")
                            assert rows() == [replacement]
                            page.locator("#health-cancel").press("Enter")
                        elif case == "delete-stale":
                            page.locator(
                                f'.health-row[data-id="{item["id"]}"] [data-act="del"]'
                            ).click()
                            replacement = replace(item)
                            expected_status.append("409")
                            page.locator(".dialog-overlay [data-dialog-confirm]").press("Enter")
                            expect(page.locator("#health-write-error")).to_contain_text(
                                "reading changed"
                            )
                            assert rows() == [replacement]
                        else:

                            def intercept_delete(route):
                                writes.append(route.request.url)
                                assert item["record_id"] in route.request.url
                                if case != "delete-rejected":
                                    response = route.fetch()
                                    assert response.ok, response.text()
                                    if case == "delete-reused-id":
                                        response = context.request.post(
                                            base + "/api/health",
                                            data={
                                                "kind": "sleep",
                                                "value": 8,
                                                "unit": "h",
                                                "date": "2026-10-01",
                                            },
                                        )
                                        assert response.ok
                                        assert response.json()["id"] == item["id"]
                                fail(route)

                            page.route(endpoint, intercept_delete)
                            page.route(base + "/api/health", fail)
                            confirm_delete(item)
                            expect(page.locator("#health-write-error")).to_contain_text(
                                "could not confirm deletion"
                            )
                            expect(
                                page.locator('#health-body [data-kokuen-state="partial"]')
                            ).to_be_visible()
                            expect(
                                page.locator(f'.health-row[data-record-id="{item["record_id"]}"]')
                            ).to_be_visible()
                            if case == "delete-lost":
                                page.locator("#health-refresh").press("Enter")
                                expect(
                                    page.locator('#health-body [data-kokuen-state="partial"]')
                                ).to_be_visible()
                                expect(page.locator("#health-write-error")).to_contain_text(
                                    "could not confirm deletion"
                                )
                                expect(
                                    page.locator(
                                        f'.health-row[data-record-id="{item["record_id"]}"]'
                                    )
                                ).to_be_visible()
                            page.unroute(endpoint, intercept_delete)
                            if case == "delete-other":
                                confirm_delete(other)
                                expect(
                                    page.locator(
                                        f'.health-row[data-record-id="{other["record_id"]}"]'
                                    )
                                ).to_have_count(0)
                                expect(
                                    page.locator('#health-body [data-kokuen-state="partial"]')
                                ).to_be_visible()
                                expect(page.locator("#health-write-error")).to_contain_text(
                                    "could not confirm deletion"
                                )
                                expect(
                                    page.locator(
                                        f'.health-row[data-record-id="{item["record_id"]}"]'
                                    )
                                ).to_be_visible()
                                assert rows() == []
                                page.screenshot(
                                    path=str(output / f"other-delete-{width}-retained.png"),
                                    full_page=True,
                                )
                            page.unroute(base + "/api/health", fail)
                            if case == "delete-lost":
                                expected_status.append("404")
                            if case == "delete-reused-id":
                                expected_status.append("409")
                            if case in {"delete-refresh", "delete-other"}:
                                page.locator("#health-refresh").press("Enter")
                                expect(page.locator("#health-write-error")).to_have_count(0)
                                expect(page.locator("#health-add-toggle")).to_be_focused()
                            else:
                                confirm_delete(item)
                            expect(
                                page.locator(f'.health-row[data-record-id="{item["record_id"]}"]')
                            ).to_have_count(0)
                            if case == "delete-reused-id":
                                expect(page.locator("#health-write-error")).to_contain_text(
                                    "reading changed"
                                )
                                replacement = rows()[0]
                                assert replacement["kind"] == "sleep" and replacement["value"] == 8
                            else:
                                assert rows() == []
                                expect(page.locator("#health-write-error")).to_have_count(0)
                            assert len(writes) == 1
                        page.reload(wait_until="networkidle")
                        expect(page.locator(".health-row")).to_have_count(1 if replacement else 0)
                        if replacement:
                            expect(
                                page.locator(
                                    f'.health-row[data-record-id="{replacement["record_id"]}"] .health-row-val'
                                )
                            ).to_have_text("8 h")
                    else:
                        # Hold an old read, then let a newer navigation finish first.
                        def hold_first(route):
                            if held:
                                route.continue_()
                            else:
                                held.append((route, route.fetch()))

                        page.route(base + "/api/health", hold_first)
                        page.locator('.health-chip[data-days="7"]').press("Enter")
                        expect(
                            page.locator('#health-body [data-kokuen-state="loading"]')
                        ).to_be_visible()
                        wait_held()
                        replacement = replace(item)
                        page.locator('.health-chip[data-days="90"]').press("Enter")
                        expect(
                            page.locator(
                                f'.health-row[data-record-id="{replacement["record_id"]}"]'
                            )
                        ).to_be_visible()
                        route, response = held.pop()
                        route.fulfill(response=response)
                        page.unroute(base + "/api/health", hold_first)
                        page.wait_for_timeout(200)
                        expect(
                            page.locator(f'.health-row[data-record-id="{item["record_id"]}"]')
                        ).to_have_count(0)
                        expect(page.locator('.health-chip[data-days="90"]')).to_have_attribute(
                            "aria-checked", "true"
                        )
                    assert not errors, errors
                    assert len(console) == len(expected_status) and all(
                        status in message for status, message in zip(expected_status, console)
                    ), (console, expected_status)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                        "horizontal overflow"
                    )
                    for button in page.locator("#health-body button:visible").all():
                        box = button.bounding_box()
                        assert box and box["height"] >= 44 and box["width"] >= 44, box
                    result["status"] = "passed"
                except Exception as error:
                    result["error"] = str(error)
                finally:
                    page.screenshot(path=str(output / f"{case}-{width}-final.png"), full_page=True)
                    result["console_errors"] = console
                    result["page_errors"] = errors
                    for row in rows():
                        context.request.delete(base + f"/api/health/{row['id']}")
                    context.close()
                    (output / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
        browser.close()
    print(json.dumps(scenarios, indent=2))
    if any(result["status"] != "passed" for result in scenarios):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
