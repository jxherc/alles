"""Central Aide browser gate with owned data and a simulated text response.

Run through scripts/run_browser_gates.py. No real model, microphone, call,
DSH pairing, or background worker is invoked by this gate.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

SIMULATION = "real local UI and database; synthetic records; intercepted text SSE"
BASE = "http://127.0.0.1:" + os.environ["PORT"]
OUT = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
DATA = Path(os.environ["ALLES_DATA"]).resolve()
RUN_ID = os.environ["ALLES_TEST_RUN_ID"]
require_server_ownership(BASE, RUN_ID)
assert Path(tempfile.gettempdir()).resolve() in DATA.parents
assert (DATA / ".alles-test-owner").read_text() == RUN_ID
assert Path(os.environ["ALLES_DB"]).resolve() == DATA / "aide.db"

# Import the database only after proving that both HTTP and SQLite belong to
# the same throwaway runner. No owner database can become a fallback target.
from core.database import (  # noqa: E402
    JarvisRun,
    JarvisRunEvent,
    JarvisWorkflow,
    Memory,
    Message,
    Project,
    SessionLocal,
)


def seed(api):
    assert api.post(BASE + "/api/setup/dismiss").ok
    primary_response = api.get(BASE + "/api/aide/conversation")
    assert primary_response.ok
    primary = primary_response.json()
    old_response = api.post(BASE + "/api/sessions", data={"name": "Weekend in Kyoto"})
    assert old_response.ok
    old = old_response.json()
    endpoint = api.post(
        BASE + "/api/models/endpoint",
        data={
            "name": "isolated text fixture",
            "base_url": BASE + "/synthetic-model",
            "provider_adapter": "manual",
        },
    ).json()
    assert api.patch(
        BASE + "/api/models/endpoint/" + endpoint["id"],
        data={"models": ["central-fixture"]},
    ).ok
    assert api.patch(
        BASE + "/api/settings",
        data={
            "default_endpoint_id": endpoint["id"],
            "default_model": "central-fixture",
            "model_roles": {},
            "memory_policy": "ask",
            "memory_auto_inject": False,
            "intent_suggestions": False,
            "auto_compact": False,
        },
    ).ok
    now = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        db.add_all(
            [
                Message(
                    session_id=primary["id"],
                    role="user",
                    content="Help me make room for the work that matters today.",
                    timestamp=now - timedelta(minutes=3),
                ),
                Message(
                    session_id=primary["id"],
                    role="assistant",
                    content=(
                        "Start with the launch notes, then leave a clear hour for the prototype. "
                        "Keep the rest of the afternoon open.\n\n"
                        "I can help you turn either one into a concrete next step."
                    ),
                    timestamp=now - timedelta(minutes=2),
                ),
                Message(
                    session_id=old["id"],
                    role="user",
                    content="Keep the quiet riverside walk in our Kyoto plan.",
                    timestamp=now - timedelta(days=2),
                ),
                Message(
                    session_id=old["id"],
                    role="assistant",
                    content="The riverside walk is in the older plan. Nothing here was removed.",
                    timestamp=now - timedelta(days=2) + timedelta(seconds=1),
                ),
                Memory(
                    id="central-owned-memory",
                    text="I prefer short answers and one useful next step.",
                    category="preference",
                    source="manual",
                    status="active",
                    trust="owner",
                    provenance=json.dumps({"kind": "owner_request"}),
                ),
                Project(id="central-owned-project", name="Prototype"),
            ]
        )
        for index, (state, title, summary) in enumerate(
            [
                ("running", "Launch notes", "Reviewing the three open decisions"),
                ("queued", "Prototype checklist", "Check what is ready to build"),
                ("succeeded", "Reading list", "The reading list is ready"),
            ]
        ):
            workflow = JarvisWorkflow(
                id=f"central-owned-workflow-{state}",
                name=title,
                prompt="synthetic browser status only",
                enabled=False,
            )
            db.add(workflow)
            db.flush()
            run = JarvisRun(
                id=f"central-owned-{state}",
                workflow_id=workflow.id,
                session_id=primary["id"],
                state=state,
                result_summary=summary,
                created_at=now - timedelta(minutes=index + 1),
                started_at=now if state != "queued" else None,
                finished_at=now if state == "succeeded" else None,
                lease_owner="synthetic-browser-fixture" if state == "running" else "",
                lease_expires_at=now + timedelta(days=1) if state == "running" else None,
            )
            db.add(run)
            db.flush()
            db.add(
                JarvisRunEvent(
                    run_id=run.id,
                    sequence=1,
                    kind="status",
                    source="fixture",
                    summary=summary,
                )
            )
        db.commit()
    return {"primary": primary["id"], "old": old["id"]}


def context_for(pw, browser, width, theme, zoom=False):
    options = {
        "viewport": {"width": width, "height": 844 if width < 700 else 900},
        "has_touch": width < 700,
        "locale": "en-US",
        "timezone_id": "UTC",
        "service_workers": "block",
        "reduced_motion": "reduce",
    }
    if not zoom:
        return browser.new_context(**options)
    profile = DATA / f"central-zoom-{theme}"
    extension = profile / "extension"
    extension.mkdir(parents=True)
    (extension / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "name": "owned central Aide zoom check",
                "version": "1.0",
                "permissions": ["tabs"],
                "background": {"service_worker": "zoom.js"},
            }
        )
    )
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
        profile / "browser",
        channel="chromium",
        headless=True,
        args=[
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
        ],
        **options,
    )


def geometry(page, selectors):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "page overflow"
    results = {}
    for selector in selectors:
        control = page.locator(selector)
        expect(control).to_be_visible()
        box = control.bounding_box()
        assert box and box["width"] >= 44 and box["height"] >= 44, (selector, box)
        viewport = page.evaluate("({width:innerWidth,height:innerHeight})")
        assert 0 <= box["x"] and box["x"] + box["width"] <= viewport["width"] + 1, box
        assert 0 <= box["y"] and box["y"] + box["height"] <= viewport["height"] + 1, box
        results[selector] = box
    assert page.locator('select:visible, input[type="radio"]:visible').count() == 0
    return results


def capture_empty(browser):
    """Check first entry before the synthetic history or endpoints exist."""
    rows = []
    primary_id = None
    for width, theme in [(1440, "dark"), (390, "light")]:
        context = browser.new_context(
            viewport={"width": width, "height": 844 if width < 700 else 900},
            has_touch=width < 700,
            service_workers="block",
            reduced_motion="reduce",
        )
        errors = []
        outside = []

        def boundary(route):
            if urlsplit(route.request.url).netloc != urlsplit(BASE).netloc:
                outside.append(route.request.url)
                return route.abort()
            return route.continue_()

        context.route("**/*", boundary)
        assert context.request.post(BASE + "/api/setup/dismiss").ok
        assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(BASE + "/?view=chat", wait_until="networkidle")
            page.wait_for_function("window._currentSession?.primary === true")
            current = page.evaluate("window._currentSession.id")
            if primary_id is None:
                primary_id = current
            assert current == primary_id
            expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
            expect(page.locator("#aide-sidebar")).not_to_be_visible()
            expect(page.locator("#composer-ta")).to_be_visible()
            expect(page.locator("#messages .msg-row")).to_have_count(0)
            geometry(page, ["#aide-mode-conversation", "#aide-mode-coding", "#aide-call-open"])
            page.screenshot(path=str(OUT / f"aide-empty-{width}-{theme}.png"))
            assert not errors and not outside, (errors, outside)
            rows.append(
                {
                    "scenario_id": "aide.primary-empty",
                    "profile": f"{width}-{theme}",
                    "status": "passed",
                    "same_primary_session": True,
                    "simulation": "real local UI and empty owned database; no provider",
                }
            )
        finally:
            context.close()
    return rows


def check_primary_recovery(browser, ids):
    """A cold history failure must not create a replacement conversation."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        service_workers="block",
        reduced_motion="reduce",
    )
    failing = True
    events = {"console": [], "page_errors": [], "external": [], "new_sessions": []}

    def boundary(route):
        url = urlsplit(route.request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(route.request.url)
            return route.abort()
        if url.path == "/api/sessions" and route.request.method == "POST":
            events["new_sessions"].append(route.request.post_data)
            return route.abort()
        if failing and url.path == f"/api/sessions/{ids['primary']}/history":
            return route.fulfill(status=503, json={"detail": "synthetic history outage"})
        return route.continue_()

    context.route("**/*", boundary)
    page = context.new_page()
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["console"].append(message.text) if message.type == "error" else None,
    )
    try:
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        panel = page.locator("#aide-context-panel")
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("could not open your conversation")
        assert page.locator("#composer-outer").evaluate("element => element.inert")
        page.screenshot(path=str(OUT / "aide-primary-history-unavailable.png"))
        failing = False
        panel.get_by_role("button", name="retry", exact=True).click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(panel).not_to_be_visible()
        expect(page.locator("#messages")).to_contain_text("Help me make room")
        assert not page.locator("#composer-outer").evaluate("element => element.inert")
        expect(page.locator("#composer-ta")).to_be_focused()
        page.screenshot(path=str(OUT / "aide-primary-history-recovered.png"))
        assert (
            not events["external"] and not events["new_sessions"] and not events["page_errors"]
        ), events
        unexpected = [
            message
            for message in events["console"]
            if "503" not in message
            and "selectSession Error: conversation unavailable" not in message
            and "initSessions Error: primary conversation unavailable" not in message
        ]
        assert not unexpected, unexpected
        return {
            "scenario_id": "aide.primary-history-recovery",
            "profile": "1440-light",
            "status": "passed",
            "no_replacement_session": True,
            "simulation": "real local UI/database; primary history response deliberately unavailable once",
        }
    except Exception:
        events["failure_state"] = page.evaluate("""() => ({
          primaryUnavailable: window._aidePrimaryUnavailable,
          composerInert: document.getElementById('composer-outer').inert,
          contextHidden: document.getElementById('aide-context-overlay').hidden,
          currentSession: window._currentSession?.id || null,
          space: document.body.dataset.space,
          mode: document.body.dataset.aideMode
        })""")
        page.screenshot(path=str(OUT / "failure-primary-history-recovery.png"))
        raise
    finally:
        (OUT / "events-primary-history-recovery.json").write_text(
            json.dumps(events, indent=2) + "\n"
        )
        context.close()


