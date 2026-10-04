"""Service-specific switch interactions with synthetic companion responses only."""

import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

BASE = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
rows = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    try:
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 844},
                service_workers="block",
                reduced_motion="reduce",
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlparse(route.request.url).netloc == urlparse(BASE).netloc
                    else route.abort()
                ),
            )
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(5000)
            errors, console = [], []
            page.on(
                "console",
                lambda message: console.append(message.text) if message.type == "error" else None,
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            row = {"width": width, "status": "failed"}
            rows.append(row)
            try:
                assert context.request.post(BASE + "/api/setup/dismiss").ok
                state = {"enabled": True, "calls": 0, "fail": False, "gets": 0}

                def fixtures(route):
                    path = urlparse(route.request.url).path
                    if path == "/api/system/companions":
                        route.fulfill(
                            json={
                                "companions": [
                                    {
                                        "service_id": key,
                                        "name": name,
                                        "prepared": True,
                                        "owned": True,
                                        "running": True,
                                        "healthy": True,
                                        "activated": True,
                                        "version": "fixture",
                                        "license": "fixture",
                                        "image": "fixture",
                                    }
                                    for key, name in [
                                        ("adguard-home", "DNS fixture"),
                                        ("nginx-proxy-manager", "proxy fixture"),
                                    ]
                                ]
                            }
                        )
                    elif path.endswith("adguard-home/dashboard"):
                        state["gets"] += 1
                        route.fulfill(
                            json={
                                "stats": {},
                                "filtering": {"enabled": state["enabled"], "interval": 24},
                                "rewrites": [],
                                "filters": [],
                            }
                        )
                    elif path.endswith("adguard-home/filtering"):
                        state["calls"] += 1
                        if state["fail"]:
                            route.fulfill(
                                status=503,
                                json={"detail": "synthetic filtering unavailable; try again"},
                            )
                        else:
                            state["enabled"] = route.request.post_data_json["enabled"]
                            route.fulfill(
                                json={"ok": True, "enabled": state["enabled"], "interval": 24}
                            )
                    elif path.endswith("nginx-proxy-manager/dashboard"):
                        route.fulfill(
                            json={"connected": True, "proxy_hosts": [], "certificates": []}
                        )
                    else:
                        route.abort()

                page.route(BASE + "/api/system/companions**", fixtures)
                page.goto(BASE + "/?view=server-services", wait_until="networkidle")
                dns = page.get_by_role("switch", name="DNS filtering", exact=True)
                page.get_by_label("domain", exact=True).fill("synthetic.local")
                page.get_by_role("textbox", name="answer", exact=True).fill("127.0.0.1")
                dns.focus()
                page.keyboard.press("Space")
                expect(dns).to_have_attribute("aria-checked", "false")
                page.screenshot(path=str(OUT / f"{width}-dns.png"))
                expect(dns).to_be_focused()
                assert state["calls"] == 1
                expect(page.get_by_label("domain", exact=True)).to_have_value("synthetic.local")
                expect(page.get_by_role("textbox", name="answer", exact=True)).to_have_value(
                    "127.0.0.1"
                )
                state["fail"] = True
                page.keyboard.press("Space")
                expect(dns).to_be_enabled()
                expect(dns).to_have_attribute("aria-checked", "false")
                expect(dns).to_be_focused()
                expect(
                    page.locator('.server-workbench-card[data-companion="adguard-home"]')
                ).to_contain_text("synthetic filtering unavailable")
                state["fail"] = False
                page.keyboard.press("Space")
                expect(dns).to_have_attribute("aria-checked", "true")
                expect(dns).to_be_enabled()
                expect(dns).to_be_focused()
                assert state["calls"] == 3 and state["gets"] == 1
                expect(
                    page.locator('.server-workbench-card[data-companion="adguard-home"]')
                ).not_to_contain_text("synthetic filtering unavailable")
                expect(page.get_by_label("domain", exact=True)).to_have_value("synthetic.local")
                proxy = page.get_by_role("switch", name="force HTTPS", exact=True)
                proxy.focus()
                page.keyboard.press("Space")
                expect(proxy).to_have_attribute("aria-checked", "true")
                expect(proxy).to_be_focused()
                page.keyboard.press("Space")
                expect(proxy).to_have_attribute("aria-checked", "false")
                expect(proxy).to_be_focused()
                page.screenshot(path=str(OUT / f"{width}-proxy.png"))
                page.reload(wait_until="networkidle")
                expect(dns).to_have_attribute("aria-checked", "true")
                assert state["gets"] == 2
                row["boundary"] = (
                    "browser fixtures for companion endpoints; no service control, DNS or proxy changes"
                )
                assert not errors, errors
                assert len(console) == 1 and "503" in console[0], console
                row["status"] = "passed"
            except Exception as error:
                row.update(error=str(error), traceback=traceback.format_exc())
            finally:
                row["page_errors"] = errors
                row["console_errors"] = console
                (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2))
                context.close()
    finally:
        browser.close()
raise SystemExit(any(row["status"] != "passed" for row in rows))
