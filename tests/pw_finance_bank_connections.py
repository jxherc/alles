"""Owned Finance bank dialog and OAuth return tests with synthetic provider responses only."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

SDK = r"""
window.Plaid = { create(config) {
  window.syntheticLinkCreates = (window.syntheticLinkCreates || 0) + 1;
  window.syntheticLinkConfig = {token: config.token, receivedRedirectUri: config.receivedRedirectUri};
  const layer = document.createElement('section');
  layer.setAttribute('role', 'dialog'); layer.setAttribute('aria-label', 'synthetic Plaid Link');
  layer.style.cssText = 'position:fixed;inset:16px;z-index:100000;background:#171717;color:#eceae6;padding:24px';
  layer.innerHTML = '<p>synthetic Plaid Link</p><button type="button">authorize test account</button><button type="button">cancel Link</button>';
  layer.querySelectorAll('button')[0].onclick = () => config.onSuccess('synthetic-public');
  layer.querySelectorAll('button')[1].onclick = () => config.onExit(null);
  return { open() { document.body.append(layer); layer.querySelector('button').focus(); }, destroy() { layer.remove(); } };
} };
"""


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, theme in [(1440, "dark"), (390, "light")]:
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            state = {
                "connections": [],
                "requests": [],
                "pending": [],
                "delay": "",
                "sdk_fail": True,
                "sdk_requests": 0,
            }
            errors, console, external = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )

            def fulfill(route, payload):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

            def route_request(route):
                request = route.request
                parsed = urlsplit(request.url)
                if request.url == "https://cdn.plaid.com/link/v2/stable/link-initialize.js":
                    state["sdk_requests"] += 1
                    if state["sdk_fail"]:
                        state["sdk_fail"] = False
                        route.fulfill(status=503, content_type="text/javascript", body="")
                    else:
                        route.fulfill(status=200, content_type="text/javascript", body=SDK)
                    return
                if parsed.netloc != urlsplit(base).netloc:
                    external.append(request.url)
                    route.abort("blockedbyclient")
                    return
                path = parsed.path
                if path.startswith("/api/finance/connections") and not path.endswith(
                    "/plaid/return"
                ):
                    if request.method == "GET":
                        fulfill(route, {"connections": state["connections"]})
                        return
                    state["requests"].append(
                        {"path": path, "method": request.method, "body": request.post_data_json}
                    )
                    if state["delay"] and path.endswith(state["delay"]):
                        state["pending"].append(route)
                        return
                    if path.endswith("/link-token"):
                        connection_id = path.split("/")[-3]
                        row = next(
                            item for item in state["connections"] if item["id"] == connection_id
                        )
                        fulfill(
                            route,
                            {
                                "link_token": "synthetic-original-link",
                                "expiration": "2099-10-16T00:00:00Z",
                                "redirect_uri": base + "/api/finance/connections/plaid/return",
                                "update_mode": bool(row.get("item_id")),
                            },
                        )
                    elif path.endswith("/exchange") or path.endswith("/update-complete"):
                        connection_id = path.split("/")[-3]
                        row = next(
                            item for item in state["connections"] if item["id"] == connection_id
                        )
                        row.update(status="connected", item_id="synthetic-item")
                        fulfill(route, row)
                    elif request.method == "DELETE":
                        connection_id = path.rsplit("/", 1)[-1]
                        state["connections"] = [
                            item for item in state["connections"] if item["id"] != connection_id
                        ]
                        fulfill(route, {"ok": True, "connection_id": connection_id})
                    else:
                        raise AssertionError(f"unhandled synthetic bank request: {path}")
                    return
                route.continue_()

            context.route("**/*", route_request)
            context.route_web_socket("**/*", lambda ws: ws.close())
            assert context.request.post(base + "/api/setup/dismiss").ok
            assert context.request.patch(
                base + "/api/settings", data={"theme": theme, "language": "en"}
            ).ok
            page.goto(base + "/?view=finance", wait_until="networkidle")
            page.locator('#finance-tabs [data-group-section="money"]').click()
            page.locator("#money-manage-toggle").click()
            page.locator("#money-connect").click()
            dialog = page.get_by_role("dialog", name="bank connections", exact=True)
            expect(dialog).to_be_visible()
            expect(dialog.get_by_role("button", name="close", exact=True)).to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(dialog.get_by_role("button", name="connect Plaid", exact=True)).to_be_focused()

            # Uncertain response cannot erase the one-time token.
            state["delay"] = "/simplefin"
            dialog.locator("#finance-simplefin-token").fill("exact one-time token")
            dialog.get_by_role("button", name="connect SimpleFIN", exact=True).click()
            expect(
                dialog.get_by_role("button", name="connect SimpleFIN", exact=True)
            ).to_be_disabled()
            assert len(state["pending"]) == 1
            fulfill(state["pending"].pop(), {})
            expect(dialog.locator(".finance-bank-status")).to_contain_text("not confirmed")
            expect(dialog.locator("#finance-simplefin-token")).to_have_value("exact one-time token")

            # The saved acknowledgment belongs to the submitted token, not newer input.
            dialog.get_by_role("button", name="connect SimpleFIN", exact=True).click()
            dialog.locator("#finance-simplefin-token").fill("newer token")
            row = {
                "id": "synthetic-simplefin",
                "provider": "simplefin",
                "label": "SimpleFIN",
                "status": "connected",
                "environment": "production",
            }
            state["connections"].append(row)
            fulfill(state["pending"].pop(), row)
            expect(dialog.locator("#finance-simplefin-token")).to_have_value("newer token")
            expect(dialog.locator('[data-bank-id="synthetic-simplefin"]')).to_be_visible()

            # Closing during configuration must not launch Link after the close.
            state["delay"] = "/plaid"
            dialog.locator("#finance-plaid-client").fill("synthetic-client")
            dialog.locator("#finance-plaid-secret").fill("synthetic-secret")
            dialog.get_by_role("button", name="connect Plaid", exact=True).click()
            dialog.get_by_role("button", name="close", exact=True).click()
            plaid = {
                "id": "synthetic-plaid",
                "provider": "plaid",
                "label": "Plaid",
                "status": "link_required",
                "environment": "sandbox",
            }
            state["connections"].append(plaid)
            fulfill(state["pending"].pop(), plaid)
            expect(page.locator("#money-connect")).to_be_focused()
            page.locator("#money-connect").click()
            expect(dialog.locator('[data-bank-id="synthetic-plaid"]')).to_contain_text(
                "sandbox · test accounts"
            )
            assert not any(item["path"].endswith("/link-token") for item in state["requests"])
            state["delay"] = ""

            # SDK failure is recoverable, then cancellation keeps the configured row.
            dialog.get_by_role("button", name="open Link", exact=True).click()
            expect(dialog.locator(".finance-bank-status")).to_contain_text("did not load")
            expect(page.locator("script[data-alles-plaid-link]")).to_have_count(0)
            dialog.get_by_role("button", name="open Link", exact=True).click()
            page.get_by_role("button", name="cancel Link", exact=True).click()
            expect(dialog.locator(".finance-bank-status")).to_contain_text("Link closed")
            expect(dialog.get_by_role("button", name="open Link", exact=True)).to_be_enabled()
            expect(dialog.get_by_role("button", name="close", exact=True)).to_be_focused()
            assert page.evaluate("sessionStorage.getItem('alles:finance-plaid-link')") is None
            assert state["sdk_requests"] == 2

            # Normal Link and reconnect both use the rendered provider fixture.
            dialog.get_by_role("button", name="open Link", exact=True).click()
            page.get_by_role("button", name="authorize test account", exact=True).click()
            expect(dialog.locator(".finance-bank-status")).to_contain_text("Plaid connected")
            dialog.get_by_role("button", name="reconnect", exact=True).click()
            page.get_by_role("button", name="authorize test account", exact=True).click()
            expect(dialog.locator(".finance-bank-status")).to_contain_text("Plaid connected")
            assert sum(item["path"].endswith("/exchange") for item in state["requests"]) == 1
            assert sum(item["path"].endswith("/update-complete") for item in state["requests"]) == 1

            # Sync is guarded, and it refreshes the ledger without clearing its drafts.
            state["delay"] = "/sync"
            bank_row = dialog.locator('[data-bank-id="synthetic-plaid"]')
            bank_row.get_by_role("button", name="sync", exact=True).click()
            expect(bank_row.get_by_role("button", name="sync", exact=True)).to_be_disabled()
            assert len(state["pending"]) == 1
            fulfill(state["pending"].pop(), {**plaid, "created": 0, "updated": 0})
            expect(dialog.locator(".finance-bank-status")).to_contain_text("sync complete")
            expect(
                dialog.get_by_role("button", name="refresh connections", exact=True)
            ).to_be_enabled()
            expect(dialog.get_by_role("button", name="close", exact=True)).to_be_focused()
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / f"bank-{width}-{theme}.png"))
            dialog.get_by_role("button", name="close", exact=True).click()

            # Resume on the real route using a same-tab, expiring synthetic binding.
            binding = {
                "connection_id": "synthetic-plaid",
                "link_token": "synthetic-resume-token",
                "expires_at": 4095792000000,
                "redirect_uri": base + "/api/finance/connections/plaid/return",
                "update_mode": True,
            }
            page.evaluate(
                "binding => sessionStorage.setItem('alles:finance-plaid-link', JSON.stringify(binding))",
                binding,
            )
            received = base + "/api/finance/connections/plaid/return?oauth_state_id=synthetic-state"
            page.goto(received, wait_until="networkidle")
            expect(
                page.get_by_role("button", name="authorize test account", exact=True)
            ).to_be_visible()
            assert page.evaluate("window.syntheticLinkConfig") == {
                "token": "synthetic-resume-token",
                "receivedRedirectUri": received,
            }
            page.get_by_role("button", name="authorize test account", exact=True).click()
            expect(page.locator("#plaid-return-status")).to_contain_text("Plaid connected")
            expect(page.locator("#plaid-return-retry")).to_be_hidden()
            back = page.get_by_role("link", name="return to Finance", exact=True)
            assert back.bounding_box()["height"] >= 44
            assert page.evaluate("sessionStorage.getItem('alles:finance-plaid-link')") is None
            page.screenshot(path=str(output / f"return-{width}-{theme}.png"))
            page.get_by_role("link", name="return to Finance", exact=True).click()
            page.locator('#finance-tabs [data-group-section="money"]').click()
            page.locator("#money-manage-toggle").click()
            expect(page.locator("#money-connect")).to_be_visible()
            page.goto(received, wait_until="networkidle")
            expect(page.locator("#plaid-return-status")).to_contain_text("missing or expired")
            expect(page.locator("#plaid-return-retry")).to_be_hidden()
            expect(
                page.get_by_role("button", name="authorize test account", exact=True)
            ).to_have_count(0)
            assert not errors and not external, {"errors": errors, "external": external}
            assert len(console) == 1 and "503" in console[0], console
            records.append(
                {
                    "profile": f"{width}-{theme}",
                    "status": "passed",
                    "scope": "synthetic providers; no real credentials or provider traffic",
                    "console": console,
                    "requests": state["requests"],
                    "states": [
                        "pending claim",
                        "malformed acknowledgment",
                        "newer input",
                        "close during config",
                        "SDK failure and retry",
                        "Link cancel",
                        "connect",
                        "reconnect",
                        "pending sync",
                        "same-tab OAuth return",
                        "expired return",
                        "keyboard focus",
                        "reduced motion",
                    ],
                }
            )
            context.tracing.stop(path=str(output / f"bank-{width}-{theme}-trace.zip"))
            context.close()
        browser.close()
    (output / "scenarios.json").write_text(json.dumps(records, indent=2))
    print(json.dumps({"status": "passed", "profiles": len(records)}))


if __name__ == "__main__":
    run()