def check_archive_recovery(browser, ids):
    """A failed archive read must retain the previous message and draft owner."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        service_workers="block",
        reduced_motion="reduce",
    )
    failing = True
    events = {"console": [], "page_errors": [], "external": [], "new_sessions": []}

    def boundary(route):
        url = urlsplit(route.request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(route.request.url)
            return route.abort()
        if url.path == "/api/sessions" and route.request.method == "POST":
            events["new_sessions"].append(route.request.post_data)
            return route.abort()
        if failing and url.path == f"/api/sessions/{ids['old']}/history":
            return route.fulfill(status=503, json={"detail": "synthetic archive outage"})
        return route.continue_()

    context.route("**/*", boundary)
    page = context.new_page()
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["console"].append(message.text) if message.type == "error" else None,
    )
    try:
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        draft = "Keep this attached to the primary conversation."
        page.locator("#composer-ta").fill(draft)
        before = page.locator("#messages").inner_text()
        owner_hash = page.evaluate("location.hash")
        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="archive"]').click()
        archive_row = page.locator(f'.session-item[data-id="{ids["old"]}"] .session-open')
        with (
            page.expect_console_message(
                lambda message: "selectSession Error: conversation unavailable" in message.text
            ),
            page.expect_response(
                lambda response: (
                    response.url.endswith(f"/api/sessions/{ids['old']}/history")
                    and response.status == 503
                )
            ),
        ):
            archive_row.click()
        assert page.evaluate("window._currentSession.id") == ids["primary"]
        assert (
            page.evaluate("async () => (await import('/static/js/sessions.js')).getActiveId()")
            == ids["primary"]
        )
        assert page.evaluate("location.hash") == owner_hash
        expect(page.locator("#composer-ta")).to_have_value(draft)
        assert page.locator("#messages").inner_text() == before
        page.screenshot(path=str(OUT / "aide-archive-history-unavailable.png"))
        failing = False
        archive_row.click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["old"])
        expect(page.locator("#messages")).to_contain_text("Nothing here was removed")
        page.locator("#aide-history-return").click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(page.locator("#composer-ta")).to_have_value(draft)
        page.screenshot(path=str(OUT / "aide-archive-history-recovered.png"))
        assert (
            not events["external"] and not events["new_sessions"] and not events["page_errors"]
        ), events
        unexpected = [
            message
            for message in events["console"]
            if "503" not in message
            and "selectSession Error: conversation unavailable" not in message
        ]
        assert not unexpected, unexpected
        return {
            "scenario_id": "aide.archive-history-recovery",
            "profile": "1440-light",
            "status": "passed",
            "ownership_and_draft_preserved": True,
            "simulation": "real local UI/database; archive history response deliberately unavailable once",
        }
    except Exception:
        page.screenshot(path=str(OUT / "failure-archive-history-recovery.png"))
        raise
    finally:
        (OUT / "events-archive-history-recovery.json").write_text(
            json.dumps(events, indent=2) + "\n"
        )
        context.close()


def check_primary_handoff_recovery(browser, ids, width, theme):
    """A real app handoff cannot overwrite or send from a failed primary read."""
    name = f"{width}-{theme}"
    context = browser.new_context(
        viewport={"width": width, "height": 844 if width < 700 else 900},
        has_touch=width < 700,
        service_workers="block",
        reduced_motion="reduce",
    )
    assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
    failing = False
    allow_send = False
    events = {
        "console": [],
        "page_errors": [],
        "external": [],
        "new_sessions": [],
        "chat": [],
        "forbidden": [],
        "failed_primary_reads": 0,
    }

    def boundary(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(request.url)
            return route.abort()
        if url.path == "/api/sessions" and request.method == "POST":
            events["new_sessions"].append(request.post_data)
            return route.abort()
        if request.method == "POST" and (
            url.path == "/api/aide/calls"
            or url.path.endswith("/offer")
            or url.path in {"/api/aide/coding/pair", "/api/aide/coding/runs"}
        ):
            events["forbidden"].append(url.path)
            return route.abort()
        if failing and url.path == f"/api/sessions/{ids['primary']}/history":
            events["failed_primary_reads"] += 1
            return route.fulfill(status=503, json={"detail": "synthetic canonical history outage"})
        if url.path == "/api/chat" and request.method == "POST":
            body = request.post_data_json
            events["chat"].append(body)
            if not allow_send or body.get("session_id") != ids["primary"]:
                events["forbidden"].append("chat before canonical recovery or wrong owner")
                return route.abort()
            answer = "The recovered primary conversation received this handoff."
            chunks = [
                {"saved_user": {"id": "synthetic-handoff-user"}},
                {"delta": answer},
                {"saved_message": {"id": "synthetic-handoff-answer", "content": answer}},
            ]
            stream = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            return route.fulfill(content_type="text/event-stream", body=stream + "data: [DONE]\n\n")
        return route.continue_()

    context.route("**/*", boundary)
    page = context.new_page()
    page.set_default_timeout(10_000)
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["console"].append(message.text) if message.type == "error" else None,
    )
    primary_draft = "Keep this original primary draft until its conversation is restored."
    archive_draft = "This draft belongs only to the earlier Kyoto conversation."
    question = "Help me choose the next step after this app handoff."
    try:
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        page.locator("#composer-ta").fill(primary_draft)
        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="archive"]').click()
        page.locator(f'.session-item[data-id="{ids["old"]}"] .session-open').click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["old"])
        page.locator("#composer-ta").fill(archive_draft)
        owner_hash = page.evaluate("location.hash")
        messages = page.locator("#messages").inner_text()
        failing = True
        page.locator("#aide-history-return").click()
        panel = page.locator("#aide-context-panel")
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("could not open your conversation")

        def assert_failed_owner():
            expect(panel).to_be_visible()
            expect(panel).to_contain_text("could not open your conversation")
            assert page.locator("#composer-outer").evaluate("element => element.inert")
            assert page.evaluate("window._currentSession.id") == ids["old"]
            assert (
                page.evaluate("async () => (await import('/static/js/sessions.js')).getActiveId()")
                == ids["old"]
            )
            assert page.evaluate("location.hash") == owner_hash
            assert page.locator("#messages").inner_text() == messages
            expect(page.locator("#composer-ta")).to_have_value(archive_draft)
            assert not events["chat"] and not events["new_sessions"], events
            assert "wait for the current answer" not in page.locator("body").inner_text()

        assert_failed_owner()
        blocked_reads = events["failed_primary_reads"]
        assert page.evaluate("question => window._askInChat(question)", question) is False
        assert_failed_owner()
        assert (
            page.evaluate(
                "question => window._askInChat(question, false, null, 'central-owned-project')",
                question,
            )
            is False
        )
        assert_failed_owner()
        assert events["failed_primary_reads"] == blocked_reads
        page.screenshot(path=str(OUT / f"aide-handoff-canonical-unavailable-{name}.png"))
        failed_reads = events["failed_primary_reads"]
        with page.expect_response(
            lambda response: (
                response.url.endswith(f"/api/sessions/{ids['primary']}/history")
                and response.status == 503
            )
        ):
            panel.get_by_role("button", name="retry", exact=True).click()
        expect(panel).to_contain_text("could not open your conversation")
        assert events["failed_primary_reads"] > failed_reads
        assert_failed_owner()
        failing = False
        panel.get_by_role("button", name="retry", exact=True).click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(panel).not_to_be_visible()
        expect(page.locator("#composer-ta")).to_have_value(primary_draft)
        assert not page.locator("#composer-outer").evaluate("element => element.inert")
        assert not events["chat"] and not events["new_sessions"], events
        allow_send = True
        assert page.evaluate("question => window._askInChat(question)", question) is True
        expect(page.locator("#messages")).to_contain_text(
            "The recovered primary conversation received this handoff."
        )
        assert len(events["chat"]) == 1, events
        assert events["chat"][0]["session_id"] == ids["primary"]
        assert events["chat"][0]["message"] == question
        assert context.request.get(BASE + "/api/aide/conversation").json()["id"] == ids["primary"]
        page.screenshot(path=str(OUT / f"aide-handoff-canonical-recovered-{name}.png"))
        assert not any(
            events[key] for key in ("external", "new_sessions", "page_errors", "forbidden")
        ), events
        unexpected = [
            message
            for message in events["console"]
            if message
            != "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
            and "selectSession Error: conversation unavailable" not in message
        ]
        assert not unexpected, unexpected
        return {
            "scenario_id": "aide.primary-handoff-recovery",
            "profile": name,
            "status": "passed",
            "failed_recovery_keeps_owner_and_drafts": True,
            "same_primary_handoff_send": True,
            "simulation": "real _askInChat and local UI; injected primary-history503; intercepted text SSE",
        }
    except Exception:
        page.screenshot(path=str(OUT / f"failure-primary-handoff-recovery-{name}.png"))
        raise
    finally:
        (OUT / f"events-primary-handoff-recovery-{name}.json").write_text(
            json.dumps(events, indent=2) + "\n"
        )
        context.close()


def check_reply_menu(page, reply, ids, name, kind, events, rewrites, *, touch=False, stress=False):
    """Exercise the actual compact menu without replacing its action callbacks."""
    actions = reply.locator(".msg-actions")
    trigger = actions.locator(".msg-more-trigger")
    copy = actions.locator(".msg-copy-action")
    menu = actions.locator(".msg-actions-menu")

    def activate(target):
        return target.tap() if touch else target.click()

    def focused_item_is_contained():
        focused = menu.evaluate("""menu => {
          const active = document.activeElement, popup = menu.getBoundingClientRect();
          const item = active?.getBoundingClientRect();
          return {inside:menu.contains(active), popup:popup.toJSON(), item:item?.toJSON()};
        }""")
        assert focused["inside"] and focused["item"], focused
        item, popup = focused["item"], focused["popup"]
        assert item["top"] >= popup["top"] - 1 and item["bottom"] <= popup["bottom"] + 1, focused
        assert item["left"] >= popup["left"] - 1 and item["right"] <= popup["right"] + 1, focused

    expect(actions.locator(":scope > button:visible")).to_have_count(2)
    expect(menu).not_to_be_visible()
    expect(copy).to_have_attribute("aria-label", "copy reply")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    assert menu.evaluate(
        "element => Boolean(element.closest('.ai-wrap') && element.closest('.msg-row'))"
    )
    trigger.scroll_into_view_if_needed()
    # Finish browser scrolling before opening a surface that intentionally
    # dismisses on page scroll; streamed replies also finish scrolling here.
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    trigger.focus()
    # Native focus can scroll again at browser zoom. Wait for the focused
    # trigger's geometry and chat offset to settle before the first key, so a
    # queued setup-scroll event cannot masquerade as post-open user scrolling.
    # Do not repeat this after Escape: return-focus must support immediate Space.
    trigger.evaluate("""element => new Promise((resolve, reject) => {
      const chat = document.querySelector('#chat');
      const deadline = performance.now() + 2000;
      let previous = '', stableFrames = 0;
      const sample = () => {
        if (document.activeElement !== element) return reject(new Error('reply trigger lost focus'));
        const box = element.getBoundingClientRect();
        const current = JSON.stringify([chat.scrollTop, chat.scrollLeft,
          box.x, box.y, box.width, box.height, innerWidth, innerHeight]);
        stableFrames = current === previous ? stableFrames + 1 : 0;
        previous = current;
        if (stableFrames >= 2) return resolve();
        if (performance.now() >= deadline) return reject(new Error('reply trigger did not settle'));
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    })""")
    for key in ("Enter", "Space"):
        page.keyboard.press(key)
        expect(menu).to_be_visible()
        focused_item_is_contained()
        page.keyboard.press("Escape")
        expect(menu).not_to_be_visible()
        expect(trigger).to_be_focused()
    page.keyboard.press("ArrowDown")
    options = menu.locator('button[role="menuitem"]:not([disabled])')
    expect(options.first).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("ArrowUp")
    expect(options.last).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("Home")
    expect(options.first).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("End")
    expect(options.last).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("ArrowDown")
    expect(options.first).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("Escape")
    expect(menu).not_to_be_visible()
    expect(trigger).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(options.last).to_be_focused()
    focused_item_is_contained()
    page.keyboard.press("Escape")
    activate(trigger)
    expect(menu).to_be_visible()
    focused_item_is_contained()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    geometry(page, ["#" + menu.get_attribute("id")])
    placement = menu.evaluate("""menu => {
      const trigger = menu.closest('.msg-actions').querySelector('.msg-more-trigger');
      const anchor = trigger.getBoundingClientRect(), popup = menu.getBoundingClientRect();
      const hit = document.elementFromPoint(anchor.x + anchor.width / 2, anchor.y + anchor.height / 2);
      return {anchor:anchor.toJSON(), popup:popup.toJSON(),
        triggerReceivesPointer:trigger === hit || trigger.contains(hit),
        intersects:popup.left < anchor.right && popup.right > anchor.left &&
          popup.top < anchor.bottom && popup.bottom > anchor.top,
        scrollHeight:menu.scrollHeight, clientHeight:menu.clientHeight,
        overflowY:getComputedStyle(menu).overflowY};
    }""")
    assert not placement["intersects"], placement
    assert placement["triggerReceivesPointer"], placement
    if placement["scrollHeight"] > placement["clientHeight"]:
        assert placement["overflowY"] in {"auto", "scroll"}, placement
        menu.evaluate("""async element => {
          element.scrollTop = element.scrollHeight;
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        expect(menu).to_be_visible()
        assert menu.evaluate("element => element.scrollTop > 0"), placement
        last_box, menu_box = options.last.bounding_box(), menu.bounding_box()
        assert last_box and menu_box and last_box["y"] >= menu_box["y"], (last_box, menu_box)
        assert last_box["y"] + last_box["height"] <= menu_box["y"] + menu_box["height"] + 1, (
            last_box,
            menu_box,
        )
        menu.evaluate("""async element => {
          element.scrollTop = 0;
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        expect(menu).to_be_visible()
    page.mouse.move(0, 0)
    page.screenshot(path=str(OUT / f"aide-reply-menu-{kind}-{name}.png"))
    for option in options.all():
        bounds = option.bounding_box()
        assert bounds and bounds["height"] >= 44, bounds
        assert option.evaluate("element => Number(getComputedStyle(element).opacity)") == 1, (
            option.inner_text()
        )
    activate(trigger)
    expect(menu).not_to_be_visible()
    activate(trigger)
    composer = page.locator("#composer-ta")
    # The popup may cover the composer's center at narrow widths. Dismiss it
    # through an exposed part of the real textarea rather than clicking through.
    exposed = composer.evaluate("""element => {
      const rect = element.getBoundingClientRect();
      for (const x of [8, rect.width / 2, rect.width - 8]) {
        for (const y of [8, rect.height / 2, rect.height - 8]) {
          const hit = document.elementFromPoint(rect.x + x, rect.y + y);
          if (hit === element || element.contains(hit)) return {x, y};
        }
      }
      return null;
    }""")
    assert exposed, "reply menu leaves no reachable composer area for outside dismissal"
    if touch:
        composer.tap(position=exposed)
    else:
        composer.click(position=exposed)
    expect(menu).not_to_be_visible()
    expect(page.locator("#composer-ta")).to_be_focused()

    trigger.focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Shift+Tab")
    expect(menu).not_to_be_visible()
    expect(copy).to_be_focused()
    trigger.focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")
    expect(menu).not_to_be_visible()
    assert not page.evaluate("document.activeElement.closest('.msg-actions-menu') !== null")

    others = page.locator(".msg-more-trigger")
    if others.count() > 1:
        other = next(
            item
            for item in others.all()
            if item.get_attribute("aria-controls") != menu.get_attribute("id")
        )
        activate(trigger)
        # A menu can legitimately cover another reply's button. Keyboard entry
        # tests singleton ownership without clicking through the open surface.
        other.evaluate("element => element.focus({ preventScroll: true })")
        page.keyboard.press("ArrowDown")
        expect(menu).not_to_be_visible()
        expect(page.locator(".msg-actions-menu:visible")).to_have_count(1)
        page.keyboard.press("Escape")

    viewport = dict(page.viewport_size)
    activate(trigger)
    page.set_viewport_size({**viewport, "height": viewport["height"] - 16})
    expect(menu).not_to_be_visible()
    page.set_viewport_size(viewport)
    if stress:
        page.set_viewport_size({**viewport, "height": 240})
        trigger.scroll_into_view_if_needed()
        activate(trigger)
        assert menu.evaluate("element => element.scrollHeight > element.clientHeight")
        menu.evaluate("element => { element.scrollTop = 44; }")
        page.wait_for_function(
            "id => document.getElementById(id).scrollTop > 0", arg=menu.get_attribute("id")
        )
        page.evaluate("() => new Promise(requestAnimationFrame)")
        expect(menu).to_be_visible()
        page.keyboard.press("Escape")
        activate(trigger)
        page.locator("#chat").evaluate(
            "element => element.scrollBy(0, element.scrollTop > 0 ? -12 : 12)"
        )
        expect(menu).not_to_be_visible()
        page.set_viewport_size(viewport)

    before_copy = page.evaluate("window.__centralCopied.length")
    content = reply.locator(".ai-content").inner_text()
    activate(copy)
    page.wait_for_function("count => window.__centralCopied.length === count + 1", arg=before_copy)
    assert page.evaluate("window.__centralCopied.at(-1)") == content
    message_id = reply.evaluate("element => element.closest('.msg-row').dataset.msgId")
    rewrites[message_id] = reply.evaluate("element => element.answerText")
    before_rewrite = len(events["rewrite"])
    activate(trigger)
    with page.expect_request(lambda request: urlsplit(request.url).path == "/api/chat/rewrite"):
        activate(menu.locator('[data-style="shorter"]'))
    expect(menu).not_to_be_visible()
    expect(menu.locator('[data-style="shorter"]')).to_have_text("shorter")
    assert len(events["rewrite"]) == before_rewrite + 1
    assert events["rewrite"][-1] == {
        "session_id": ids["primary"],
        "style": "shorter",
        "msg_id": message_id,
    }

    activate(trigger)
    task_action = menu.get_by_role("menuitem", name="+plan task", exact=True)
    if kind == "history":
        task_action.focus()
        page.keyboard.press("Enter")
    else:
        activate(task_action)
    expect(menu).not_to_be_visible()
    expect(page.locator(".capture-review")).to_be_visible()
    expect(page.locator("#capture-notes")).to_have_value(rewrites[message_id])
    page.locator("#capture-cancel").click()
    expect(page.locator(".capture-review")).not_to_be_visible()
    expect(trigger).to_be_focused()
    expect(copy).to_have_text("copy")
    expect(actions.locator(":scope > button:visible")).to_have_count(2)
    return {
        "kind": kind,
        "menu_items": options.count(),
        "placement": placement,
        "original_copy_rewrite_and_plan_callbacks": True,
    }


def run_profile(pw, browser, ids, width, theme, zoom=False):
    name = f"{width}-{theme}" + ("-zoom200" if zoom else "")
    context = context_for(pw, browser, width, theme, zoom)
    assert context.request.put(BASE + "/api/appearance", data=from_legacy(theme, None)).ok
    events = {
        "console": [],
        "page_errors": [],
        "external": [],
        "forbidden": [],
        "chat": [],
        "simulated_branches": [],
        "rewrite": [],
    }
    rewrites = {}
    context.add_init_script("""
      window.__centralMicRequests = 0;
      window.__centralCopied = [];
      if (navigator.clipboard) navigator.clipboard.writeText = async text => {
        window.__centralCopied.push(text);
      };
      if (navigator.mediaDevices) {
        navigator.mediaDevices.getUserMedia = () => {
          window.__centralMicRequests += 1;
          return Promise.reject(new Error('microphone forbidden in central gate'));
        };
      }
    """)

    def boundary(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != urlsplit(BASE).netloc:
            events["external"].append(request.url)
            return route.abort()
        if request.method == "POST" and (
            url.path == "/api/aide/calls"
            or url.path.endswith("/offer")
            or url.path in {"/api/aide/coding/pair", "/api/aide/coding/runs"}
        ):
            events["forbidden"].append(url.path)
            return route.abort()
        if url.path == f"/api/sessions/{ids['primary']}/git/branches":
            if request.method != "GET":
                events["forbidden"].append(url.path)
                return route.abort()
            events["simulated_branches"].append(url.path)
            return route.fulfill(
                json={
                    "repository": True,
                    "available": True,
                    "current": "main",
                    "branches": ["main", "review"],
                    "dirty": False,
                }
            )
        if url.path == "/api/chat/rewrite" and request.method == "POST":
            body = request.post_data_json
            events["rewrite"].append(body)
            assert body["session_id"] == ids["primary"] and body["msg_id"] in rewrites, body
            return route.fulfill(json={"content": rewrites[body["msg_id"]]})
        if url.path == "/api/chat" and request.method == "POST":
            body = request.post_data_json
            events["chat"].append(body)
            answer = "The launch notes come first. Start with the three decisions still open."
            user_id, answer_id = str(uuid4()), str(uuid4())
            with SessionLocal() as db:
                db.add_all(
                    [
                        Message(
                            id=user_id,
                            session_id=body["session_id"],
                            role="user",
                            content=body["message"],
                        ),
                        Message(
                            id=answer_id,
                            session_id=body["session_id"],
                            role="assistant",
                            content=answer,
                        ),
                    ]
                )
                if body["message"] != "Check this streamed reply menu.":
                    db.commit()
            chunks = [
                {"saved_user": {"id": user_id}},
                {"delta": answer},
                {"saved_message": {"id": answer_id, "content": answer}},
            ]
            stream = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            return route.fulfill(content_type="text/event-stream", body=stream + "data: [DONE]\n\n")
        return route.continue_()

    context.route("**/*", boundary)
    page = context.new_page()
    page.set_default_timeout(10_000)
    page.on("pageerror", lambda error: events["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: events["console"].append(message.text) if message.type == "error" else None,
    )
    row = {
        "scenario_id": "aide.central-assistant",
        "profile": name,
        "simulation": SIMULATION,
        "status": "failed",
    }
    context.tracing.start(screenshots=True, snapshots=True)
    try:
        page.goto(BASE + "/?view=chat", wait_until="networkidle")
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        if zoom:
            worker = (
                context.service_workers[0]
                if context.service_workers
                else context.wait_for_event("serviceworker")
            )
            result = worker.evaluate("""async () => {
              const tab = (await chrome.tabs.query({})).find(t => t.url.startsWith('http://127.0.0.1:'));
              await chrome.tabs.setZoom(tab.id, 2);
              return await chrome.tabs.getZoom(tab.id);
            }""")
            assert result == 2
            page.wait_for_function("innerWidth === 720 && devicePixelRatio === 2")
            row["native_zoom"] = result
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
        expect(page.locator("#aide-sidebar")).not_to_be_visible()
        expect(page.locator("#messages")).to_contain_text("Help me make room")
        controls = [
            "#aide-mode-conversation",
            "#aide-mode-coding",
            "#aide-call-open",
            "#aide-jobs-open",
            "#aide-more-btn",
            "#send-btn",
        ]
        row["controls"] = geometry(page, controls)

        row["reply_menus"] = [
            check_reply_menu(
                page,
                page.locator("#messages .ai-wrap").first,
                ids,
                name,
                "history",
                events,
                rewrites,
                touch=width < 700,
                stress=width == 1440 and theme == "dark" and not zoom,
            )
        ]

        if width == 1440 and theme == "dark" and not zoom:
            page.locator("#composer-ta").fill("What should I start with?")
            page.locator("#send-btn").click()
            expect(page.locator("#messages")).to_contain_text("The launch notes come first.")
            expect(page.locator("#send-btn")).to_be_enabled()
            assert len(events["chat"]) == 1
            assert events["chat"][0]["session_id"] == ids["primary"]
        else:
            page.locator("#composer-ta").fill("Check this streamed reply menu.")
            page.locator("#send-btn").click()
            expect(page.locator("#messages .ai-wrap").last).to_contain_text(
                "The launch notes come first."
            )
            expect(
                page.locator("#messages .ai-wrap").last.locator(".msg-more-trigger")
            ).to_be_visible()
            expect(page.locator("#send-btn")).to_be_enabled()
        row["reply_menus"].append(
            check_reply_menu(
                page,
                page.locator("#messages .ai-wrap").last,
                ids,
                name,
                "streamed",
                events,
                rewrites,
                touch=width < 700,
            )
        )
        page.evaluate("id => window._refreshAideSessionQuietly(id)", ids["primary"])
        expect(page.locator(".msg-actions-menu:visible")).to_have_count(0)
        page.locator("#chat").evaluate("element => { element.scrollTop = 0; }")
        expect(page.locator("#toast-container .toast")).to_have_count(0)
        page.mouse.move(0, 0)
        page.screenshot(path=str(OUT / f"aide-conversation-{name}.png"))

        draft = "Keep this unsent thought while I look around."
        page.locator("#composer-ta").fill(draft)
        jobs = page.locator("#aide-jobs-open")
        jobs.click()
        panel = page.locator("#aide-context-panel")
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("running")
        expect(panel).to_contain_text("queued")
        expect(panel).to_contain_text("The reading list is ready")
        geometry(page, ["#aide-context-close"])
        assert page.locator(".app").evaluate("element => element.inert")
        page.screenshot(path=str(OUT / f"aide-background-{name}.png"))
        page.keyboard.press("Shift+Tab")
        assert panel.evaluate("element => element.contains(document.activeElement)")
        page.keyboard.press("Escape")
        expect(panel).not_to_be_visible()
        expect(jobs).to_be_focused()
        assert not page.locator(".app").evaluate("element => element.inert")

        jobs.focus()
        page.keyboard.press("Enter")
        panel.locator('[data-run-id="central-owned-succeeded"]').click()
        detail = page.locator('.aide-run-detail[data-run-id="central-owned-succeeded"]')
        expect(detail).to_contain_text("The reading list is ready")
        detail.locator("summary").click()
        expect(detail.locator(".aide-run-events")).to_contain_text("The reading list is ready")
        page.keyboard.press("Escape")
        expect(detail).not_to_be_visible()
        expect(page.locator("#composer-ta")).to_be_focused()

        if zoom:
            jobs.click()
            panel.locator('[data-run-id="central-owned-queued"]').click()
            queued = page.locator('.aide-run-detail[data-run-id="central-owned-queued"]')
            queued.get_by_role("button", name="cancel job", exact=True).click()
            expect(queued.locator("[data-run-state]")).to_have_text("cancelled")
            expect(queued).to_have_attribute("aria-busy", "false")
            result = context.request.get(BASE + "/api/jarvis/runs/central-owned-queued")
            assert result.ok and result.json()["state"] == "cancelled"
            row["cancel_focus"] = page.evaluate(
                "({tag:document.activeElement.tagName,id:document.activeElement.id,text:document.activeElement.textContent.slice(0,80)})"
            )
            page.keyboard.press("Escape")
            expect(queued).not_to_be_visible()
            row["queued_cancel"] = True

        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="memory"]').click()
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("I prefer short answers and one useful next step.")
        page.screenshot(path=str(OUT / f"aide-memory-{name}.png"))
        page.keyboard.press("Escape")
        expect(panel).not_to_be_visible()
        expect(page.locator("#aide-more-btn")).to_be_focused()

        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="archive"]').click()
        expect(page.locator("#aide-sidebar")).to_be_visible()
        sidebar = page.locator("#aide-sidebar")
        page.locator("#aide-sidebar-close").focus()
        page.keyboard.press("Shift+Tab")
        last = sidebar.locator(
            'button:visible:not([disabled]), input:visible:not([disabled]), [tabindex="0"]:visible'
        ).last
        expect(last).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator("#aide-sidebar-close")).to_be_focused()
        page.locator("#aide-sidebar-close").click()
        expect(page.locator("#aide-sidebar")).not_to_be_visible()
        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="archive"]').click()
        expect(page.locator("#aide-sidebar")).to_be_visible()
        archive_row = page.locator(f'.session-item[data-id="{ids["old"]}"] .session-open')
        archive_row.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["old"])
        expect(page.locator("#messages")).to_contain_text("Nothing here was removed")
        expect(page.locator("#aide-history-return")).to_be_visible()
        page.screenshot(path=str(OUT / f"aide-archive-{name}.png"))
        page.locator("#aide-history-return").click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(page.locator("#composer-ta")).to_have_value(draft)
        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="archive"]').click()
        page.locator(f'.session-item[data-id="{ids["old"]}"] .session-open').click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["old"])
        page.evaluate("window._navigateTo('today')")
        expect(page.locator("body")).to_have_attribute("data-space", "today")
        page.evaluate("window._navigateTo('chat')")
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(page.locator("#composer-ta")).to_have_value(draft)

        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="options"]').click()
        expect(page.locator("#aide-new-context")).to_be_visible()
        page.locator("#aide-project-context").click()
        project_menu = page.locator("#aide-project-context-menu")
        expect(project_menu).to_be_visible()
        project_menu.get_by_role("menuitemradio", name="Prototype", exact=True).click()
        page.wait_for_function("window._currentSession?.project_id === 'central-owned-project'")
        expect(page.locator("#aide-project-context-label")).to_have_text("Prototype")
        page.locator("#aide-branch-context").click()
        branch_menu = page.locator("#aide-branch-context-menu")
        expect(branch_menu).to_be_visible()
        expect(branch_menu.get_by_role("menuitemradio", name="main", exact=True)).to_have_attribute(
            "aria-checked", "true"
        )
        expect(branch_menu.get_by_role("menuitemradio", name="review", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        expect(branch_menu).not_to_be_visible()
        expect(page.locator("#aide-branch-context")).to_be_focused()
        page.locator("#effort-btn").click()
        page.locator('#perm-menu [data-kind="effort"][data-v="high"]').click()
        expect(page.locator("#effort-btn .effort-label")).to_have_text("high")
        geometry(
            page,
            ["#aide-project-context", "#aide-branch-context", "#effort-btn", "#aide-options-close"],
        )
        page.screenshot(path=str(OUT / f"aide-conversation-settings-{name}.png"))
        page.locator("#aide-options-close").click()
        expect(page.locator("#aide-new-context")).not_to_be_visible()

        page.locator("#aide-call-open").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "call")
        expect(page.locator("#aide-call-workspace")).to_be_visible()
        expect(page.locator("#aide-call-workspace")).to_contain_text("unavailable")
        page.evaluate("id => window._refreshAideSessionQuietly(id)", ids["primary"])
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "call")
        assert page.evaluate("window.__centralMicRequests") == 0
        page.screenshot(path=str(OUT / f"aide-call-unavailable-{name}.png"))
        page.locator("#aide-call-details-toggle").click()
        expect(page.locator("#aide-call-details")).to_be_visible()
        expect(page.locator("#aide-call-details")).to_contain_text("main conversation")
        geometry(page, ["#aide-call-back", "#aide-call-details-toggle"])
        page.locator("#aide-call-details-toggle").click()
        expect(page.locator("#aide-call-details")).not_to_be_visible()
        page.locator("#aide-call-back").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
        page.locator("#aide-call-open").click()
        expect(page.locator("#aide-call-workspace")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#aide-call-workspace")).not_to_be_visible()

        page.locator("#aide-mode-coding").click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "coding")
        expect(page.locator("#aide-coding-workspace")).to_be_visible()
        expect(page.locator("#messages")).not_to_be_visible()
        expect(page.locator("#aide-work-panel")).not_to_be_visible()
        geometry(page, ["#aide-mode-conversation", "#aide-mode-coding"])
        page.screenshot(path=str(OUT / f"aide-coding-unpaired-{name}.png"))
        page.locator("#aide-more-btn").click()
        page.locator('[data-aide-central-action="private"]').click()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
        expect(page.locator("#incognito-bar")).to_be_visible()
        expect(page.locator("#aide-coding-workspace")).not_to_be_visible()
        page.locator("#composer-ta").fill("Private unsent fixture only")
        page.locator("#incognito-exit").click()
        page.wait_for_function("id => window._currentSession?.id === id", arg=ids["primary"])
        expect(page.locator("#incognito-bar")).not_to_be_visible()
        expect(page.locator("body")).to_have_attribute("data-aide-mode", "conversation")
        expect(page.locator("#composer-ta")).to_have_value(draft)
        assert context.request.get(BASE + "/api/aide/conversation").json()["id"] == ids["primary"]
        page.evaluate("window._navigateTo('today')")
        expect(page.locator("body")).to_have_attribute("data-space", "today")
        page.evaluate("id => window._refreshAideSessionQuietly(id)", ids["primary"])
        expect(page.locator("body")).to_have_attribute("data-space", "today")
        page.evaluate("window._navigateTo('chat')")
        expect(page.locator("body")).to_have_attribute("data-space", "aide")
        expect(page.locator("#composer-ta")).to_have_value(draft)
        assert not events["external"], events
        assert not events["forbidden"], events
        assert not events["page_errors"], events
        assert not events["console"], events
        assert page.evaluate("window.__centralMicRequests") == 0
        row.update(
            status="passed", primary_restored=True, draft_preserved=True, no_live_actions=True
        )
    except Exception as error:
        row["error"] = str(error)
        page.screenshot(path=str(OUT / f"failure-{name}.png"))
        raise
    finally:
        (OUT / f"events-{name}.json").write_text(json.dumps(events, indent=2) + "\n")
        (OUT / f"scenario-{name}.json").write_text(json.dumps(row, indent=2) + "\n")
        context.tracing.stop(path=OUT / f"trace-{name}.zip")
        context.close()
    return row


def main():
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            rows.extend(capture_empty(browser))
            seed_context = browser.new_context()
            ids = seed(seed_context.request)
            seed_context.close()
            rows.append(check_primary_recovery(browser, ids))
            rows.append(check_archive_recovery(browser, ids))
            for width, theme in [(1440, "dark"), (390, "light")]:
                rows.append(check_primary_handoff_recovery(browser, ids, width, theme))
            for width, theme, zoom in [
                (1440, "dark", False),
                (1440, "light", False),
                (390, "dark", False),
                (390, "light", False),
                (320, "dark", False),
                (768, "light", False),
                (1440, "dark", True),
            ]:
                rows.append(run_profile(pw, browser, ids, width, theme, zoom))
        finally:
            browser.close()
            (OUT / "scenarios.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
