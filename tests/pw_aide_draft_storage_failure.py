"""Owned draft-save refusal and same-action recovery through real app controls."""

import base64
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[1] / "tests"),
]
from browser_gate_safety import require_server_ownership  # noqa: E402

from services.appearance import from_legacy  # noqa: E402

FAULT = """() => {
  const storage = localStorage, original = Storage.prototype.setItem;
  let failure = null; const attempts = [];
  Storage.prototype.setItem = function(key, value) {
    if (this === storage && String(key).startsWith('aide-draft-v2-')) {
      attempts.push({key: String(key), value: String(value), failure});
      if (failure) throw new DOMException('owned synthetic draft write failure', failure);
    }
    return original.call(this, key, value);
  };
  window.__ownedDraftFailure = {
    set(value) { failure = value; },
    attempts() { return attempts.slice(); },
    restore() { Storage.prototype.setItem = original; failure = null; },
  };
}"""

STATE = """() => {
  const input = document.getElementById('composer-ta'), active = document.activeElement;
  const rect = active?.getBoundingClientRect();
  const r = rect ? {x:rect.x,y:rect.y,width:rect.width,height:rect.height} : null;
  const hit = rect ? document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2) : null;
  return {
    text: input.value, selection: [input.selectionStart,input.selectionEnd],
    scope: window._pendingDocumentScope || null,
    session: window._currentSession?.id || null,
    session_project: window._currentSession?.project_id || '',
    pending_project: window._pendingProjectId || '',
    private: document.body.classList.contains('is-incognito'),
    attachments: [...document.querySelectorAll('#attachment-chips .attach-chip')].map(n => ({
      id:n.dataset.id,name:n.querySelector('.attach-name')?.textContent,
      text:n.textContent,classes:n.className,
    })),
    focus: {id:active?.id,tag:active?.tagName,rect:r,
      visible:!!active?.getClientRects().length,
      center_hit:!!active && !!hit && (active===hit || active.contains(hit))},
    href: location.href,
  };
}"""


def capture(ctx, page, path, width, height):
    session = ctx.new_cdp_session(page)
    try:
        png = base64.b64decode(
            session.send(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )["data"]
        )
    finally:
        session.detach()
    Path(path).write_bytes(png)
    dimensions = struct.unpack(">II", png[16:24])
    assert dimensions == (width, height), dimensions
    return {"path": str(path), "sha256": hashlib.sha256(png).hexdigest(), "pixels": dimensions}


def close_sidebar(page):
    if page.evaluate("innerWidth <= 700") and page.locator("#aide-sidebar").is_visible():
        page.keyboard.press("Escape")
        expect(page.locator("#aide-sidebar")).to_be_hidden()


def sidebar(page):
    if not page.locator("#aide-sidebar").is_visible():
        page.locator("#sidebar-toggle-btn").click()
    expect(page.locator("#aide-sidebar")).to_be_visible()


def app_view(page, view):
    page.locator("#app-drawer-btn").click()
    page.locator(f'#app-drawer-grid button[data-view="{view}"]').click()
    expect(page.locator("#app-drawer")).to_be_hidden()


def keyboard_target(page, selector):
    for _ in range(100):
        if page.evaluate("selector => document.activeElement?.matches(selector)", selector):
            return
        page.keyboard.press("Tab")
    raise AssertionError(f"normal Tab did not reach {selector}")


