"""Owned compact Mail navigation, real cache reads and local draft persistence.

Preparation is side-effect free. After the parent releases verification, run
--serve-fixture through the owned runner environment in one process, then run this
file without that flag against that server. The server mode executes the unchanged
canonical guard, seeds SQL headers and the existing in-process message cache, and
keeps the actual routes, renderer and draft services. No provider transport exists.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import runpy
import sqlite3
import struct
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from browser_gate_safety import require_server_ownership  # noqa: E402

GUARD_SHA256 = "ca71cf20e2631b71662abd376d02702fe637883038115c47a82368644009e44f"
PROFILES = [(w, t, False) for w in (1440, 820, 390) for t in ("light", "dark")]
PROFILES += [(1440, t, True) for t in ("light", "dark")]
SOURCES = (
    "static/js/mail.js",
    "static/style.css",
    "static/kokuen.css",
    "static/index.html",
    "static/js/specialist_groups.js",
    "tests/pw_mail_compact_navigation.py",
)
DRAFT_FIELDS = ("account_id", "to", "cc", "bcc", "subject", "body", "in_reply_to", "references")
FIXTURE_FILE = "mail-compact-fixture.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def owned_environment():
    data = Path(os.environ["ALLES_DATA"]).resolve()
    database = Path(os.environ["ALLES_DB"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert data != ROOT and not data.is_relative_to(ROOT / "data")
    assert database.is_relative_to(data), "database must belong to the marked fixture root"
    assert run_id and (data / ".alles-test-owner").read_text().strip() == run_id
    port = int(os.environ["PORT"])
    assert 0 < port < 65536
    return data, database, run_id, f"http://127.0.0.1:{port}"


def seed_fixture(guard):
    """Called after the real application lifespan has initialized its owned DB."""
    data, database, run_id, _ = owned_environment()
    from core.database import CachedMessage, MailAccount, SessionLocal
    from core.settings import save_settings
    from services import mail

    aid = "mail-compact-" + run_id
    messages = [
        ("801", "another cached message", "another synthetic message"),
        (
            "802",
            "café meeting 日本語 — bring the yellow folder",
            "bring the yellow folder.\nmeet at the café. 日本語",
        ),
        ("803", "unavailable cached message", None),
    ]
    with SessionLocal() as db:
        assert db.query(MailAccount).count() == 0, "use a fresh mail fixture root"
        assert db.get(MailAccount, aid) is None, "use a fresh marked fixture for each run"
        account = MailAccount(
            id=aid,
            name="compact mail fixture",
            email=aid + "@example.invalid",
            username=aid,
            imap_host="",
            smtp_host="",
            password="",
            use_ssl=False,
        )
        db.add(account)
        db.flush()
        cache_account = {
            key: getattr(account, key)
            for key in ("imap_host", "imap_port", "username", "email", "use_ssl")
        }
        for uid, subject, body in messages:
            db.add(
                CachedMessage(
                    id=aid + "-" + uid,
                    account_id=aid,
                    folder="INBOX",
                    uid=uid,
                    sender="Élodie <elodie@example.invalid>",
                    recipients=account.email,
                    subject=subject,
                    date="Tue, 06 Oct 2026 07:00:00 +0000",
                    date_ts=1791270000 - int(uid),
                    seen=True,
                    message_id=f"<{aid}-{uid}@example.invalid>",
                    thread_id=aid + "-" + uid,
                )
            )
            if body is not None:
                message = dict(
                    uid=uid,
                    subject=subject,
                    text=body,
                    html="",
                    from_="Élodie <elodie@example.invalid>",
                    to=account.email,
                    date="Tue, 06 Oct 2026 07:00:00 +0000",
                    message_id=f"<{aid}-{uid}@example.invalid>",
                    references="",
                    has_attachment=False,
                )
                message["from"] = message.pop("from_")
                key = (mail._acct_key(cache_account), "INBOX", uid)
                mail._put_cache(mail._MESSAGE_CACHE, key, 6 * 60 * 60, message)
        db.commit()
    save_settings(
        {"mail_poll_seconds": 10, "mail_signature": "", "language": "en", "timezone": "UTC"}
    )
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT account_id, folder, uid, subject FROM cached_messages WHERE account_id=? ORDER BY uid",
            (aid,),
        ).fetchall()
    write_json(
        data / FIXTURE_FILE,
        {
            "run_id": run_id,
            "account_id": aid,
            "messages": messages,
            "sql_headers": rows,
            "guard_sha256": digest(guard),
            "pid": os.getpid(),
            "fixture": "real SQL header cache and service body cache; empty provider hosts; routes unchanged",
        },
    )


def serve_fixture(guard):
    owned_environment()
    guard = guard.resolve()
    assert digest(guard) == GUARD_SHA256, "canonical guard changed; parent must review it"
    import uvicorn

    original_run = uvicorn.run

    def guarded_run(application, *args, **kwargs):
        original_lifespan = application.router.lifespan_context

        @asynccontextmanager
        async def fixture_lifespan(app):
            async with original_lifespan(app) as state:
                seed_fixture(guard)
                yield state

        application.router.lifespan_context = fixture_lifespan
        return original_run(application, *args, **kwargs)

    uvicorn.run = guarded_run
    try:
        runpy.run_path(str(guard), run_name="__main__")
    finally:
        uvicorn.run = original_run


def owned_context(pw, browser, data, label, width, zoom, motion):
    options = dict(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        device_scale_factor=1,
        timezone_id="UTC",
        locale="en-US",
        has_touch=width == 390,
        service_workers="block",
        reduced_motion=motion,
    )
    if not zoom:
        return browser.new_context(**options)
    profile = data / ("mail-compact-browser-" + label)
    extension = profile / "extension"
    extension.mkdir(parents=True)
    write_json(
        extension / "manifest.json",
        {
            "manifest_version": 3,
            "name": "owned native zoom check",
            "version": "1.0",
            "permissions": ["tabs"],
            "background": {"service_worker": "zoom.js"},
        },
    )
    (extension / "zoom.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
    return pw.chromium.launch_persistent_context(
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


def run():
    from playwright.sync_api import expect, sync_playwright

    from services.appearance import from_legacy

    data, database, run_id, base = owned_environment()
    require_server_ownership(base, run_id)
    fixture = json.loads((data / FIXTURE_FILE).read_text())
    assert fixture["run_id"] == run_id and fixture["guard_sha256"] == GUARD_SHA256
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"]) / "mail-compact-navigation"
    out.mkdir(parents=True, exist_ok=True)
    source_before = {path: digest(ROOT / path) for path in SOURCES}
    write_json(out / "source-before.json", source_before)
    write_json(out / "fixture.json", fixture)
    aid = fixture["account_id"]
    origin = urlsplit(base)
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, theme, zoom in PROFILES:
                for motion in ("no-preference", "reduce"):
                    label = f"{width}-{theme}-{'native200-' if zoom else ''}{motion}"
                    row = {"profile": label, "status": "failed", "checks": [], "captures": []}
                    records.append(row)
                    context = owned_context(pw, browser, data, label, width, zoom, motion)
                    events = {
                        key: []
                        for key in (
                            "external",
                            "websockets",
                            "page",
                            "console",
                            "http",
                            "failed",
                            "forbidden",
                            "workers",
                        )
                    }
                    expected_failures, held, assets = set(), [], {}
                    recovery = {
                        "lose_save": False,
                        "block_read": False,
                        "saved": None,
                        "writes": [],
                    }
                    delayed = {"enabled": False}

                    def boundary(route):
                        request = route.request
                        target = urlsplit(request.url)
                        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                            events["external"].append(request.url)
                            return route.abort()
                        if target.path == "/sw.js" or request.resource_type == "serviceworker":
                            events["workers"].append(request.url)
                            return route.abort()
                        # The application may read metadata; this test never sends or schedules mail.
                        if request.method not in {"GET", "HEAD"} and target.path.startswith(
                            (
                                "/api/mail/send",
                                "/api/mail/schedule",
                                "/api/mail/oauth",
                                "/api/mail/accounts",
                            )
                        ):
                            events["forbidden"].append(request.url)
                            return route.abort()
                        if (
                            target.path == f"/api/mail/message/{aid}"
                            and delayed["enabled"]
                            and parse_qs(target.query).get("uid") == ["802"]
                        ):
                            response = route.fetch(max_redirects=0)
                            assert response.ok and response.json()["uid"] == "802"
                            held.append((route, response))
                            return
                        if target.path == "/api/mail/drafts":
                            if (
                                request.method == "GET"
                                and recovery["block_read"]
                                and parse_qs(target.query).get("context") == ["true"]
                            ):
                                expected_failures.add(request.url)
                                return route.abort("failed")
                            if request.method == "POST":
                                recovery["writes"].append(request.post_data_json)
                                if recovery["lose_save"]:
                                    response = route.fetch(max_redirects=0)
                                    assert response.ok, response.text()
                                    recovery["saved"] = response.json()
                                    recovery["lose_save"] = False
                                    recovery["block_read"] = True
                                    expected_failures.add(request.url)
                                    return route.abort("failed")
                        return route.continue_()

                    context.route("**/*", boundary)
                    context.route_web_socket(
                        "**/*", lambda ws: (events["websockets"].append(ws.url), ws.close())
                    )
                    page = context.new_page()
                    page.set_default_timeout(10000)
                    page.on("pageerror", lambda error: events["page"].append(str(error)))
                    page.on(
                        "console",
                        lambda message: events["console"].append(
                            {
                                "type": message.type,
                                "text": message.text,
                                "location": message.location,
                            }
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: events["failed"].append(
                            {"url": request.url, "failure": request.failure}
                        ),
                    )

                    def response_event(response):
                        path = urlsplit(response.url).path.lstrip("/")
                        if path in {"static/js/mail.js", "static/style.css", "static/kokuen.css"}:
                            assets[path] = response
                        if response.status >= 400:
                            events["http"].append({"url": response.url, "status": response.status})

                    page.on("response", response_event)

                    def api(method, path, payload=None):
                        assert path.startswith("/api/") and not path.startswith("//")
                        response = context.request.fetch(
                            base + path, method=method, data=payload, max_redirects=0
                        )
                        assert response.ok, (path, response.status, response.text())
                        return response.json()

                    def profile_proof(verify=True):
                        proof = page.evaluate("""() => ({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
                          scale:visualViewport.scale,zoom:getComputedStyle(document.documentElement).zoom,
                          reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,
                          theme:document.documentElement.getAttribute('data-theme'),
                          overflow:document.documentElement.scrollWidth>innerWidth})""")
                        if not verify:
                            return proof
                        assert (proof["width"], proof["height"]) == (
                            (720, 450) if zoom else (width, 844 if width == 390 else 900)
                        ), proof
                        assert (
                            proof["dpr"] == (2 if zoom else 1)
                            and proof["scale"] == 1
                            and float(proof["zoom"]) == 1
                        ), proof
                        assert proof["reduced"] == (motion == "reduce") and not proof["overflow"], (
                            proof
                        )
                        assert (proof["theme"] == "light") == (theme == "light"), proof
                        return proof

                    def capture(name, verify=True):
                        proof = profile_proof(verify=verify)
                        session = context.new_cdp_session(page)
                        try:
                            png = base64.b64decode(
                                session.send(
                                    "Page.captureScreenshot",
                                    {"format": "png", "captureBeyondViewport": False},
                                )["data"]
                            )
                        finally:
                            session.detach()
                        filename = f"{label}-{name}.png"
                        (out / filename).write_bytes(png)
                        proof["physical_pixels"] = struct.unpack(">II", png[16:24])
                        proof["active"] = page.evaluate("document.activeElement?.outerHTML")
                        proof["screenshot"] = filename
                        row["captures"].append(proof)
                        write_json(out / f"{label}-{name}.json", proof)
                        if verify:
                            assert proof["physical_pixels"] == (
                                width,
                                844 if width == 390 else 900,
                            ), proof

                    def visible_content(locator, first_line=False):
                        expect(locator).to_be_visible()
                        geometry = locator.evaluate("""e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,
                          right:r.right,bottom:r.bottom,vw:innerWidth,vh:innerHeight}}""")
                        assert geometry["x"] >= 0 and geometry["right"] <= geometry["vw"] + 1, (
                            geometry
                        )
                        assert (
                            geometry["y"] >= 0
                            and geometry["y"] + min(24, geometry["height"]) <= geometry["vh"]
                        ), geometry
                        if not first_line:
                            assert geometry["bottom"] <= geometry["vh"] + 1, geometry
                        return geometry

                    def pane_layout():
                        compact = zoom or width <= 1100
                        for selector in ("#mail-list", "#mail-sidebar"):
                            if compact:
                                expect(page.locator(selector)).to_be_hidden()
                            else:
                                expect(page.locator(selector)).to_be_visible()
                        main = page.locator("#mail-main").bounding_box()
                        assert main and main["width"] >= (
                            width / 2 if not compact else (720 if zoom else width) - 4
                        ), main
                        if not compact:
                            sidebar = page.locator("#mail-sidebar").bounding_box()
                            listing = page.locator("#mail-list").bounding_box()
                            assert sidebar["x"] + sidebar["width"] <= listing["x"] + 1
                            assert listing["x"] + listing["width"] <= main["x"] + 1
                        visible_content(page.locator(".mail-pane-back"))
                        return {"compact": compact, "main": main}

                    def draft_viewport(stage):
                        # Observe settled layout without any action that could scroll the editor.
                        page.evaluate(
                            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                        )
                        expect(page.locator("#mc-subj")).to_be_focused()
                        pane_layout()
                        geometry = page.evaluate(r"""() => {
                          const pane = document.querySelector('#mail-main');
                          const nav = pane.querySelector('.mail-pane-nav');
                          const subject = pane.querySelector('#mc-subj'), body = pane.querySelector('#mc-html');
                          const rect = e => { const r = e.getBoundingClientRect(); return {x:r.x, y:r.y, right:r.right, bottom:r.bottom, height:r.height}; };
                          const p = rect(pane), n = rect(nav), s = rect(subject), b = rect(body), style = getComputedStyle(body);
                          const label = subject.labels[0], l = label ? rect(label) : null;
                          const top = Math.max(0, p.y, n.bottom), bottom = Math.min(innerHeight, p.bottom);
                          const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
                          let node; while ((node = walker.nextNode()) && !node.textContent.trim()) {}
                          let text = null;
                          if (node) {
                            const range = document.createRange(), start = node.textContent.search(/\S/);
                            range.setStart(node, start); range.setEnd(node, Math.min(node.length, start + 24));
                            text = rect(range);
                          }
                          const hit = r => document.elementFromPoint((r.x + r.right) / 2, (r.y + r.bottom) / 2);
                          return {pane:p, nav:n, label:l, subject:s, body:b, text, top, bottom, width:innerWidth,
                            labelFor:label?.htmlFor, labelText:label?.textContent.trim(),
                            labelUncovered:!!label && label.contains(hit(l)),
                            lineHeight:parseFloat(style.lineHeight),
                            bodyRoom:Math.min(bottom, b.bottom - parseFloat(style.paddingBottom)) - Math.max(top, b.y + parseFloat(style.paddingTop)),
                            subjectUncovered:hit(s) === subject, textUncovered:!!text && body.contains(hit(text)),
                            scroll:{main:pane.scrollTop, layout:pane.parentElement.scrollTop, document:document.scrollingElement.scrollTop},
                            subjectPrimitive:subject.dataset.kokuenPrimitive};
                        }""")
                        row.setdefault("draft_geometry", {})[stage] = geometry
                        for name in ("label", "subject", "text"):
                            rect = geometry[name]
                            assert (
                                rect
                                and rect["y"] >= geometry["top"]
                                and rect["bottom"] <= geometry["bottom"]
                            ), geometry
                            assert (
                                rect["x"] >= max(0, geometry["pane"]["x"])
                                and rect["right"]
                                <= min(geometry["width"], geometry["pane"]["right"]) + 1
                            ), geometry
                        assert geometry["subjectUncovered"] and geometry["textUncovered"], geometry
                        assert geometry["labelUncovered"], geometry
                        assert (
                            geometry["labelFor"] == "mc-subj" and geometry["labelText"] == "subject"
                        ), geometry
                        assert geometry["bodyRoom"] >= 2 * geometry["lineHeight"], geometry

                    def keyboard_to(locator, reverse=False):
                        for _ in range(90):
                            if locator.evaluate("e=>document.activeElement===e"):
                                expect(locator).to_be_focused()
                                assert locator.evaluate(
                                    "e=>e.matches(':focus-visible') && getComputedStyle(e).outlineStyle!=='none'"
                                )
                                return
                            page.keyboard.press("Shift+Tab" if reverse else "Tab")
                        raise AssertionError("keyboard could not reach " + str(locator))

                    def back_to(opener):
                        button = page.locator(".mail-pane-back")
                        keyboard_to(button, reverse=True)
                        page.keyboard.press("Enter")
                        expect(page.locator("#mail-main")).to_be_empty()
                        expect(page.locator("#mail-list")).to_be_visible()
                        expect(opener).to_be_focused()

                    def message_button(uid):
                        return page.locator(
                            f'#mail-list .mail-row[data-aid="{aid}"][data-folder="INBOX"][data-uid="{uid}"] .mail-open'
                        )

                    def enter_mail(reload=False):
                        if reload:
                            page.reload(wait_until="networkidle")
                        else:
                            page.goto(base + "/?view=inbox", wait_until="networkidle")
                        page.get_by_role("tab", name="mail", exact=True).click()
                        expect(message_button("802")).to_be_visible()

                    def pending_storage():
                        return page.evaluate(
                            "Object.fromEntries(Object.entries(sessionStorage).filter(([k])=>k.startsWith('alles-mail-draft:')))"
                        )

                    def readback(saved):
                        current = api("GET", "/api/mail/drafts/" + saved["id"])
                        assert {field: current[field] for field in DRAFT_FIELDS} == {
                            field: saved[field] for field in DRAFT_FIELDS
                        }
                        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
                            values = db.execute(
                                'SELECT account_id,"to",cc,bcc,subject,body,in_reply_to,"references" FROM mail_drafts WHERE id=? AND deleted_at IS NULL',
                                (saved["id"],),
                            ).fetchone()
                        assert dict(zip(DRAFT_FIELDS, values, strict=True)) == {
                            field: saved[field] for field in DRAFT_FIELDS
                        }
                        return current

                    try:
                        api("POST", "/api/setup/dismiss")
                        api("PUT", "/api/appearance", from_legacy(theme, None))
                        # These are real API responses from the stored cache, not browser fixtures.
                        cached = api("GET", f"/api/mail/inbox/{aid}")
                        assert (
                            cached["cached"] is True
                            and cached["error"] == "no IMAP host configured"
                        )
                        assert {m["uid"] for m in cached["messages"]} == {"801", "802", "803"}
                        actual_message = api("GET", f"/api/mail/message/{aid}?uid=802&folder=INBOX")
                        assert actual_message["text"] == fixture["messages"][1][2]
                        row["api_cache_readback"] = {"list": cached, "message": actual_message}
                        enter_mail()
                        if zoom:
                            worker = next(
                                (
                                    w
                                    for w in context.service_workers
                                    if w.url.startswith("chrome-extension://")
                                ),
                                None,
                            )
                            if worker is None:
                                worker = context.wait_for_event(
                                    "serviceworker",
                                    predicate=lambda w: w.url.startswith("chrome-extension://"),
                                )
                            assert (
                                worker.evaluate(
                                    """async origin=>{const tabs=await chrome.tabs.query({});
                              const tab=tabs.find(t=>t.url&&new URL(t.url).origin===origin);
                              await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id)}""",
                                    base,
                                )
                                == 2
                            )
                            page.wait_for_function(
                                "innerWidth===720&&innerHeight===450&&devicePixelRatio===2"
                            )
                        row["profile_proof"] = profile_proof()
                        expect(page.locator("#mail-list .mail-error-strip")).to_contain_text(
                            "showing saved mail; no IMAP host configured"
                        )
                        row["delivered_assets"] = {
                            path: hashlib.sha256(response.body()).hexdigest()
                            for path, response in assets.items()
                        }
                        assert set(row["delivered_assets"]) == {
                            "static/js/mail.js",
                            "static/style.css",
                            "static/kokuen.css",
                        }
                        for path, checksum in row["delivered_assets"].items():
                            assert checksum == source_before[path], (
                                path,
                                checksum,
                                source_before[path],
                            )
                        capture("list")

                        opener = message_button("802")
                        keyboard_to(opener)
                        with page.expect_response(
                            lambda r: (
                                urlsplit(r.url).path == f"/api/mail/read/{aid}"
                                and r.request.method == "POST"
                            )
                        ) as read:
                            page.keyboard.press("Enter")
                        assert read.value.ok and read.value.json()["seen"] is True
                        subject = page.locator(".mail-reader-subject")
                        expect(subject).to_be_focused()
                        row["reader_geometry"] = {
                            "subject": visible_content(subject),
                            "body": visible_content(
                                page.locator(".mail-body-text"), first_line=True
                            ),
                            **pane_layout(),
                        }
                        expect(page.locator(".mail-body-text")).to_have_text(actual_message["text"])
                        capture("reader")
                        if zoom or width <= 1100:
                            warning = page.locator(".mail-pane-warning")
                            keyboard_to(warning.locator("summary"), reverse=True)
                            page.keyboard.press("Enter")
                            expect(warning.locator("p")).to_contain_text(
                                "showing saved mail; no IMAP host configured"
                            )
                            with page.expect_response(
                                lambda r: urlsplit(r.url).path == f"/api/mail/inbox/{aid}"
                            ):
                                warning.get_by_role(
                                    "button", name="retry connection", exact=True
                                ).press("Enter")
                            expect(subject).to_be_visible()
                            warning.locator("summary").press("Enter")
                            capture("connection-warning")
                        # Wait for the actual 10-second poll, not a renderer call or fabricated refresh.
                        old_node = opener.element_handle()
                        with page.expect_response(
                            lambda r: (
                                urlsplit(r.url).path == f"/api/mail/inbox/{aid}"
                                and parse_qs(urlsplit(r.url).query).get("quick") == ["1"]
                            ),
                            timeout=20000,
                        ) as polled:
                            page.wait_for_function(
                                "old=>!old.isConnected", arg=old_node, timeout=20000
                            )
                        assert polled.value.ok
                        assert not old_node.evaluate("e=>e.isConnected")
                        back_to(opener)
                        row["checks"].append(
                            "real cached reader; compact focus/layout; desktop three panes; connection retry; actual poll replaces node; keyboard back returns exact second row"
                        )
                        capture("back-after-poll")

                        message_button("803").press("Enter")
                        expect(page.locator("#mail-message-retry")).to_be_focused()
                        expect(page.locator("#mail-main")).to_contain_text(
                            "could not load message: no IMAP host configured"
                        )
                        pane_layout()
                        with page.expect_response(
                            lambda r: urlsplit(r.url).path == f"/api/mail/message/{aid}"
                        ):
                            page.locator("#mail-message-retry").press("Enter")
                        expect(page.locator("#mail-message-retry")).to_be_focused()
                        capture("unavailable")
                        back_to(message_button("803"))
                        delayed["enabled"] = True
                        opener.press("Enter")
                        page.wait_for_function(
                            "!!document.querySelector('#mail-main .mail-pane-back')"
                        )
                        for _ in range(100):
                            if held:
                                break
                            page.wait_for_timeout(20)
                        assert len(held) == 1
                        back_to(opener)
                        delayed["enabled"] = False
                        route, response = held.pop()
                        with page.expect_response(
                            lambda r: urlsplit(r.url).path == f"/api/mail/message/{aid}"
                        ):
                            route.fulfill(response=response)
                        page.wait_for_timeout(250)
                        expect(page.locator("#mail-main")).to_be_empty()
                        expect(opener).to_be_focused()
                        row["checks"].append(
                            "real unavailable body and retry; held real cached response after back cannot reopen pane or take focus"
                        )
                        capture("late-response")

                        page.locator("#mail-compose-btn").click()
                        body = page.locator("#mc-html")
                        expect(body).to_be_visible()
                        pane_layout()
                        expect(
                            page.locator('.mc-chipfield[data-role="to"] .mc-chip-input')
                        ).to_be_focused()
                        exact_subject = "compact draft café 日本語 " + label
                        page.locator("#mc-subj").fill(exact_subject)
                        body.fill("exact saved draft — café 日本語 " + label)
                        expected_body = body.inner_html()
                        capture("compose")
                        with page.expect_response(
                            lambda r: (
                                r.url == base + "/api/mail/drafts" and r.request.method == "POST"
                            )
                        ) as saved_response:
                            page.locator("#mc-save").press("Enter")
                        assert saved_response.value.ok
                        saved = saved_response.value.json()
                        assert (
                            saved["subject"] == exact_subject
                            and saved["body"] == expected_body
                            and saved["account_id"] == aid
                        )
                        expect(page.get_by_text("draft saved", exact=True).last).to_be_visible()
                        row["draft_saved"] = readback(saved)
                        enter_mail(reload=True)
                        page.get_by_role("button", name="drafts", exact=True).click()
                        draft_opener = page.locator(
                            f'.mail-draft-row[data-id="{saved["id"]}"] .mail-open'
                        )
                        draft_opener.press("Enter")
                        expect(page.locator("#mc-subj")).to_be_focused()
                        expect(page.locator("#mc-subj")).to_have_value(exact_subject)
                        assert body.inner_html() == expected_body
                        draft_viewport("saved-reopened")
                        capture("saved-reopened")
                        unsent = "newer unsent work — retain this " + label
                        body.fill(unsent)
                        retained = pending_storage()
                        body.press("Escape")
                        dialog = page.get_by_role("alertdialog")
                        expect(dialog).to_contain_text("discard unsaved draft changes?")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        expect(body).to_have_text(unsent)
                        assert pending_storage() == retained
                        keyboard_to(page.locator("#mc-close"), reverse=True)
                        page.keyboard.press("Enter")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        expect(body).to_have_text(unsent)
                        assert pending_storage() == retained
                        page.locator("#mc-close").press("Enter")
                        dialog.get_by_role("button", name="confirm", exact=True).press("Enter")
                        expect(draft_opener).to_be_focused()
                        expect(page.locator("#mail-main")).to_be_empty()
                        readback(saved)
                        row["checks"].append(
                            "real draft save/API+SQL exact readback/reload; unsaved Escape and Back cancellation retain text; confirmed leave restores exact draft row"
                        )

                        draft_opener.press("Enter")
                        body.fill("pending saved work — café 日本語 " + label)
                        pending_body = body.inner_html()
                        recovery["lose_save"] = True
                        writes_before = len(recovery["writes"])
                        page.locator("#mc-save").press("Enter")
                        expect(page.locator("#mail-draft-status")).to_contain_text(
                            "could not load draft recovery"
                        )
                        assert (
                            recovery["saved"] is not None
                            and recovery["saved"]["body"] == pending_body
                        )
                        retained = pending_storage()
                        assert len(retained) == 1
                        pending = json.loads(next(iter(retained.values())))
                        assert pending["body"] == pending_body and pending["id"] == saved["id"]
                        body.press("Escape")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        assert body.inner_html() == pending_body and pending_storage() == retained
                        page.locator("#mc-close").press("Enter")
                        dialog.get_by_role("button", name="cancel", exact=True).press("Enter")
                        assert body.inner_html() == pending_body and pending_storage() == retained
                        capture("pending-save-retained")
                        page.locator("#mc-close").press("Enter")
                        dialog.get_by_role("button", name="confirm", exact=True).press("Enter")
                        expect(draft_opener).to_be_focused()
                        assert pending_storage() == retained
                        enter_mail(reload=True)
                        assert pending_storage() == retained
                        recovery["block_read"] = False
                        page.locator("#mail-draft-load-retry").press("Enter")
                        page.wait_for_function(
                            "!Object.keys(sessionStorage).some(k=>k.startsWith('alles-mail-draft:'))"
                        )
                        page.get_by_role("button", name="drafts", exact=True).click()
                        draft_opener.press("Enter")
                        assert body.inner_html() == pending_body
                        row["draft_recovered"] = readback(recovery["saved"])
                        assert len(recovery["writes"]) == writes_before + 1, (
                            "reload/read recovery must not post another save"
                        )
                        draft_viewport("pending-save-recovered")
                        capture("pending-save-recovered")
                        row["checks"].append(
                            "lost reply follows a real persisted update; canceled exits and confirmed leave keep exact pending recovery; reload confirms same saved bytes without another POST"
                        )
                        assert not any(
                            worker.url.startswith(base) for worker in context.service_workers
                        )
                        assert (
                            not events["external"]
                            and not events["websockets"]
                            and not events["forbidden"]
                            and not events["page"]
                            and not events["http"]
                        ), events
                        unexpected_failures = [
                            item
                            for item in events["failed"]
                            if item["url"] not in expected_failures
                        ]
                        unexpected_console = [
                            item
                            for item in events["console"]
                            if item["type"] == "error"
                            and not (
                                item["location"].get("url") in expected_failures
                                and "Failed to load resource" in item["text"]
                            )
                            and "Service Worker registration blocked by Playwright"
                            not in item["text"]
                        ]
                        assert not unexpected_failures and not unexpected_console, (
                            unexpected_failures,
                            unexpected_console,
                        )
                        row["status"] = "passed"
                    except Exception:
                        row["error"] = traceback.format_exc()
                        try:
                            capture("failed", verify=False)
                        except Exception:
                            row["capture_error"] = traceback.format_exc()
                    finally:
                        for route, _ in held:
                            route.abort()
                        row["events"] = events
                        row["expected_failed_requests"] = sorted(expected_failures)
                        context.close()
                        write_json(out / "scenarios.json", records)
                        print(label, row["status"], flush=True)
        finally:
            browser.close()
            source_after = {path: digest(ROOT / path) for path in SOURCES}
            write_json(out / "source-after.json", source_after)
    assert source_after == source_before, "source changed during rendered verification"
    assert len(records) == 16 and all(row["status"] == "passed" for row in records), records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve-fixture",
        action="store_true",
        help="run the real app through the canonical guard with the owned mail cache seeded",
    )
    parser.add_argument("--guard", type=Path, default=ROOT / ".agent/guarded_server.py")
    args = parser.parse_args()
    if args.serve_fixture:
        serve_fixture(args.guard)
    else:
        run()


if __name__ == "__main__":
    main()
