"""Local settings behavior evidence; disposable server only, no real providers."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
CASES = []


async def main():
    require_server_ownership(BASE, os.environ["ALLES_TEST_RUN_ID"])
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for width in (1440, 390):
            context = await browser.new_context(
                viewport={"width": width, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            overrides, calls, errors, console, outside, rules = {}, [], [], [], [], []

            async def intercept(route):
                request = route.request
                u = urlparse(request.url)
                key = (u.path, request.method)
                if u.netloc != urlparse(BASE).netloc:
                    outside.append(request.url)
                    await route.abort()
                    return
                calls.append({"path": u.path, "method": request.method})
                response = overrides.get(key)
                if response:
                    if response.get("wait"):
                        await response["wait"].wait()
                    await route.fulfill(
                        status=response.get("status", 200), json=response.get("body", {})
                    )
                    return
                if u.path == "/api/automations":
                    if request.method == "POST":
                        data = request.post_data_json
                        data.update(id=f"synthetic-{len(rules) + 1}", enabled=True)
                        rules.append(data)
                        await route.fulfill(json=data)
                        return
                    if request.method == "GET":
                        await route.fulfill(json=rules)
                        return
                if u.path.startswith("/api/automations/synthetic-"):
                    ident = u.path.split("/")[3]
                    row = next((r for r in rules if r["id"] == ident), None)
                    if request.method == "PATCH":
                        row.update(request.post_data_json)
                        await route.fulfill(json=row)
                        return
                    if request.method == "DELETE":
                        rules.remove(row)
                        await route.fulfill(json={"ok": True})
                        return
                    if u.path.endswith("/test"):
                        await route.fulfill(json={"ok": True})
                        return
                if (
                    u.path
                    in [
                        "/api/auth/config",
                        "/api/auth/change-password",
                        "/api/research",
                        "/api/search/test",
                        "/api/proactive/run",
                        "/api/insights/run",
                        "/api/memory/distill/run",
                    ]
                    and request.method == "POST"
                ):
                    await route.fulfill(
                        status=503, json={"detail": "synthetic unavailable; no provider call"}
                    )
                    return
                await route.continue_()

            await context.route("**/*", intercept)
            await context.route_web_socket("**/*", lambda socket: socket.close())
            await context.request.post(BASE + "/api/setup/dismiss")
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    console.append({"type": message.type, "text": message.text})
                    if message.type == "error"
                    else None
                ),
            )

            async def record(pane, name, ok, detail=None):
                path = OUT / f"{width}-{pane}-{name}.png"
                await page.screenshot(path=str(path))
                row = {
                    "profile": str(width),
                    "pane": pane,
                    "case": name,
                    "status": "passed" if ok else "failed",
                    "detail": detail,
                    "screenshot": str(path),
                }
                CASES.append(row)
                (OUT / "scenarios.json").write_text(json.dumps(CASES, indent=2) + "\n")
                print(json.dumps(row), flush=True)

            async def section(name):
                trigger = page.locator("#settings-section-trigger")
                if (
                    await trigger.is_visible()
                    and await trigger.get_attribute("aria-expanded") != "true"
                ):
                    await trigger.click()
                await page.locator(f'.s-nav-item[data-pane="{name}"]').click()
                await expect(page.locator("#s-pane-" + name)).to_be_visible()
                await page.wait_for_timeout(250)

            async def fresh(name):
                await page.goto(BASE + "/?view=today", wait_until="networkidle")
                await page.locator("#today-settings").click()
                await section(name)

            async def settings():
                return await (await context.request.get(BASE + "/api/settings")).json()

            async def count(path, method="POST"):
                return sum(c["path"] == path and c["method"] == method for c in calls)

            async def run_button(pane, selector, path, status_selector, success):
                button = page.locator(selector)
                button_count = await count(path)
                hold = asyncio.Event()
                overrides[(path, "POST")] = {
                    "wait": hold,
                    "status": 503,
                    "body": {"detail": "synthetic unavailable"},
                }
                await button.click()
                await page.wait_for_timeout(100)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(100)
                pending = await button.is_disabled() and await count(path) == button_count + 1
                await record(
                    pane,
                    selector[1:] + "-pending-repeat",
                    pending,
                    {
                        "calls": await count(path) - button_count,
                        "disabled": await button.is_disabled(),
                    },
                )
                hold.set()
                await expect(button).to_be_enabled()
                await page.wait_for_timeout(100)
                status = (
                    await page.locator(status_selector).inner_text()
                    if status_selector
                    else " | ".join(await page.locator(".toast").all_text_contents())
                )
                await record(
                    pane,
                    selector[1:] + "-failed",
                    "fail" in status.lower() or "error" in status.lower(),
                    status[-500:],
                )
                overrides[(path, "POST")] = {"body": success}
                await button.click()
                await expect(button).to_be_enabled()
                await page.wait_for_timeout(100)
                status = (
                    await page.locator(status_selector).inner_text()
                    if status_selector
                    else " | ".join(await page.locator(".toast").all_text_contents())
                )
                await record(
                    pane,
                    selector[1:] + "-retry",
                    not ("failed" in status.lower() or "error:" in status.lower())
                    if status_selector
                    else (await button.is_enabled() and await count(path) == button_count + 2),
                    status[-500:],
                )
                overrides.pop((path, "POST"))

            for pane, selector, key in [
                ("ai", "#s-thinking-toggle", "stream_thinking"),
                ("proactive", "#s-prox-enabled", "pidx_proactive_enabled"),
                ("intelligence", "#s-intel-insights", "insights_enabled"),
                ("recall", "#s-pidx-enabled", "pidx_enabled"),
                ("andromeda", "#s-andromeda-results", "andromeda_normal_results"),
            ]:
                await fresh(pane)
                sw = page.locator(selector)
                await sw.scroll_into_view_if_needed()
                before = await sw.get_attribute("aria-checked") == "true"
                await sw.focus()
                await page.keyboard.press("Space")
                await page.wait_for_timeout(250)
                actual = await settings()
                now = await sw.get_attribute("aria-checked") == "true"
                await record(
                    pane,
                    "keyboard-toggle-persist",
                    now != before and actual[key] == now,
                    {
                        "before": before,
                        "display": now,
                        "stored": actual[key],
                        "focused": await sw.evaluate("(el)=>el===document.activeElement"),
                    },
                )
                overrides[("/api/settings", "PATCH")] = {
                    "status": 503,
                    "body": {"detail": "synthetic save refused"},
                }
                await sw.press("Space")
                await page.wait_for_timeout(250)
                rejected = await sw.get_attribute("aria-checked") == "true"
                error = await page.locator("#s-pane-" + pane + " .settings-save-state").inner_text()
                await record(
                    pane,
                    "refused-toggle-restores-confirmed",
                    rejected == now,
                    {"confirmed": now, "display": rejected, "status": error},
                )
                overrides.pop(("/api/settings", "PATCH"))
                await section("general")
                await section(pane)
                await record(
                    pane,
                    "reopen-recovers-confirmed",
                    (await sw.get_attribute("aria-checked") == "true") == now,
                )
                if pane == "ai":
                    inp = page.locator("#settings-context-limit")
                    await inp.fill("64")
                    await page.locator("#settings-save-btn").click()
                    await page.wait_for_timeout(250)
                    await record(pane, "context-save", (await settings())["context_limit"] == 64)
                elif pane == "proactive":
                    await run_button(
                        pane,
                        "#s-prox-run",
                        "/api/proactive/run",
                        "#s-prox-status",
                        {"ran": True, "written": 2, "signals": 3},
                    )
                    overrides[("/api/proactive/run", "POST")] = {
                        "body": {"ran": False, "reason": "no_provider"}
                    }
                    await page.locator("#s-prox-run").click()
                    await page.wait_for_timeout(100)
                    await record(
                        pane,
                        "no-provider",
                        "not run (no provider)"
                        in await page.locator("#s-prox-status").inner_text(),
                    )
                    overrides.pop(("/api/proactive/run", "POST"))
                elif pane == "intelligence":
                    await run_button(
                        pane,
                        "#s-intel-insights-run",
                        "/api/insights/run",
                        "#s-intel-status",
                        {"ran": True, "count": 2},
                    )
                    await run_button(
                        pane,
                        "#s-intel-distill-run",
                        "/api/memory/distill/run",
                        "#s-intel-status",
                        {"ran": True, "count": 3},
                    )
                elif pane == "recall":
                    await run_button(
                        pane,
                        "#s-pidx-reindex",
                        "/api/recall/reindex",
                        None,
                        {"indexed": {"note": 0}},
                    )
                    clear = page.locator("#s-pidx-clear")
                    baseline = await count("/api/recall/clear")
                    await clear.click()
                    await page.keyboard.press("Escape")
                    await record(
                        pane,
                        "clear-cancel",
                        await count("/api/recall/clear") == baseline
                        and await clear.evaluate("(el)=>el===document.activeElement"),
                    )
                    await page.wait_for_timeout(3300)
                    overrides[("/api/recall/clear", "POST")] = {
                        "status": 503,
                        "body": {"detail": "synthetic clear refused"},
                    }
                    await clear.click()
                    await page.locator("[data-dialog-confirm]").click()
                    await page.wait_for_timeout(250)
                    visible = await page.locator("#s-pane-recall").inner_text()
                    toasts = await page.locator(".toast").all_text_contents()
                    await record(
                        pane,
                        "clear-refusal-visible",
                        any(
                            "fail" in t or "refused" in t or "error" in t or "could not" in t
                            for t in toasts
                        ),
                        {"pane": visible, "toasts": toasts},
                    )
                    overrides.pop(("/api/recall/clear", "POST"))
                    hold = asyncio.Event()
                    overrides[("/api/recall/clear", "POST")] = {"wait": hold, "body": {}}
                    baseline = await count("/api/recall/clear")
                    await clear.click()
                    await page.locator("[data-dialog-confirm]").click()
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(100)
                    await record(
                        pane,
                        "clear-pending-repeat",
                        await clear.is_disabled()
                        and await count("/api/recall/clear") == baseline + 1,
                    )
                    await section("security")
                    newdraft = page.locator("#s-pw-new")
                    await newdraft.fill("synthetic-active-draft")
                    await newdraft.focus()
                    hold.set()
                    await page.wait_for_timeout(200)
                    await record(
                        pane,
                        "clear-malformed-no-focus-theft",
                        await newdraft.input_value() == "synthetic-active-draft"
                        and await newdraft.evaluate("(el)=>el===document.activeElement"),
                        await page.locator(".toast").all_text_contents(),
                    )
                    overrides[("/api/recall/clear", "POST")] = {"body": {"removed": 0}}
                    await section("recall")
                    await clear.click()
                    await page.locator("[data-dialog-confirm]").click()
                    await expect(clear).to_be_enabled()
                    await record(
                        pane, "clear-valid-retry", await count("/api/recall/clear") == baseline + 2
                    )
                    overrides.pop(("/api/recall/clear", "POST"))
                elif pane == "andromeda":
                    provider = page.locator("#s-andromeda-primary")
                    await provider.focus()
                    await page.keyboard.press("Enter")
                    await page.keyboard.press("End")
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(250)
                    await page.locator("#s-andromeda-test").click()
                    await record(
                        pane,
                        "disabled-provider-keyboard",
                        await provider.get_attribute("data-value") == "disabled"
                        and "disabled"
                        in await page.locator("#s-andromeda-search-status").inner_text(),
                    )
                    await provider.focus()
                    await page.keyboard.press("Enter")
                    await page.keyboard.press("Home")
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(250)
                    await run_button(
                        pane,
                        "#s-andromeda-test",
                        # the engine check moved from research to its own endpoint
                        "/api/search/test",
                        "#s-andromeda-search-status",
                        {"ok": True, "count": 5, "ms": 12},
                    )

            await fresh("security")
            blur = page.locator("#s-sensitive-blur-toggle")
            before = await blur.get_attribute("aria-checked")
            await blur.focus()
            await page.keyboard.press("Space")
            after = await blur.get_attribute("aria-checked")
            await section("general")
            await section("security")
            await record(
                "security",
                "privacy-keyboard-persistence",
                before != after and await blur.get_attribute("aria-checked") == after,
            )
            pwnew = page.locator("#s-pw-new")
            pwconf = page.locator("#s-pw-new2")
            pwbtn = page.locator("#s-pw-save")
            baseline = await count("/api/auth/change-password")
            await pwnew.fill("short")
            await pwconf.fill("short")
            await pwbtn.click()
            await record(
                "security", "password-minimum", await count("/api/auth/change-password") == baseline
            )
            await pwnew.fill("synthetic-new-pass")
            await pwconf.fill("different-synthetic")
            await pwbtn.click()
            await record(
                "security",
                "password-mismatch",
                await count("/api/auth/change-password") == baseline,
            )
            await pwconf.fill("synthetic-new-pass")
            await page.locator("#s-pw-old").fill("synthetic-old-pass")
            hold = asyncio.Event()
            overrides[("/api/auth/change-password", "POST")] = {
                "wait": hold,
                "status": 503,
                "body": {"detail": "synthetic password refusal"},
            }
            await pwbtn.click()
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            await record(
                "security",
                "password-pending-repeat",
                await pwbtn.is_disabled()
                and await count("/api/auth/change-password") == baseline + 1,
            )
            await pwnew.fill("newer-synthetic-pass")
            hold.set()
            await expect(pwbtn).to_be_enabled()
            await record(
                "security",
                "password-refusal-retains-new-draft",
                await pwnew.input_value() == "newer-synthetic-pass",
            )
            overrides[("/api/auth/change-password", "POST")] = {"body": {"ok": True}}
            await pwconf.fill("newer-synthetic-pass")
            await pwbtn.click()
            await expect(pwnew).to_have_value("")
            await record(
                "security",
                "password-synthetic-ack-clears-submitted",
                await pwconf.input_value() == "",
            )
            auth = page.locator("#s-auth-enable")
            oldauth = await auth.get_attribute("aria-checked")
            await auth.click()
            await page.wait_for_timeout(150)
            await record(
                "security",
                "auth-refusal-keeps-state",
                await auth.get_attribute("aria-checked") == oldauth,
            )

            await fresh("rules")
            await page.locator(".rule-preset").first.click()
            await page.locator("#rule-name").fill("synthetic rule")
            hold = asyncio.Event()
            overrides[("/api/automations", "POST")] = {
                "wait": hold,
                "status": 503,
                "body": {"detail": "synthetic rule refusal"},
            }
            await page.locator("#rule-add-btn").click()
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            await record(
                "rules",
                "create-pending-repeat",
                await page.locator("#rule-add-btn").is_disabled()
                and await count("/api/automations") == 1,
            )
            hold.set()
            await expect(page.locator("#rule-add-btn")).to_be_enabled()
            await record(
                "rules",
                "create-refusal-retains-draft",
                await page.locator("#rule-name").input_value() == "synthetic rule",
            )
            overrides.pop(("/api/automations", "POST"))
            await page.locator("#rule-add-btn").click()
            await expect(page.locator(".rule-row")).to_have_count(1)
            await record("rules", "create-retry", True)
            await page.locator(".rule-row-main").click()
            await page.locator("#rule-name").fill("unsaved replacement")
            await page.locator("#rule-cancel-btn").click()
            await record(
                "rules",
                "edit-cancel",
                await page.locator(".rule-row-name").inner_text() == "synthetic rule"
                and await page.locator("#rule-name").input_value() == "",
            )
            await page.locator('[data-act="toggle"]').click()
            await expect(page.locator(".rule-row")).to_have_class("rule-row off")
            await record("rules", "pause-resume", True)
            await page.locator('[data-act="toggle"]').click()
            await expect(page.locator(".rule-row")).to_have_class("rule-row")
            await run_button(
                "rules",
                '[data-act="test"]',
                "/api/automations/synthetic-1/test",
                None,
                {"ok": True},
            )
            await page.wait_for_timeout(3300)
            hold = asyncio.Event()
            overrides[("/api/automations/synthetic-1", "DELETE")] = {
                "wait": hold,
                "status": 503,
                "body": {"detail": "synthetic delete refused"},
            }
            await page.locator('[data-act="del"]').click()
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            await record(
                "rules",
                "delete-pending-repeat",
                await page.locator('[data-act="del"]').is_disabled()
                and await count("/api/automations/synthetic-1", "DELETE") == 1,
            )
            await page.locator("#rule-name").fill("new draft while deleting")
            await page.locator("#rule-name").focus()
            hold.set()
            await page.wait_for_timeout(200)
            await record(
                "rules",
                "delete-refusal-preserves-new-draft",
                await page.locator("#rule-name").input_value() == "new draft while deleting"
                and await page.locator("#rule-name").evaluate("(el)=>el===document.activeElement"),
            )
            toasts = await page.locator(".toast").all_text_contents()
            await record(
                "rules",
                "delete-refusal-visible",
                any(
                    "fail" in t or "refused" in t or "error" in t or "could not" in t
                    for t in toasts
                ),
                {"toasts": toasts, "rows": await page.locator(".rule-row").count()},
            )
            overrides.pop(("/api/automations/synthetic-1", "DELETE"))
            await page.locator('[data-act="del"]').click()
            await expect(page.locator(".rule-row")).to_have_count(0)
            await record("rules", "delete-retry", True)

            # First-read failures must be visible and recover by reopening.
            for pane in ["ai", "proactive", "intelligence", "recall", "andromeda", "rules"]:
                overrides[("/api/settings", "GET")] = {
                    "status": 503,
                    "body": {"detail": "synthetic settings load refusal"},
                }
                if pane == "rules":
                    overrides[("/api/automations/options", "GET")] = {
                        "status": 503,
                        "body": {"detail": "synthetic options refusal"},
                    }
                error_start = len(errors)
                await fresh(pane)
                await page.wait_for_timeout(250)
                texts = await page.locator(".toast").all_text_contents()
                await record(
                    pane,
                    "failed-load-visible",
                    any(
                        "load" in t and ("could not" in t or "fail" in t or "refus" in t)
                        for t in texts
                    ),
                    {"toasts": texts, "pageerrors": errors[error_start:]},
                )
                overrides.pop(("/api/settings", "GET"))
                overrides.pop(("/api/automations/options", "GET"), None)
                await section("general")
                await section(pane)
                await record(
                    pane,
                    "failed-load-reopen",
                    not errors[error_start:],
                    {"pageerrors": errors[error_start:]},
                )
            (OUT / f"{width}-events.json").write_text(
                json.dumps(
                    {
                        "pageerrors": errors,
                        "console": console,
                        "external": outside,
                        "requests": calls,
                    },
                    indent=2,
                )
                + "\n"
            )
            assert not errors, errors
            assert not outside, outside
            await context.close()
        await browser.close()
    summary = {
        "cases": len(CASES),
        "passed": sum(x["status"] == "passed" for x in CASES),
        "failed": sum(x["status"] == "failed" for x in CASES),
        "scope": "synthetic settings writes, mocked automation/password/provider responses; no live provider/model/password/security mutation",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


asyncio.run(main())
raise SystemExit(1 if any(row["status"] == "failed" for row in CASES) else 0)