def run():
    base = "http://127.0.0.1:" + os.environ["PORT"]
    origin = urlsplit(base)
    data = Path(os.environ["ALLES_DATA"]).resolve()
    assert Path(tempfile.gettempdir()).resolve() in data.parents
    assert os.environ["ALLES_TEST_DATA"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == os.environ["ALLES_TEST_RUN_ID"]
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    cases = [
        ("new-task", "QuotaExceededError"),
        ("switch", "SecurityError"),
        ("incognito", "QuotaExceededError"),
        ("project", "SecurityError"),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width, height, theme in [(1440, 900, "light"), (390, 844, "dark")]:
                for case, failure in cases:
                    label = f"{width}-{theme}-{case}"
                    ctx = browser.new_context(
                        viewport={"width": width, "height": height},
                        service_workers="block",
                        reduced_motion="reduce",
                        has_touch=width == 390,
                    )
                    unexpected, errors, console, uploads_deleted = [], [], [], []
                    row = {
                        "case": label,
                        "failure": failure,
                        "status": "failed",
                        "captures": [],
                        "rendered_pass": False,
                    }
                    rows.append(row)

                    def boundary(route):
                        request = route.request
                        url = urlsplit(request.url)
                        if (url.scheme, url.netloc) != (origin.scheme, origin.netloc):
                            unexpected.append(request.url)
                            return route.abort()
                        if url.path == "/api/andromeda/providers" and request.method == "GET":
                            return route.fulfill(json={"providers": []})
                        if url.path == "/api/system/searxng" and request.method == "GET":
                            return route.fulfill(
                                json={
                                    "installed": False,
                                    "available": False,
                                    "support_verified": False,
                                    "bind": "owned fixture",
                                    "version": "",
                                    "license": "",
                                    "data_kept": False,
                                }
                            )
                        if (
                            url.path == "/api/chat"
                            or url.path.startswith("/owned/")
                            or (
                                url.path.startswith("/api/andromeda/")
                                and not url.path.startswith("/api/andromeda/saved")
                            )
                            or (
                                url.path.startswith("/api/system/searxng/")
                                or (
                                    url.path.startswith("/api/models/")
                                    and not (
                                        url.path == "/api/models/roles" and request.method == "GET"
                                    )
                                )
                            )
                        ):
                            unexpected.append(request.url)
                            return route.abort()
                        if url.path.startswith("/api/uploads/") and request.method == "DELETE":
                            uploads_deleted.append(request.url)
                        return route.continue_()

                    ctx.route("**/*", boundary)
                    ctx.route_web_socket("**/*", lambda ws: (unexpected.append(ws.url), ws.close()))
                    page = ctx.new_page()
                    page.set_default_timeout(8000)
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            console.append(message.text) if message.type == "error" else None
                        ),
                    )
                    api = ctx.request
                    try:
                        assert api.post(base + "/api/setup/dismiss").ok
                        assert api.put(base + "/api/appearance", data=from_legacy(theme, None)).ok
                        assert api.get(base + "/api/models").json() == [], (
                            "requires an empty owned model fixture"
                        )
                        outgoing = api.post(
                            base + "/api/sessions", data={"name": "outgoing " + label}
                        ).json()["id"]
                        other = api.post(
                            base + "/api/sessions", data={"name": "destination " + label}
                        ).json()["id"]
                        note = f"draft-storage-{label}.md"
                        assert api.post(
                            base + "/api/vault-md/file",
                            data={
                                "path": note,
                                "content": "# owned note\nkeep the blue cup\n",
                            },
                        ).ok
                        target_url = base + f"/?view=chat#{outgoing}"
                        if case == "project":
                            project = api.post(
                                base + "/api/projects", data={"name": "owned target " + label}
                            ).json()
                            saved = api.post(
                                base + "/api/andromeda/saved",
                                data={
                                    "query": "owned saved context " + label,
                                    "request": {
                                        "query": "owned saved context " + label,
                                        "category": "all",
                                        "normal_results": True,
                                        "overview": False,
                                    },
                                    "results": [
                                        {
                                            "title": "owned source",
                                            "url": base + "/owned/draft-source",
                                            "snippet": "retained synthetic source excerpt",
                                        }
                                    ],
                                    "evidence": [],
                                    "overview": {},
                                },
                            )
                            assert saved.ok, saved.text()
                            saved = saved.json()
                            target_url = (
                                base
                                + f"/?view=chat&project_id={project['id']}&saved={saved['id']}#{outgoing}"
                            )
                        page.goto(target_url, wait_until="networkidle")
                        page.wait_for_function(
                            "id => window._currentSession?.id === id", arg=outgoing
                        )
                        close_sidebar(page)
                        app_view(page, "wiki")
                        document = page.locator(f'#wiki-tree [data-file="{note}"]')
                        expect(document).to_be_attached()
                        if not document.is_visible():
                            page.locator("#wiki-tree-toggle").click()
                        document.click()
                        page.locator("#wiki-ask-btn").click()
                        page.locator("#wiki-ask-input").fill("initial source question")
                        page.locator("#wiki-ask-go").click()
                        field = page.locator("#composer-ta")
                        expect(field).to_have_value("initial source question")
                        close_sidebar(page)
                        selected = page.evaluate("window._pendingDocumentScope")
                        assert selected["kind"] == "vault_documents"
                        assert selected["documents"][0]["path"] == note
                        assert page.evaluate("window._currentSession.id") == outgoing
                        page.locator("#more-tools-btn").click()
                        with (
                            page.expect_file_chooser() as chooser,
                            page.expect_response(
                                lambda response: (
                                    urlsplit(response.url).path == "/api/uploads"
                                    and response.request.method == "POST"
                                )
                            ) as uploaded,
                        ):
                            page.locator("#_more_tools_menu").get_by_role(
                                "menuitem", name="upload file", exact=True
                            ).click()
                            chooser.value.set_files(
                                {
                                    "name": "owned-draft.txt",
                                    "mimeType": "text/plain",
                                    "buffer": b"owned attachment bytes\n",
                                }
                            )
                        assert uploaded.value.ok
                        upload = uploaded.value.json()["id"]
                        expect(page.locator(f'.attach-chip[data-id="{upload}"]')).to_be_visible()
                        key = "aide-draft-v2-" + outgoing
                        stored = page.evaluate("key => localStorage.getItem(key)", key)
                        assert json.loads(stored) == {
                            "text": "initial source question",
                            "document_scope": selected,
                        }
                        page.evaluate(FAULT)
                        page.evaluate("failure => __ownedDraftFailure.set(failure)", failure)
                        text = "  newer unsaved question\n中文 草稿  "
                        field.fill(text)
                        assert page.evaluate("document.activeElement.id") == "composer-ta"
                        page.keyboard.press("Home")
                        page.keyboard.press("Shift+ArrowRight")
                        expect(
                            page.get_by_text(
                                "could not keep this draft for reload. keep this tab open.",
                                exact=True,
                            )
                        ).to_be_visible()

                        def target():
                            if case in ("new-task", "switch"):
                                sidebar(page)
                                selector = (
                                    "#new-chat-btn"
                                    if case == "new-task"
                                    else f'.session-item[data-id="{other}"] .session-open'
                                )
                                keyboard_target(page, selector)
                                return "keyboard"
                            if case == "project":
                                app_view(page, "andromeda")
                                expect(page.locator(".andromeda-result-title")).to_have_text(
                                    "owned source"
                                )
                                assert (
                                    urlsplit(page.url).query.find("project_id=" + project["id"])
                                    >= 0
                                )
                                return "#andromeda-explain"
                            return "#incognito-btn"

                        action = target()
                        before = page.evaluate(STATE)
                        attempts = len(page.evaluate("__ownedDraftFailure.attempts()"))
                        row["before"] = before
                        row["stored_before"] = stored
                        row["captures"].append(
                            capture(ctx, page, out / f"{label}-before.png", width, height)
                        )
                        if action == "keyboard":
                            page.keyboard.press("Enter")
                        else:
                            page.locator(action).click()
                        page.wait_for_function(
                            "n => __ownedDraftFailure.attempts().length > n", arg=attempts
                        )
                        after = page.evaluate(STATE)
                        row["refused"] = after
                        row["captures"].append(
                            capture(ctx, page, out / f"{label}-refused.png", width, height)
                        )
                        for name in (
                            "text",
                            "selection",
                            "scope",
                            "session",
                            "session_project",
                            "pending_project",
                            "private",
                            "attachments",
                        ):
                            assert after[name] == before[name], (name, before[name], after[name])
                        assert after["text"] == text and after["scope"] == selected
                        assert page.evaluate("key => localStorage.getItem(key)", key) == stored
                        assert not uploads_deleted
                        assert (
                            api.get(base + "/api/uploads/" + upload).body()
                            == b"owned attachment bytes\n"
                        )
                        close_sidebar(page)
                        expect(page.locator("#aide-document-scope")).to_be_visible()
                        expect(field).to_have_value(text)
                        row["captures"].append(
                            capture(ctx, page, out / f"{label}-preserved.png", width, height)
                        )
                        page.evaluate("__ownedDraftFailure.set(null)")
                        action = target()
                        if action == "keyboard":
                            page.keyboard.press("Enter")
                        else:
                            page.locator(action).click()
                        if case == "switch":
                            page.wait_for_function(
                                "id => window._currentSession?.id === id", arg=other
                            )
                            expect(field).to_have_value("")
                        elif case == "project":
                            page.wait_for_function(
                                "id => window._currentSession === null && window._pendingProjectId === id",
                                arg=project["id"],
                            )
                            expect(field).to_have_value(
                                re.compile("retained synthetic source excerpt")
                            )
                            assert page.evaluate("window._pendingDocumentScope") is None
                        else:
                            expect(field).to_have_value("")
                            assert page.evaluate("window._currentSession") is None
                        if case == "incognito":
                            expect(page.locator("#incognito-exit")).to_be_visible()
                            expect(page.locator("#attachment-chips")).to_be_hidden()
                            row["private_active_attachments"] = page.evaluate(
                                "async () => (await import('/static/js/uploads.js?v=253')).getAttachments()"
                            )
                            assert row["private_active_attachments"] == []
                            assert api.get(base + "/api/uploads/" + upload).status == 404
                        else:
                            assert page.evaluate(STATE)["attachments"] == before["attachments"]
                        assert json.loads(
                            page.evaluate("key => localStorage.getItem(key)", key)
                        ) == {
                            "text": text,
                            "document_scope": selected,
                        }
                        row["recovered"] = page.evaluate(STATE)
                        row["captures"].append(
                            capture(ctx, page, out / f"{label}-recovered.png", width, height)
                        )
                        if case == "incognito":
                            page.locator("#incognito-exit").click()
                        sidebar(page)
                        page.locator(f'.session-item[data-id="{outgoing}"] .session-open').click()
                        expect(field).to_have_value(text)
                        close_sidebar(page)
                        expect(page.locator("#aide-document-scope")).to_be_visible()
                        assert page.evaluate("window._pendingDocumentScope") == selected
                        keyboard_target(page, "#composer-ta")
                        row["returned"] = page.evaluate(STATE)
                        assert row["returned"]["focus"]["visible"]
                        row["captures"].append(
                            capture(ctx, page, out / f"{label}-returned.png", width, height)
                        )
                        assert not unexpected and not errors and not console, (
                            unexpected,
                            errors,
                            console,
                        )
                        row["status"] = "passed"
                    except Exception:
                        row["error"] = traceback.format_exc()
                        try:
                            row["captures"].append(
                                capture(ctx, page, out / f"{label}-failure.png", width, height)
                            )
                        except Exception:
                            row["failure_capture_error"] = traceback.format_exc()
                        raise
                    finally:
                        row.update(
                            unexpected=unexpected,
                            page_errors=errors,
                            console_errors=console,
                            upload_deletions=uploads_deleted,
                        )
                        observation_error = None
                        try:
                            if not page.is_closed():
                                row["fault_attempts"] = page.evaluate(
                                    "window.__ownedDraftFailure?.attempts() || []"
                                )
                        except Exception:
                            observation_error = traceback.format_exc()
                            row["fault_observation_error"] = observation_error
                            row["status"] = "failed"
                        try:
                            (out / "draft-storage.json").write_text(
                                json.dumps(rows, indent=2) + "\n"
                            )
                        finally:
                            ctx.close()
                        if observation_error and "error" not in row:
                            raise AssertionError(observation_error)
        finally:
            browser.close()


if __name__ == "__main__":
    run()
