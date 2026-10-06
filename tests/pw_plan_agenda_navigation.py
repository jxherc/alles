"""Owned Plan agenda -> exact current editor -> saved record -> agenda continuity.

Run only after the parent releases settled-source browser verification, against
the existing guarded test server. No server is launched here. Successful paths
use real APIs/editors; named GET failures and held real GET replies are the only
network fault injections. Eight profiles each run both motion preferences.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import struct
import sys
import tempfile
import traceback
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_gate_safety import require_server_ownership
from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.appearance import from_legacy  # noqa: E402

PROFILES = [(width, theme, False) for width in (1440, 820, 390) for theme in ("light", "dark")]
PROFILES += [(1440, theme, True) for theme in ("light", "dark")]
MOTIONS = ("no-preference", "reduce")


class GetFault:
    def __init__(self, path, mode):
        self.path, self.mode = path, mode
        self.entered, self.release, self.done = (asyncio.Event() for _ in range(3))
        self.hits = 0
        self.status = None
        self.ids = []


class NetworkBoundary:
    def __init__(self, base):
        self.origin = urlsplit(base)
        self.fault = None
        self.denied, self.sockets, self.workers = [], [], []
        self.injected, self.errors = [], []

    async def route(self, route):
        request = route.request
        target = urlsplit(request.url)
        if (target.scheme, target.netloc) != (self.origin.scheme, self.origin.netloc):
            self.denied.append(request.url)
            await route.abort()
            return
        if target.path == "/sw.js" or request.resource_type == "serviceworker":
            self.workers.append(request.url)
            await route.abort()
            return
        fault = self.fault
        if not fault or request.method != "GET" or target.path != fault.path:
            await route.continue_()
            return
        fault.hits += 1
        try:
            if fault.mode == "reject":
                self.injected.append((request.url, 503))
                fault.entered.set()
                await route.fulfill(status=503, json={"detail": "owned agenda load interruption"})
            else:
                # Capture the real backend reply before leaving Plan. Never invent success data.
                response = await route.fetch(max_redirects=0)
                fault.status = response.status
                data = await response.json()
                fault.ids = [item["id"] for item in data] if isinstance(data, list) else []
                fault.entered.set()
                await fault.release.wait()
                await route.fulfill(response=response)
        except Exception as error:
            self.errors.append(repr(error))
            fault.entered.set()
            await route.abort()
        finally:
            fault.done.set()

    async def close_socket(self, socket):
        self.sockets.append(socket.url)
        await socket.close()


async def owned_context(pw, browser, data, width, theme, zoom, motion, label):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        device_scale_factor=1,
        color_scheme=theme,
        has_touch=width == 390,
        timezone_id="UTC",
        locale="en-US",
        reduced_motion=motion,
        service_workers="block",
    )
    if not zoom:
        return await browser.new_context(**options)
    profile = Path(tempfile.mkdtemp(prefix=f"agenda-{label}-", dir=data))
    extension = profile / "extension"
    extension.mkdir()
    (extension / "manifest.json").write_text(
        json.dumps(
            dict(
                manifest_version=3,
                name="owned agenda native zoom",
                version="1.0",
                permissions=["tabs"],
                background={"service_worker": "zoom.js"},
            )
        )
    )
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return await pw.chromium.launch_persistent_context(
        profile / "browser",
        channel="chromium",
        headless=True,
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
            "--disable-background-networking",
            "--disable-component-update",
            "--no-first-run",
        ],
        **options,
    )


class AgendaCase:
    def __init__(self, context, base, output, label, width, theme, zoom, motion, run_id):
        self.context, self.base, self.output = context, base, output
        self.label, self.width, self.theme, self.zoom, self.motion = (
            label,
            width,
            theme,
            zoom,
            motion,
        )
        self.marker = f"agenda-{run_id}-{label}"
        self.title = f"réunion 日本語 🌱 — review the saved planning record {self.marker}"
        self.today = datetime.now(UTC).date()
        self.later = (self.today + timedelta(days=2)).isoformat()
        self.owned = {}
        self.deleted = set()
        self.boundary = NetworkBoundary(base)
        self.page_errors, self.console_errors, self.http_errors, self.failed_requests = (
            [],
            [],
            [],
            [],
        )
        self.result = {"profile": label, "status": "failed", "steps": []}

    async def api(self, method, path, body=None):
        assert path.startswith("/api/") and not urlsplit(path).netloc, path
        response = await self.context.request.fetch(
            self.base + path, method=method, data=body, max_redirects=0
        )
        assert response.url == self.base + path and response.ok, (
            path,
            response.status,
            await response.text(),
        )
        return await response.json()

    async def create(self, key, path, body):
        record = await self.api("POST", path, body)
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", record["id"]), record
        self.owned[key] = (path, record)
        self.result.setdefault("fixture_ids", {})[key] = record["id"]
        return record

    def record(self, key):
        return self.owned[key][1]

    async def saved(self, key):
        path, original = self.owned[key]
        rows = await self.api("GET", path)
        matches = [row for row in rows if row["id"] == original["id"]]
        assert len(matches) == 1, (key, matches)
        return matches[0]

    async def delete(self, key):
        record = await self.saved(key)
        assert self.marker in (record.get("title") or record.get("text") or ""), record
        await self.api("DELETE", self.owned[key][0] + "/" + record["id"])
        self.deleted.add(key)

    async def seed(self):
        await self.api("POST", "/api/setup/dismiss")
        await self.api("PUT", "/api/appearance", from_legacy(self.theme, None))
        await self.api("PATCH", "/api/settings", {"language": "en", "timezone": "UTC"})
        for key in ("task-a", "task-b", "gone-task"):
            await self.create(
                key, "/api/tasks", {"title": self.title, "notes": f"{self.marker} {key}"}
            )
        await self.create(
            "dated",
            "/api/tasks",
            {"title": self.marker + " dated", "due_date": self.today.isoformat()},
        )
        await self.create(
            "outside",
            "/api/tasks",
            {
                "title": self.marker + " outside",
                "due_date": (self.today + timedelta(days=12)).isoformat(),
            },
        )
        for key, hour in (("event-a", "09"), ("event-b", "10"), ("gone-event", "11")):
            await self.create(
                key,
                "/api/calendar",
                {
                    "title": self.title,
                    "description": f"{self.marker} {key}",
                    "start_dt": f"{self.later}T{hour}:00",
                    "end_dt": f"{self.later}T{hour}:30",
                    "reminders": [],
                },
            )
        master = (self.today - timedelta(days=7)).isoformat()
        await self.create(
            "series",
            "/api/calendar",
            {
                "title": self.title,
                "description": self.marker + " series",
                "start_dt": f"{master}T14:00",
                "end_dt": f"{master}T14:30",
                "recurrence": "daily",
                "recur_count": 20,
                "reminders": [],
            },
        )
        await self.create(
            "reminder",
            "/api/reminders",
            {"text": self.marker + " reminder", "trigger_at": f"{self.later}T23:59:00"},
        )

    async def attach(self):
        await self.context.route("**/*", self.boundary.route)
        await self.context.route_web_socket("**/*", self.boundary.close_socket)
        await self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(10000)
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.page.on(
            "console",
            lambda message: (
                self.console_errors.append({"text": message.text, "location": message.location})
                if message.type == "error"
                else None
            ),
        )
        self.page.on(
            "response",
            lambda response: (
                self.http_errors.append((response.url, response.status))
                if response.status >= 400
                else None
            ),
        )
        self.page.on(
            "requestfailed",
            lambda request: self.failed_requests.append(
                {"url": request.url, "failure": request.failure}
            ),
        )

    async def geometry(self):
        geometry = await self.page.evaluate("""() => ({
          width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
          scale: visualViewport.scale, htmlZoom: getComputedStyle(document.documentElement).zoom,
          bodyZoom: getComputedStyle(document.body).zoom,
          reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
          overflow: document.documentElement.scrollWidth > innerWidth + 1
        })""")
        assert (geometry["width"], geometry["height"], geometry["dpr"]) == (
            (720, 450, 2) if self.zoom else (self.width, 844 if self.width == 390 else 900, 1)
        ), geometry
        assert geometry["scale"] == 1 and geometry["htmlZoom"] == geometry["bodyZoom"] == "1", (
            geometry
        )
        assert geometry["reduced"] == (self.motion == "reduce") and not geometry["overflow"], (
            geometry
        )
        return geometry

    async def capture(self, name):
        geometry = await self.geometry()
        session = await self.context.new_cdp_session(self.page)
        try:
            image = await session.send(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )
        finally:
            await session.detach()
        png = base64.b64decode(image["data"])
        pixels = struct.unpack(">II", png[16:24])
        assert pixels == (self.width, 844 if self.width == 390 else 900), pixels
        (self.output / f"{self.label}-{name}.png").write_bytes(png)
        self.result.setdefault("captures", []).append({"name": name, "pixels": pixels, **geometry})

    async def zoom_page(self):
        if not self.zoom:
            return
        workers = [
            worker
            for worker in self.context.service_workers
            if worker.url.startswith("chrome-extension://")
        ]
        worker = (
            workers[0]
            if workers
            else await self.context.wait_for_event(
                "serviceworker",
                predicate=lambda worker: worker.url.startswith("chrome-extension://"),
            )
        )
        factor = await worker.evaluate(
            """async origin => {
          const tabs = (await chrome.tabs.query({})).filter(tab => {
            try { return new URL(tab.url).origin === origin; } catch { return false; }
          });
          if (tabs.length !== 1) throw new Error('expected one owned application tab');
          await chrome.tabs.setZoom(tabs[0].id, 2);
          return chrome.tabs.getZoom(tabs[0].id);
        }""",
            self.base,
        )
        assert factor == 2
        await self.page.wait_for_function(
            "innerWidth === 720 && innerHeight === 450 && devicePixelRatio === 2"
        )

    def row(self, key, occurrence=None):
        record_id = self.record(key)["id"]
        identity = (
            f"task:{record_id}"
            if self.owned[key][0] == "/api/tasks"
            else f"event:{record_id}:{occurrence or self.later}"
        )
        return self.page.locator(f'#plan-view button[data-plan-agenda-record="{identity}"]')

    def choice(self, window):
        return self.page.locator(
            f'#plan-view .specialist-choice-group button[data-value="{window}"]'
        )

    async def agenda(self, section="overview", window="unscheduled"):
        await self.page.locator(f'#plan-tabs [data-group-section="{section}"]').press("Enter")
        await expect(self.page.locator("#plan-view")).to_have_attribute("data-section", section)
        await expect(self.choice(window)).to_be_visible()
        if await self.choice(window).get_attribute("aria-pressed") != "true":
            await self.choice(window).press("Enter")
        await expect(self.choice(window)).to_have_attribute("aria-pressed", "true")

    async def keyboard_row(self, key, window, occurrence=None):
        row = self.row(key, occurrence)
        await self.choice(window).focus()
        for _ in range(100):
            await self.page.keyboard.press("Tab")
            if await row.evaluate("el => el === document.activeElement"):
                break
        else:
            raise AssertionError(f"agenda record {key} is not reachable by Tab")
        await self.focus_proof(row)
        return row

    async def focus_proof(self, control):
        await expect(control).to_be_focused()
        proof = await control.evaluate("""el => {
          const r = el.getBoundingClientRect(), s = getComputedStyle(el);
          const x = Math.max(1, r.left) + Math.min(r.width / 2, innerWidth - Math.max(1, r.left) - 1);
          const y = Math.max(1, r.top) + Math.min(r.height / 2, innerHeight - Math.max(1, r.top) - 1);
          return {visible: el.matches(':focus-visible'), width: r.width, height: r.height,
            outline: s.outlineStyle, outlineWidth: parseFloat(s.outlineWidth), color: s.outlineColor,
            inside: r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1,
            uncovered: el.contains(document.elementFromPoint(x, y))};
        }""")
        assert (
            proof["visible"]
            and proof["outline"] not in ("none", "hidden")
            and proof["outlineWidth"] >= 2
        ), proof
        assert proof["color"] not in ("transparent", "rgba(0, 0, 0, 0)"), proof
        assert (
            min(proof["width"], proof["height"]) >= 44 and proof["inside"] and proof["uncovered"]
        ), proof
        self.result.setdefault("focus", []).append(proof)

    async def exact_editor(self, key, occurrence=None):
        record = self.record(key)
        task = self.owned[key][0] == "/api/tasks"
        await expect(self.page.locator("#te-title" if task else "#cal-title")).to_have_value(
            record["title"]
        )
        await expect(self.page.locator("#te-title" if task else "#cal-title")).to_be_focused()
        target = parse_qs(urlsplit(self.page.url).query)
        assert target["record"] == [record["id"]] and target["record_view"] == [
            "tasks" if task else "calendar"
        ], target
        if task:
            await expect(self.page.locator(".task-editor-ov")).to_have_attribute(
                "data-task-id", record["id"]
            )
            await expect(self.page.locator("#te-notes")).to_have_value(record["notes"])
        else:
            assert target["occurrence"] == [occurrence or self.later], target
            await expect(self.page.locator("#cal-desc")).to_have_value(record["description"])
            expected_start = f"{occurrence}T14:00" if key == "series" else record["start_dt"]
            assert (
                await self.page.locator("#cal-start").evaluate("el => el.value") == expected_start
            )

    async def back(self, key, section, window, occurrence=None, browser=True):
        if browser:
            await self.page.go_back(wait_until="networkidle")
        else:
            await self.page.locator(f'#plan-tabs [data-group-section="{section}"]').press("Enter")
        await expect(self.page.locator("#plan-view")).to_have_attribute("data-section", section)
        await expect(self.choice(window)).to_have_attribute("aria-pressed", "true")
        await expect(self.row(key, occurrence)).to_be_focused()
        await expect(self.page.locator(".task-editor-ov")).to_have_count(0)
        await expect(self.page.locator("#calendar-view .cal-editor:visible")).to_have_count(0)

    async def task_workflow(self):
        await self.agenda(window="unscheduled")
        for key in ("task-a", "task-b"):
            await expect(self.row(key).locator(".specialist-record-title")).to_have_text(self.title)
        other = await self.saved("task-a")
        control = self.row("task-b")
        await control.tap() if self.width == 390 else await control.click()
        await self.exact_editor("task-b")
        renamed = self.title + " edited"
        notes = self.marker + " saved task details 中文"
        await self.page.locator("#te-title").fill(renamed)
        await self.page.locator("#te-notes").fill(notes)
        endpoint = self.base + "/api/tasks/" + self.record("task-b")["id"]
        async with self.page.expect_response(
            lambda response: response.url == endpoint and response.request.method == "PATCH"
        ) as response:
            await self.page.locator("#te-save").press("Enter")
        assert (await response.value).ok
        await expect(self.page.locator("#te-title")).to_have_count(0)
        saved = await self.saved("task-b")
        assert (saved["title"], saved["notes"]) == (renamed, notes), saved
        assert await self.saved("task-a") == other
        self.owned["task-b"] = ("/api/tasks", saved)
        await self.back("task-b", "overview", "unscheduled")
        await self.focus_proof(self.row("task-b"))
        await self.capture("task-saved-return")
        # A fresh editor load reads the actual saved values again.
        await self.row("task-b").press("Space")
        await self.exact_editor("task-b")
        await self.page.keyboard.press("Escape")
        await self.back("task-b", "overview", "unscheduled", browser=False)
        control = await self.keyboard_row("task-a", "unscheduled")
        await self.capture("keyboard-row")
        await control.press("Enter")
        await self.exact_editor("task-a")
        await self.page.keyboard.press("Escape")
        await self.back("task-a", "overview", "unscheduled", browser=False)
        await self.focus_proof(self.row("task-a"))
        self.result["steps"].append(
            {
                "scenario": "task-exact-save-back-keyboard",
                "id": saved["id"],
                "untouched_id": other["id"],
                "readback": {field: saved[field] for field in ("id", "title", "notes", "due_date")},
            }
        )

    async def event_workflow(self):
        await self.agenda("week", "seven")
        for key in ("event-a", "event-b", "series"):
            await expect(self.row(key).locator(".specialist-record-title")).to_have_text(self.title)
        other = await self.saved("event-a")
        control = self.row("event-b")
        await control.tap() if self.width == 390 else await control.click()
        await self.exact_editor("event-b")
        await self.save_event("event-b", self.marker + " saved event details 中文")
        assert await self.saved("event-a") == other
        await self.back("event-b", "week", "seven")
        await self.capture("event-saved-return")
        control = await self.keyboard_row("series", "seven")
        await control.press("Space")
        await self.exact_editor("series", self.later)
        original = self.record("series")
        await self.capture("later-occurrence-editor")
        await self.save_event(
            "series", self.marker + " saved recurring details 中文", recurring=True
        )
        saved = await self.saved("series")
        assert saved["start_dt"] == original["start_dt"] and saved["end_dt"] == original["end_dt"]
        assert saved["recurrence"] == "daily" and saved["recur_count"] == original["recur_count"]
        assert parse_qs(urlsplit(self.page.url).query)["occurrence"] == [self.later]
        await self.back("series", "week", "seven", self.later)
        await self.focus_proof(self.row("series"))
        await self.capture("recurrence-saved-return")
        await self.row("series").press("Enter")
        await self.exact_editor("series", self.later)
        await self.page.locator("#cal-back").press("Enter")
        await self.back("series", "week", "seven", self.later, browser=False)
        self.result["steps"].append(
            {
                "scenario": "events-equal-title-and-later-occurrence-save",
                "event_id": self.record("event-b")["id"],
                "series_id": saved["id"],
                "occurrence": self.later,
                "readback": {
                    field: saved[field]
                    for field in (
                        "id",
                        "title",
                        "description",
                        "start_dt",
                        "end_dt",
                        "recurrence",
                        "recur_count",
                    )
                },
            }
        )

    async def save_event(self, key, description, recurring=False):
        await self.page.locator("#cal-desc").fill(description)
        endpoint = self.base + "/api/calendar/" + self.record(key)["id"]
        async with self.page.expect_response(
            lambda response: (
                response.url.split("?")[0] == endpoint and response.request.method == "PATCH"
            )
        ) as pending:
            await self.page.locator("#cal-save").press("Enter")
            if recurring:
                await self.page.get_by_role("button", name="All events", exact=True).press("Enter")
        response = await pending.value
        assert response.ok, await response.text()
        response_record = await response.json()
        assert response_record["id"] == self.record(key)["id"]
        if recurring:
            query = parse_qs(urlsplit(response.url).query)
            assert query["occ"] == [self.later] and query["scope"] == ["all"], query
        await expect(self.page.locator("#cal-title")).to_have_count(0)
        saved = await self.saved(key)
        assert saved["description"] == description
        self.owned[key] = ("/api/calendar", saved)

    async def unavailable(self, key, section, window):
        await self.agenda(section, window)
        await expect(self.row(key)).to_be_visible()
        await self.delete(key)
        await expect(self.page.locator(".toast.error")).to_have_count(0)
        await self.row(key).press("Enter")
        await expect(self.page.locator("#plan-view")).to_have_attribute("aria-busy", "false")
        await expect(self.page.locator(".toast.error").last).to_contain_text(
            "could not open this item"
        )
        target = parse_qs(urlsplit(self.page.url).query)
        assert target["record"] == [self.record(key)["id"]], target
        await expect(self.page.locator(".task-editor-ov")).to_have_count(0)
        await expect(self.page.locator("#calendar-view .cal-editor:visible")).to_have_count(0)
        await self.page.go_back(wait_until="networkidle")
        await expect(self.row(key)).to_have_count(0)
        await expect(self.choice(window)).to_be_focused()
        await expect(self.choice(window)).to_have_attribute("aria-pressed", "true")
        await expect(self.page.locator(".plan-agenda-status")).to_contain_text(
            "no longer in this agenda window"
        )
        await self.capture(key + "-unavailable")
        self.result["steps"].append(
            {"scenario": key + "-unavailable-no-namesake-fallback", "id": self.record(key)["id"]}
        )

    async def failure_retry(self, key, path, section, window):
        await self.agenda(section, window)
        fault = GetFault(path, "reject")
        self.boundary.fault = fault
        try:
            await self.row(key).press("Enter")
            await asyncio.wait_for(fault.done.wait(), 10)
            if key.startswith("task"):
                retry = self.page.locator("#plan-view > .specialist-state .specialist-state-retry")
            else:
                retry = self.page.locator("#cal-load-error").get_by_role(
                    "button", name="retry", exact=True
                )
            await expect(retry).to_be_visible()
            await expect(self.page.locator(".task-editor-ov")).to_have_count(0)
            await expect(self.page.locator("#calendar-view .cal-editor:visible")).to_have_count(0)
            assert fault.hits == 1
            await self.capture(key + "-load-error")
        finally:
            self.boundary.fault = None
        await retry.press("Enter")
        await self.exact_editor(key)
        if key.startswith("task"):
            await self.page.keyboard.press("Escape")
        else:
            await self.page.locator("#cal-back").press("Enter")
        await self.back(key, section, window, browser=False)
        self.result["steps"].append(
            {"scenario": key + "-destination-error-real-retry", "path": path}
        )

    async def switch_app(self, name):
        await self.page.locator("#app-drawer-btn").press("Enter")
        await self.page.locator(f'#app-drawer [data-view="{name}"]').press("Enter")
        await expect(self.page.locator("#app-drawer")).to_be_hidden()

    async def stale_reply(self, key, path, section, window):
        await self.agenda(section, window)
        await expect(self.page.locator(".toast.error")).to_have_count(0)
        fault = GetFault(path, "hold")
        self.boundary.fault = fault
        try:
            await self.row(key).press("Enter")
            await asyncio.wait_for(fault.entered.wait(), 10)
            assert fault.status == 200 and self.record(key)["id"] in fault.ids, (
                fault.status,
                fault.ids,
            )
            await self.switch_app("library")
            library = self.page.locator("#library-view")
            await expect(library).to_be_visible()
            focused = library.locator('.specialist-choice-group [data-value="all"]')
            await focused.press("Space")
            await expect(focused).to_be_focused()
            destination_url = self.page.url
            fault.release.set()
            await asyncio.wait_for(fault.done.wait(), 10)
            await self.page.wait_for_load_state("networkidle")
            await self.page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            assert self.page.url == destination_url and fault.hits == 1
            await expect(library).to_be_visible()
            await expect(focused).to_be_focused()
            await expect(self.page.locator("#plan-view")).to_be_hidden()
            await expect(self.page.locator(".task-editor-ov")).to_have_count(0)
            await expect(self.page.locator("#calendar-view .cal-editor:visible")).to_have_count(0)
            assert await self.page.locator(".toast.error").count() == 0
            await self.capture(key + "-stale-reply-no-takeover")
            self.result["steps"].append(
                {
                    "scenario": key + "-held-real-reply-after-leaving",
                    "path": path,
                    "status": fault.status,
                    "target_in_response": True,
                    "destination": destination_url,
                }
            )
        finally:
            fault.release.set()
            self.boundary.fault = None
        await self.switch_app("plan")

    async def check_windows(self):
        await self.agenda("overview", "today")
        await expect(self.row("dated")).to_be_visible()
        await expect(self.row("task-a")).to_have_count(0)
        await expect(self.row("outside")).to_have_count(0)
        for window in ("today", "seven", "unscheduled"):
            await self.choice(window).press("Enter")
            count = await self.page.locator(
                "#plan-view .specialist-record-list > .specialist-record-row"
            ).count()
            text = await self.choice(window).inner_text()
            assert int(text.rsplit("·", 1)[1].strip()) == count, (text, count)
            await expect(self.row("dated")).to_have_count(0 if window == "unscheduled" else 1)
            for key in ("task-a", "task-b", "gone-task"):
                await expect(self.row(key)).to_have_count(1 if window == "unscheduled" else 0)
            for key in ("event-a", "event-b", "gone-event"):
                await expect(self.row(key)).to_have_count(1 if window == "seven" else 0)
            await expect(self.row("outside")).to_have_count(0)
        await self.choice("seven").press("Enter")
        reminder = self.page.locator("#plan-view .specialist-record-row").filter(
            has_text=self.marker + " reminder"
        )
        await expect(reminder).to_have_count(1)
        assert await reminder.evaluate("el => el.tagName === 'DIV' && el.tabIndex === -1")
        self.result["steps"].append({"scenario": "time-windows-counts-and-read-only-reminder"})

    async def check_network(self):
        assert not self.page_errors and not self.boundary.errors, (
            self.page_errors,
            self.boundary.errors,
        )
        assert not self.boundary.denied, self.boundary.denied
        assert Counter(self.http_errors) == Counter(self.boundary.injected), (
            self.http_errors,
            self.boundary.injected,
        )
        injected_urls = {url for url, _ in self.boundary.injected}
        assert len(self.console_errors) <= len(self.boundary.injected), self.console_errors
        for message in self.console_errors:
            assert (
                message["text"]
                == "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            ), message
            assert message["location"].get("url", "") in injected_urls | {""}, message
        assert all(request["url"] in self.boundary.workers for request in self.failed_requests), (
            self.failed_requests
        )
        registrations = await self.page.evaluate(
            "async () => 'serviceWorker' in navigator ? (await navigator.serviceWorker.getRegistrations()).map(r => r.scope) : []"
        )
        assert registrations == [], registrations
        assert all(
            worker.url.startswith("chrome-extension://") for worker in self.context.service_workers
        )

    async def run(self):
        await self.seed()
        await self.page.goto(self.base + "/?view=plan", wait_until="networkidle")
        await self.zoom_page()
        await self.geometry()
        if self.theme == "light":
            await expect(self.page.locator("html")).to_have_attribute("data-theme", "light")
        else:
            await expect(self.page.locator("html")).not_to_have_attribute("data-theme", "light")
        await self.check_windows()
        await self.task_workflow()
        await self.event_workflow()
        await self.unavailable("gone-task", "overview", "unscheduled")
        await self.unavailable("gone-event", "week", "seven")
        await self.failure_retry("task-a", "/api/tasks/tree", "overview", "unscheduled")
        await self.failure_retry("event-a", "/api/calendar", "week", "seven")
        await self.stale_reply("task-a", "/api/tasks/tree", "overview", "unscheduled")
        await self.stale_reply("event-a", "/api/calendar", "week", "seven")
        await self.check_network()
        self.result["status"] = "passed"

    async def finish(self):
        if self.boundary.fault:
            self.boundary.fault.release.set()
        try:
            await self.capture("final")
        except Exception as error:
            self.result["capture_error"] = repr(error)
            self.result["status"] = "failed"
        cleanup_errors = []
        for key in self.owned:
            if key not in self.deleted:
                try:
                    await self.delete(key)
                except Exception as error:
                    cleanup_errors.append({"key": key, "error": repr(error)})
        if cleanup_errors:
            self.result.update(status="failed", cleanup_errors=cleanup_errors)
        self.result.update(
            page_errors=self.page_errors,
            console_errors=self.console_errors,
            http_errors=self.http_errors,
            failed_requests=self.failed_requests,
            denied=self.boundary.denied,
            blocked_websockets=self.boundary.sockets,
            blocked_app_workers=self.boundary.workers,
            route_errors=self.boundary.errors,
        )
        await self.context.tracing.stop(path=self.output / f"{self.label}-trace.zip")


async def run():
    base = f"http://127.0.0.1:{int(os.environ['PORT'])}"
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert os.environ["ALLES_TEST_DATA"] == "1" and os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert data != Path(__file__).resolve().parents[1] / "data"
    assert run_id and (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--disable-background-networking", "--disable-component-update", "--no-first-run"]
        )
        try:
            for width, theme, zoom in PROFILES:
                for motion in MOTIONS:
                    label = f"{width}-{theme}" + ("-native200" if zoom else "") + f"-{motion}"
                    context = await owned_context(
                        pw, browser, data, width, theme, zoom, motion, label
                    )
                    case = AgendaCase(
                        context, base, output, label, width, theme, zoom, motion, run_id
                    )
                    results.append(case.result)
                    try:
                        await case.attach()
                        await case.run()
                    except Exception as error:
                        case.result.update(
                            status="failed", error=repr(error), traceback=traceback.format_exc()
                        )
                    finally:
                        try:
                            await case.finish()
                        finally:
                            await context.close()
                            (output / "scenarios.json").write_text(
                                json.dumps(results, indent=2, ensure_ascii=False)
                            )
        finally:
            await browser.close()
    return int(len(results) != 16 or any(result["status"] != "passed" for result in results))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
