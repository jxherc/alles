"""Owned split row changes, preserved drafts, failed save and reopened results."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                for theme in ("dark", "light"):
                    for case in ("add", "remove", "refresh-add", "refresh-remove"):
                        context = browser.new_context(
                            viewport={"width": width, "height": 900},
                            timezone_id="UTC",
                            service_workers="block",
                            reduced_motion="reduce",
                        )
                        held, errors, console, external = [], [], [], []
                        state = {"hold_filter": False, "fail_save": True}
                        page = context.new_page()
                        page.set_default_timeout(2500)
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.on(
                            "console",
                            lambda m: console.append(m.text) if m.type == "error" else None,
                        )

                        def route(r):
                            parsed = urlsplit(r.request.url)
                            if (parsed.scheme, parsed.netloc) != ("http", urlsplit(base).netloc):
                                external.append(r.request.url)
                                return r.abort()
                            if (
                                parsed.path == "/api/money/transactions"
                                and "tag=" in parsed.query
                                and state["hold_filter"]
                            ):
                                held.append(r)
                                return
                            if (
                                parsed.path.endswith("/splits")
                                and r.request.method == "PUT"
                                and state["fail_save"]
                            ):
                                return r.fulfill(
                                    status=503, json={"detail": "owned refused split save"}
                                )
                            return r.continue_()

                        context.route("**/*", route)
                        context.route_web_socket("**/*", lambda ws: ws.close())
                        api = context.request
                        assert api.post(base + "/api/setup/dismiss").ok
                        assert api.patch(base + "/api/settings", data={"timezone": "UTC"}).ok
                        assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                        for a in api.get(base + "/api/money/accounts").json():
                            assert api.delete(base + "/api/money/accounts/" + a["id"]).ok
                        account = api.post(
                            base + "/api/money/accounts",
                            data={"name": "owned split account", "currency": "CAD", "opening": 100},
                        ).json()
                        tid = api.post(
                            base + "/api/money/transactions",
                            data={
                                "account_id": account["id"],
                                "date": datetime.now(UTC).date().isoformat(),
                                "payee": "owned split expense",
                                "amount": -10,
                                "tags": "owned",
                            },
                        ).json()["id"]
                        if case.endswith("remove"):
                            assert api.put(
                                base + f"/api/money/transactions/{tid}/splits",
                                data={
                                    "splits": [
                                        {"category": "owned first", "amount": 6},
                                        {"category": "owned second", "amount": 4},
                                    ]
                                },
                            ).ok
                        record = {"case": case, "width": width, "theme": theme, "status": "failed"}
                        records.append(record)
                        try:
                            page.goto(base + "/?view=money", wait_until="networkidle")
                            assert (
                                page.locator("html").get_attribute("data-theme") or "dark"
                            ) == theme
                            page.locator(f'[data-split-txn="{tid}"]').press("Enter")
                            editor = page.locator(".txn-split-editor")
                            expect(editor).to_be_visible()
                            expect(editor.locator(".split-row")).to_have_count(
                                1 if case.endswith("add") else 2
                            )
                            if case.startswith("refresh-"):
                                old_root = page.locator("#txn-rows").element_handle()
                                retained_editor = editor.element_handle()
                                if page.locator("#money-entry-fields").is_hidden():
                                    page.locator("#money-entry-action").press("Enter")
                                page.locator("#tx-payee").fill("owned full refresh expense")
                                page.locator("#tx-amt").fill("2.50")
                                with page.expect_response(
                                    lambda response: (
                                        urlsplit(response.url).path == "/api/money/transactions"
                                        and response.request.method == "POST"
                                    )
                                ) as result:
                                    page.locator("#tx-add").press("Enter")
                                assert result.value.ok
                                saved_transaction = result.value.json()
                                expect(
                                    page.locator(f'[data-undo-saved="{saved_transaction["id"]}"]')
                                ).to_be_visible()
                                expect(
                                    page.locator(f'.txn[data-id="{saved_transaction["id"]}"]')
                                ).to_be_visible()
                                page.wait_for_load_state("networkidle")
                                record["old_root_detached"] = old_root.evaluate(
                                    "e => !e.isConnected"
                                )
                                record["editor_retained"] = retained_editor.evaluate(
                                    "e => e.isConnected"
                                )
                                assert record["old_root_detached"] and record["editor_retained"], (
                                    record
                                )
                                expect(editor.locator(".split-row")).to_have_count(
                                    1 if case.endswith("add") else 2
                                )
                            if case.endswith("add"):
                                editor.locator(".split-cat").fill("owned 草稿")
                                editor.locator(".split-amt").fill("6.00")
                                page.locator("#split-add-row").press("Enter")
                                expect(editor.locator(".split-row")).to_have_count(2)
                                expect(editor.locator(".split-cat").last).to_be_focused()
                                expect(editor.locator(".split-cat").first).to_have_value(
                                    "owned 草稿"
                                )
                                expect(editor.locator(".split-amt").first).to_have_value("6.00")
                                editor.locator(".split-cat").last.fill("owned second")
                                editor.locator(".split-amt").last.fill("4.00")
                            else:
                                editor.locator(".split-row-del").nth(
                                    1 if case.startswith("refresh-") else 0
                                ).press("Enter")
                                expect(editor.locator(".split-row")).to_have_count(1)
                                expect(editor.locator(".split-row-del")).to_be_focused()
                                expect(editor.locator(".split-cat")).to_have_value(
                                    "owned first" if case.startswith("refresh-") else "owned second"
                                )
                                expect(editor.locator(".split-amt")).to_have_value(
                                    "6" if case.startswith("refresh-") else "4"
                                )
                            # A late real filter read keeps the newer mounted editor and focus.
                            state["hold_filter"] = True
                            page.locator(f'.txn[data-id="{tid}"] .tx-tag[data-tag="owned"]').press(
                                "Enter"
                            )
                            for _ in range(40):
                                if held:
                                    break
                                page.wait_for_timeout(25)
                            assert len(held) == 1
                            editor.locator(".split-cat").last.fill("newer owned 草稿")
                            pending = held.pop()
                            pending.fulfill(response=pending.fetch())
                            expect(editor.locator(".split-cat").last).to_have_value(
                                "newer owned 草稿"
                            )
                            expect(editor.locator(".split-cat").last).to_be_focused()
                            expect(page.locator("#tag-clear")).to_be_visible()
                            expected = (
                                ["owned 草稿", "newer owned 草稿"]
                                if case.endswith("add")
                                else ["newer owned 草稿"]
                            )
                            page.locator("#split-save").press("Enter")
                            expect(page.locator(".toast").last).to_contain_text("save failed")
                            expect(editor.locator(".split-row")).to_have_count(len(expected))
                            expect(editor.locator(".split-cat").last).to_have_value(expected[-1])
                            state["fail_save"] = False
                            page.locator("#split-save").press("Enter")
                            expect(editor).to_have_count(0)
                            page.reload(wait_until="networkidle")
                            page.locator(f'[data-split-txn="{tid}"]').press("Enter")
                            expect(editor.locator(".split-row")).to_have_count(len(expected))
                            for i, category in enumerate(expected):
                                expect(editor.locator(".split-cat").nth(i)).to_have_value(category)
                            saved = api.get(base + f"/api/money/transactions/{tid}/splits").json()[
                                "splits"
                            ]
                            assert [s["category"] for s in saved] == expected
                            assert [s["amount"] for s in saved] == (
                                [6, 4]
                                if case.endswith("add")
                                else [6 if case.startswith("refresh-") else 4]
                            )
                            assert not errors and not external
                            assert all("503" in m for m in console), console
                            record.update(status="passed", saved=saved)
                        except Exception as e:
                            record["error"] = str(e)
                        finally:
                            record.update(
                                page_errors=errors, console_errors=console, external=external
                            )
                            page.screenshot(path=str(out / f"{width}-{theme}-{case}.png"))
                            (out / "scenarios.json").write_text(
                                json.dumps(records, indent=2) + "\n"
                            )
                            context.close()
        finally:
            browser.close()
    assert all(r["status"] == "passed" for r in records), records


if __name__ == "__main__":
    run()
