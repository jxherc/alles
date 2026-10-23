"""Aide utility recovery with synthetic HTTP on an owned isolated server.

Runs production handlers at desktop and phone widths. No provider executes.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.appearance import from_legacy  # noqa: E402

OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
OUT.mkdir(parents=True, exist_ok=True)
BASE = f"http://127.0.0.1:{os.environ['PORT']}"
DATA = Path(os.environ["ALLES_DATA"]).resolve()
RUN_ID = os.environ["ALLES_TEST_RUN_ID"]
assert os.environ.get("ALLES_TEST_DATA") == "1"
assert (DATA / ".alles-test-owner").read_text().strip() == RUN_ID
require_server_ownership(BASE, RUN_ID)
ROWS = []


def record(profile, surface, case, passed, detail=""):
    ROWS.append(
        dict(
            profile=profile,
            surface=surface,
            case=case,
            status="passed" if passed else "failed",
            detail=detail,
        )
    )
    (OUT / "cases.json").write_text(json.dumps(ROWS, indent=2) + "\n")


def endpoint(name):
    return [
        dict(
            id="fixture",
            name="Fixture",
            provider="openai",
            base_url="http://127.0.0.1:9/v1",
            enabled=True,
            models=[name],
            cached_models=[name],
            image_models=[],
            vision_models=[],
        )
    ]


def model(name):
    return dict(
        name=name,
        params_b=7,
        quant="Q4_K_M",
        run_mode="cpu",
        required_gb=5,
        speed_tps=12,
        fit_level="good",
        score=81,
        installed=False,
        is_moe=False,
    )


def usage(name):
    return dict(
        total_tokens=12000,
        total_prompt=7000,
        total_completion=5000,
        total_messages=4,
        by_month=[dict(name="oct", total=12000)],
        by_model=[dict(name=name, prompt=7000, completion=5000, total=12000, messages=4)],
    )


# Install before app boot so its scoped fetcher sees the same delayed delivery.
FETCH_DELIVERY = """(() => {
  const original = window.fetch;
  window.__holdFetch = match => {
    window.__fetchMatch = match;
    window.__held = false;
    window.__release = null;
  };
  window.fetch = async (...args) => {
    const response = await original(...args);
    if (window.__fetchMatch && String(args[0]).includes(window.__fetchMatch)) {
      window.__fetchMatch = null;
      window.__held = true;
      await new Promise(resolve => window.__release = resolve);
    }
    return response;
  };
})()"""
HOLD = "match => window.__holdFetch(match)"


async def run(browser, width):
    profile = str(width)
    ctx = await browser.new_context(
        viewport={"width": width, "height": 900 if width == 1440 else 844},
        service_workers="block",
        reduced_motion="reduce",
        locale="en-US",
    )
    await ctx.add_init_script(FETCH_DELIVERY)
    events = []
    state = {
        "surface": "",
        "mode": "normal",
        "serial": 0,
        "posts": [],
        "enabled": True,
        "runstate": "running",
        "gallery_deleted": False,
    }

    async def route(rt):
        req = rt.request
        u = urlsplit(req.url)
        p = u.path
        if u.netloc != urlsplit(BASE).netloc:
            events.append({"external": req.url})
            await rt.abort()
            return

        async def ok(x, status=200):
            await rt.fulfill(json=x, status=status)

        if p == "/api/models":
            if state["surface"] == "models":
                state["serial"] += 1
                if state["mode"] == "error":
                    return await ok({"detail": "catalog unavailable"}, 503)
                return await ok(
                    endpoint(
                        "fixture-old"
                        if state["mode"] == "stale" and state["serial"] == 1
                        else "fixture-new"
                        if state["mode"] == "stale"
                        else "fixture-chat"
                    )
                )
            return await ok([])
        if state["surface"] == "models" and p == "/api/models/roles":
            return await ok({"aide_chat": {"status": "unavailable"}})
        if (
            state["surface"] == "models"
            and p.startswith("/api/sessions/")
            and req.method == "PATCH"
        ):
            state["posts"].append(p)
            return await ok({"ok": True})
        if state["surface"] == "brain":
            if p == "/api/memories":
                state["serial"] += 1
                if state["mode"] == "error":
                    return await ok({"detail": "memory unavailable"}, 503)
                text = (
                    "old memory"
                    if state["mode"] == "stale" and state["serial"] == 1
                    else "new memory"
                    if state["mode"] == "stale"
                    else "prefers exact examples"
                )
                return await ok(
                    [{"id": "memory1", "text": text, "category": "preference", "pinned": True}]
                )
            if p == "/api/insights":
                return await ok(
                    []
                    if state["mode"] == "disabled"
                    else [
                        {
                            "id": "ins1",
                            "title": "synthetic insight",
                            "body": "review first",
                            "evidence": ["owned fixture"],
                            "pinned": False,
                        }
                    ]
                )
            if p == "/api/memory/distilled":
                return await ok(
                    []
                    if state["mode"] == "disabled"
                    else [
                        {
                            "id": "fact1",
                            "text": "synthetic learned fact",
                            "confidence": 1.8,
                            "provenance": "fixture",
                            "vetoed": False,
                            "pinned": False,
                        }
                    ]
                )
            if (
                p.startswith("/api/insights/")
                or p.startswith("/api/memory/")
                or p == "/api/memories/fact1"
            ):
                state["posts"].append(p)
                return await ok({"ok": True})
        if state["surface"] == "cookbook":
            if p == "/api/local-models/system":
                return await ok(
                    dict(
                        cpu_name="owned fixture cpu",
                        total_ram_gb=32,
                        has_gpu=False,
                        backend="fixture",
                    )
                )
            if p == "/api/local-models/catalog":
                q = parse_qs(u.query).get("search", [""])[0]
                if q == "error":
                    return await ok({"detail": "fixture failure"}, 503)
                return await ok(
                    {"models": [] if q == "none" else [model("fixture/" + (q or "model"))]}
                )
        if state["surface"] == "usage" and p == "/api/usage/summary":
            state["serial"] += 1
            if state["mode"] == "error":
                return await ok({"detail": "usage unavailable"}, 503)
            return await ok(
                usage(
                    "old model"
                    if state["mode"] == "stale" and state["serial"] == 1
                    else "new model"
                    if state["mode"] == "stale"
                    else "fixture-model"
                )
            )
        if state["surface"] == "gallery":
            if p == "/api/gallery" and req.method == "GET":
                if state["mode"] == "error":
                    return await ok({"detail": "gallery unavailable"}, 503)
                return await ok(
                    {
                        "items": []
                        if state["gallery_deleted"]
                        else [
                            {
                                "id": "img1",
                                "prompt": "synthetic gallery image",
                                "owner": "gallery",
                                "url": "/static/icons/icon-192.png",
                            }
                        ],
                        "next": None,
                    }
                )
            if p == "/api/gallery/img1" and req.method == "DELETE":
                state["posts"].append(p)
                if state["mode"] == "delete-error":
                    return await ok({"detail": "refused"}, 503)
                state["gallery_deleted"] = True
                return await ok({"ok": True})
            if p == "/api/gallery/upload":
                state["posts"].append(p)
                return await ok({"id": "upload-fixture"})
        if state["surface"] == "scheduled":
            wf = dict(
                id="wf1",
                name="synthetic schedule",
                prompt="synthetic prompt",
                enabled=state["enabled"],
                deterministic_action="aide_handoff",
                delivery_policy={"aide_schedule_owner": "aide_scheduled_v1"},
            )
            if p == "/api/jarvis/workflows":
                return await ok([wf])
            if p == "/api/jarvis/workflows/wf1/triggers":
                return await ok(
                    [
                        {
                            "id": "tr1",
                            "kind": "schedule",
                            "enabled": state["enabled"],
                            "config": {"time": "09:00"},
                        }
                    ]
                )
            if p == "/api/jarvis/runs":
                return await ok(
                    [
                        dict(
                            id="run1",
                            workflow_id="wf1",
                            state=state["runstate"],
                            result_summary="synthetic run",
                            created_at="2026-10-16T12:00:00Z",
                        )
                    ]
                )
            if p == "/api/jarvis/aide-schedules/wf1/state":
                state["posts"].append(p)
                state["enabled"] = req.post_data_json["enabled"]
                return await ok({"ok": True})
            if p == "/api/jarvis/runs/run1/cancel":
                state["posts"].append(p)
                state["runstate"] = "cancelled"
                return await ok({"ok": True})
            if p == "/api/jarvis/runs/run1/retry":
                state["posts"].append(p)
                state["runstate"] = "running"
                return await ok({"ok": True})
            if p == "/api/jarvis/aide-schedules":
                state["posts"].append(p)
                if state["mode"] == "save-error":
                    return await ok({"detail": "fixture save refused"}, 503)
                return await ok({"id": "created-fixture"})
        await rt.continue_()

    await ctx.route("**/*", route)
    await ctx.route_web_socket("**/*", lambda ws: ws.close())
    assert (await ctx.request.post(BASE + "/api/setup/dismiss")).ok
    assert (
        await ctx.request.put(
            BASE + "/api/appearance", data=from_legacy("dark" if width == 1440 else "light", None)
        )
    ).ok
    page = await ctx.new_page()
    page.set_default_timeout(7000)
    page.on("pageerror", lambda e: events.append({"pageerror": str(e)}))
    page.on("console", lambda m: events.append({"console": m.text}) if m.type == "error" else None)

    async def nav(view):
        await page.evaluate("(v)=>window._navigateTo(v)", view)

    async def shot(name):
        await page.screenshot(path=str(OUT / f"{profile}-{name}.png"), full_page=False)

    for surface in ["models", "brain", "cookbook", "usage", "gallery", "scheduled"]:
        state.update(
            surface=surface,
            mode="normal",
            serial=0,
            posts=[],
            enabled=True,
            runstate="running",
            gallery_deleted=False,
        )
        start = len(events)
        try:
            await page.goto(BASE + "/?view=" + surface, wait_until="networkidle")
            if surface == "models":
                await expect(page.locator("#sidebar-model-list")).to_contain_text("fixture chat")
                await page.locator("#sidebar-model-search").fill("absent")
                await expect(page.locator("#sidebar-model-list")).to_contain_text("no models found")
                await page.locator("#sidebar-model-search").fill("fixture")
                b = page.locator(".sidebar-model-row").first
                await b.focus()
                await b.press("Enter")
                await expect(b).to_have_class("sidebar-model-row active")
                record(profile, surface, "populated filter no-match and keyboard selection", True)
                await shot("models-loaded")
                state.update(mode="error")
                await page.locator("#models-refresh-btn").click()
                await page.wait_for_timeout(150)
                visible = await page.locator("#models-view").inner_text()
                record(
                    profile,
                    surface,
                    "failed refresh reports status while retaining catalog",
                    any(s in visible.lower() for s in ["failed", "unavailable", "could not"]),
                    visible,
                )
                await shot("models-error")
                state.update(mode="normal")
                await page.locator("#models-load-status button").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#models-load-status")).to_be_hidden()
                record(profile, surface, "keyboard retry recovers catalog", True)
                state.update(mode="stale", serial=0)
                await page.evaluate(HOLD, "/api/models")
                await page.locator("#models-refresh-btn").click()
                await page.wait_for_function("window.__held")
                await page.locator("#models-refresh-btn").click()
                await expect(page.locator("#sidebar-model-list")).to_contain_text("fixture new")
                await page.evaluate("window.__release()")
                await page.wait_for_timeout(100)
                visible = await page.locator("#sidebar-model-list").inner_text()
                record(
                    profile,
                    surface,
                    "late catalog cannot overwrite newer refresh",
                    "fixture new" in visible,
                    visible,
                )
                await shot("models-stale")
            elif surface == "brain":
                await expect(page.locator("#brain-memories")).to_contain_text(
                    "prefers exact examples"
                )
                await expect(page.locator("#brain-insights")).to_contain_text("synthetic insight")
                await expect(page.locator("#brain-usermodel")).to_contain_text("100%")
                await page.locator("[data-ins-pin]").focus()
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(100)
                record(
                    profile,
                    surface,
                    "memory insight learned fact and keyboard pin",
                    len(state["posts"]) == 1,
                )
                await shot("brain-loaded")
                await page.locator("#brain-refresh-btn").click()
                await page.wait_for_timeout(100)
                record(
                    profile,
                    surface,
                    "refresh button completes without exception",
                    not any("fetcher is not a function" in str(e) for e in events[start:]),
                    str(events[start:]),
                )
                state.update(mode="disabled")
                await nav("usage")
                await nav("brain")
                await expect(page.locator("#brain-insights")).to_contain_text("insights are off")
                await page.locator("#brain-insights [data-open-pane]").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#settings-modal")).to_be_visible()
                await page.keyboard.press("Escape")
                record(profile, surface, "disabled shortcut opens settings by keyboard", True)
                state.update(mode="error")
                await nav("usage")
                await nav("brain")
                await expect(page.locator("#brain-memories")).to_contain_text(
                    "could not load memories"
                )
                record(
                    profile, surface, "failed memory read remains distinguishable from empty", True
                )
                await shot("brain-read-error")
                state.update(mode="stale", serial=0)
                await page.evaluate(HOLD, "/api/memories")
                await page.locator("#brain-refresh-btn").click()
                await page.wait_for_function("window.__held")
                await page.locator("#brain-refresh-btn").click()
                await expect(page.locator("#brain-memories")).to_contain_text("new memory")
                await page.evaluate("window.__release()")
                await page.wait_for_timeout(100)
                text = await page.locator("#brain-memories").inner_text()
                record(
                    profile,
                    surface,
                    "late refresh cannot replace newer memory",
                    "new memory" in text,
                    text,
                )
                await expect(page.locator("#brain-view > .specialist-state")).to_be_hidden()
                record(profile, surface, "successful refresh clears prior partial banner", True)
                await shot("brain-stale")
            elif surface == "cookbook":
                await expect(page.locator("#cb-table")).to_contain_text("fixture/model")
                await page.locator("#cb-fitonly").focus()
                await page.keyboard.press("Space")
                await expect(page.locator("#cb-fitonly")).to_have_attribute("aria-checked", "false")
                await page.locator("#cb-usecase").focus()
                await page.keyboard.press("Enter")
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                record(profile, surface, "loaded catalog keyboard switch and custom choice", True)
                await shot("cookbook-loaded")
                await page.locator("#cb-search").fill("none")
                await expect(page.locator("#cb-table")).to_contain_text("no models match")
                await page.locator("#cb-search").fill("error")
                await expect(page.locator("#cb-table")).to_contain_text("catalog failed")
                record(profile, surface, "no-match and failed query states", True)
                await page.evaluate(HOLD, "search=old")
                await page.locator("#cb-search").fill("old")
                await page.wait_for_function("window.__held")
                await page.locator("#cb-search").fill("new")
                await expect(page.locator("#cb-table")).to_contain_text("fixture/new")
                await page.evaluate("window.__release()")
                await page.wait_for_timeout(100)
                text = await page.locator("#cb-table").inner_text()
                record(
                    profile,
                    surface,
                    "late query cannot overwrite new filter",
                    "fixture/new" in text,
                    text,
                )
                await shot("cookbook-stale")
            elif surface == "usage":
                await expect(page.locator("#usage-total")).to_contain_text("12.0k tokens")
                await expect(page.locator("#usage-body")).to_contain_text("fixture-model")
                record(profile, surface, "populated totals month and model breakdown", True)
                await shot("usage-loaded")
                state.update(mode="error")
                await nav("brain")
                await nav("usage")
                await page.wait_for_timeout(100)
                text = await page.locator("#usage-view").inner_text()
                record(
                    profile,
                    surface,
                    "failed summary does not impersonate empty or undefined",
                    ("failed" in text.lower() or "unavailable" in text.lower())
                    and "undefined" not in text,
                    text,
                )
                await shot("usage-error")
                state.update(mode="normal")
                await page.locator("#usage-retry").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#usage-body")).to_contain_text("fixture-model")
                record(profile, surface, "keyboard retry recovers summary", True)
                state.update(mode="stale", serial=0)
                await nav("brain")
                await page.evaluate(HOLD, "/api/usage/summary")
                await nav("usage")
                await page.wait_for_function("window.__held")
                await nav("brain")
                await nav("usage")
                await expect(page.locator("#usage-body")).to_contain_text("new model")
                await page.evaluate("window.__release()")
                await page.wait_for_timeout(100)
                text = await page.locator("#usage-body").inner_text()
                record(
                    profile,
                    surface,
                    "navigation excludes older usage result",
                    "new model" in text,
                    text,
                )
                await shot("usage-stale")
            elif surface == "gallery":
                await expect(page.locator("#gallery-grid")).to_contain_text(
                    "synthetic gallery image"
                )
                await page.locator(".gallery-del").focus()
                await page.keyboard.press("Enter")
                await expect(page.get_by_role("alertdialog")).to_be_visible()
                await page.keyboard.press("Escape")
                record(
                    profile, surface, "populated keyboard delete cancellation", not state["posts"]
                )
                await shot("gallery-loaded")
                state.update(mode="delete-error")
                await page.locator(".gallery-del").click()
                await page.locator("[data-dialog-confirm]").click()
                await expect(page.locator(".gallery-del")).to_be_enabled()
                record(
                    profile,
                    surface,
                    "rejected delete retains image and retry button",
                    not state["gallery_deleted"],
                )
                state.update(mode="normal")
                await page.locator(".gallery-del").click()
                await page.locator("[data-dialog-confirm]").click()
                await expect(page.locator("#gallery-grid")).to_contain_text("no images yet")
                record(
                    profile, surface, "explicit retry confirmed deletion", state["gallery_deleted"]
                )
                state.update(mode="error")
                await nav("brain")
                await nav("gallery")
                await expect(page.locator("#gallery-retry")).to_be_visible()
                state.update(mode="normal", gallery_deleted=False)
                await page.locator("#gallery-retry").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#gallery-grid")).to_contain_text(
                    "synthetic gallery image"
                )
                record(profile, surface, "failed list keyboard retry recovers", True)
                await page.locator("#gallery-prompt-input").fill("submitted prompt")
                await page.evaluate(HOLD, "/api/gallery/upload")
                await page.locator("#gallery-file-input").set_input_files(
                    {
                        "name": "fixture.png",
                        "mimeType": "image/png",
                        "buffer": (ROOT / "static/icons/icon-192.png").read_bytes(),
                    }
                )
                await page.wait_for_function("window.__held")
                await page.locator("#gallery-prompt-input").fill("newer draft")
                await page.evaluate("window.__release()")
                await page.wait_for_timeout(100)
                value = await page.locator("#gallery-prompt-input").input_value()
                record(
                    profile,
                    surface,
                    "late upload preserves newer prompt draft",
                    value == "newer draft",
                    repr(value),
                )
                await shot("gallery-upload-draft")
            elif surface == "scheduled":
                await expect(page.locator("#aide-schedule-list")).to_contain_text(
                    "synthetic schedule"
                )
                await page.locator("[data-schedule-action=toggle]").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("[data-schedule-action=run]")).to_be_disabled()
                record(profile, surface, "populated keyboard pause disables run", True)
                await page.locator("[data-scheduled-tab=schedules]").focus()
                await page.keyboard.press("End")
                await expect(page.locator("#aide-run-list")).to_be_visible()
                await page.locator("[data-run-action=cancel]").click()
                await expect(page.locator("#aide-run-list")).to_contain_text("cancelled")
                await page.locator("[data-run-action=retry]").click()
                await expect(page.locator("#aide-run-list")).to_contain_text("running")
                record(profile, surface, "keyboard tabs cancel and explicit retry receipts", True)
                await shot("scheduled-runs")
                await page.locator("[data-scheduled-tab=schedules]").click()
                await page.locator("#aide-scheduled-new").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#aide-schedule-name")).to_be_focused()
                await page.locator("#aide-schedule-name").fill("submitted A")
                await page.locator("#aide-schedule-prompt").fill("synthetic only")
                await page.locator("#aide-schedule-value").fill("09:00")
                await page.evaluate(HOLD, "/api/jarvis/aide-schedules")
                await page.locator("#aide-schedule-submit").click()
                await page.wait_for_function("window.__held")
                await expect(page.locator("#aide-schedule-submit")).to_be_disabled()
                await page.locator("#aide-schedule-cancel").click()
                await page.locator("#aide-scheduled-new").click()
                await page.locator("#aide-schedule-name").fill("newer B")
                await page.locator("#aide-schedule-prompt").fill("replacement prompt")
                await page.locator("#aide-schedule-value").fill("10:00")
                await expect(page.locator("#aide-schedule-submit")).to_be_enabled()
                await page.evaluate("window.__releaseA = window.__release")
                state.update(mode="save-error")
                await page.evaluate(HOLD, "/api/jarvis/aide-schedules")
                await page.locator("#aide-schedule-submit").focus()
                await page.keyboard.press("Enter")
                await page.wait_for_function("window.__held")
                await page.evaluate("window.__releaseA()")
                await page.wait_for_timeout(100)
                visible = await page.locator("#aide-schedule-form").is_visible()
                value = await page.locator("#aide-schedule-name").input_value()
                record(
                    profile,
                    surface,
                    "late save cannot close replacement schedule draft",
                    visible and value == "newer B",
                    f"visible={visible}; name={value!r}",
                )
                await expect(page.locator("#aide-schedule-submit")).to_be_disabled()
                await expect(page.locator("#aide-schedule-form-status")).to_contain_text("saving")
                record(
                    profile,
                    surface,
                    "old save completion preserves newer pending save status",
                    True,
                )
                await shot("scheduled-stale-save")
                await page.evaluate("window.__release()")
                await expect(page.locator("#aide-schedule-form-status")).to_contain_text(
                    "fixture save refused"
                )
                await expect(page.locator("#aide-schedule-submit")).to_be_enabled()
                await expect(page.locator("#aide-schedule-name")).to_have_value("newer B")
                record(profile, surface, "failed replacement save preserves draft for retry", True)
                state.update(mode="normal")
                await page.locator("#aide-schedule-submit").focus()
                await page.keyboard.press("Enter")
                await expect(page.locator("#aide-schedule-form")).to_be_hidden()
                record(
                    profile,
                    surface,
                    "replacement draft can be saved by keyboard",
                    len([p for p in state["posts"] if p == "/api/jarvis/aide-schedules"]) == 3,
                )
        except Exception as e:
            record(profile, surface, "harness execution", False, type(e).__name__ + ": " + str(e))
            await shot(surface + "-harness-error")
        unexpected = [
            event
            for event in events[start:]
            if "pageerror" in event
            or "external" in event
            or ("console" in event and "503 (Service Unavailable)" not in event["console"])
        ]
        record(
            profile,
            surface,
            "no unexpected console errors or external requests",
            not unexpected,
            json.dumps(unexpected),
        )
        (OUT / f"{profile}-{surface}-events.json").write_text(
            json.dumps(events[start:], indent=2) + "\n"
        )
    await ctx.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for width in (1440, 390):
            await run(browser, width)
        await browser.close()
    receipt = {
        "cases": ROWS,
        "passed": sum(x["status"] == "passed" for x in ROWS),
        "failed": sum(x["status"] == "failed" for x in ROWS),
        "mode": "owned guarded server; browser fixtures for utility/provider APIs; production UI; external requests blocked",
        "provider_execution": False,
    }
    (OUT / "utility-cases.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "cases"}, indent=2))
    assert not receipt["failed"], "utility recovery checks failed"


if __name__ == "__main__":
    asyncio.run(main())
