"""Owned Mail workflow regressions against the actual working-tree application.

Run through run_mail_workflows_recovery.py with a reviewed source/acceptance pair
and the canonical fixture guard. Every case gets a fresh owned synthetic database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "scripts")]
GUARD_SHA256 = "ca71cf20e2631b71662abd376d02702fe637883038115c47a82368644009e44f"
BASIC_CASES = ["accounts-round-trip", "recipients-save", "filter"]
LOADING_CASES = [
    "accounts-loading-before",
    "accounts-loading-after",
    "rules-loading-before",
    "rules-loading-after",
]
SOURCES = [
    "static/js/mail.js",
    "static/js/capture.js",
    "static/js/app.js",
    "static/js/appsettings.js",
    "static/js/specialist_groups.js",
    "static/index.html",
    "tests/pw_mail_workflows_recovery.py",
    "tests/run_mail_workflows_recovery.py",
    "tests/pw_mail_compact_navigation.py",
    "tests/browser_gate_safety.py",
    "scripts/run_browser_gates.py",
    "scripts/stabilization_report.py",
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_proof(expected_source, expected_acceptance, guard):
    from stabilization_report import acceptance_fingerprint, source_fingerprint

    proof = {
        "source": source_fingerprint(),
        "acceptance": acceptance_fingerprint(),
        "files": {path: digest(ROOT / path) for path in SOURCES},
        "guard_sha256": digest(guard),
    }
    proof["matches_reviewed_freeze"] = (
        proof["source"] == expected_source
        and proof["acceptance"] == expected_acceptance
        and proof["guard_sha256"] == GUARD_SHA256
    )
    return proof


def install_boundary(context, base, evidence):
    origin = urlsplit(base)

    def boundary(route):
        request, parsed = route.request, urlsplit(route.request.url)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            evidence["unexpected"].append({"url": request.url, "reason": "external"})
            route.abort()
            return
        path = parsed.path
        if path in {"/sw.js", "/service-worker.js", "/static/sw.js", "/static/service-worker.js"}:
            evidence["expected_blocks"].append(
                {"url": request.url, "reason": "service worker disabled for owned fixture"}
            )
            route.abort()
            return
        forbidden = (
            "/api/mail/send",
            "/api/mail/schedule",
            "/api/mail/oauth/google/start",
            "/api/mail/test/",
            "/api/mail/summarize",
            "/api/mail/suggest",
            "/api/mail/extract-event",
            "/api/mail/make-task",
            "/api/mail/rules/run/",
        )
        cached_scheduled = (
            request.method == "GET"
            and path == "/api/mail/scheduled"
            and parsed.query == "context=true"
        )
        if not cached_scheduled and any(path.startswith(prefix) for prefix in forbidden):
            evidence["unexpected"].append({"url": request.url, "reason": "out-of-case operation"})
            route.abort()
            return
        if request.method != "GET" and (
            path.startswith("/api/mail/accounts") or path.startswith("/api/mail/oauth/")
        ):
            evidence["unexpected"].append(
                {"url": request.url, "reason": "account write outside case"}
            )
            route.abort()
            return
        route.continue_()

    context.route("**/*", boundary)

    def websocket(socket):
        evidence["websockets"].append({"url": socket.url, "action": "closed before connection"})
        socket.close()

    context.route_web_socket("**/*", websocket)


def open_mail_settings(page, action):
    page.locator('#mail-view .app-cog[data-app="mail"]').click()
    page.locator(".app-settings-pop").get_by_role("button", name=action, exact=True).click()
    page.locator(
        "#mail-main .mail-accounts" if action == "accounts" else "#mail-main .mail-rules-panel"
    ).wait_for(state="visible")


def loading_case(page, context, base, case, evidence):
    accounts = case.startswith("accounts-")
    query = "context=true" if accounts else ""
    gate = Hold(
        context,
        base,
        evidence,
        "initial-settings",
        "GET",
        "/api/mail/accounts" if accounts else "/api/mail/rules",
        lambda request: urlsplit(request.url).query == query,
    ).install()
    try:
        page.locator('#mail-view .app-cog[data-app="mail"]').click()
        page.locator(".app-settings-pop").get_by_role(
            "button", name="accounts" if accounts else "rules & vacation responder", exact=True
        ).click()
        gate.wait(page)
        loading = page.locator("#mail-main > :first-child").element_handle()
        assert loading and "loading" in loading.inner_text(), (
            "driver must reach initial settings loading"
        )
        page.get_by_role("tab", name="contacts", exact=True).click()
        if case.endswith("-after"):
            held_url = gate.route.request.url
            with page.expect_response(
                lambda response: response.url == held_url and response.request.method == "GET"
            ) as delivered:
                gate.release()
            assert delivered.value.finished() is None
            evidence["timing_events"].append(
                {"phase": "initial-reply-delivered-while-away", "url": held_url}
            )
        page.get_by_role("tab", name="mail", exact=True).click()
        if case.endswith("-before"):
            assert gate.route is not None, "initial reply must still be held at return"
            gate.release()
        page.locator("#mail-accounts-close" if accounts else "#mr-add").wait_for(state="visible")
        assert loading.evaluate("node => !node.isConnected"), (
            "MAIL-C1 obsolete loading owner survived reentry"
        )
        if accounts:
            page.locator(".mail-acct-edit").first.click()
        field = page.locator("#ma-name" if accounts else "#mr-value")
        field.click()
        field.press("ControlOrMeta+A")
        field.press_sequentially("exact returned settings café 日本語")
        root = page.locator("#mail-main > :first-child").element_handle()
        page.get_by_role("tab", name="contacts", exact=True).click()
        page.locator("[data-dialog-cancel]").click()
        assert root.evaluate(
            "node => node.isConnected && node === document.querySelector('#mail-main').firstElementChild"
        )
        assert field.input_value() == "exact returned settings café 日本語"
    finally:
        gate.close()


def serve_fixture(guard, case):
    import pw_mail_compact_navigation as fixture

    original_seed = fixture.seed_fixture

    def seed(path):
        original_seed(path)
        data, _, _, _ = fixture.owned_environment()
        metadata_path = data / fixture.FIXTURE_FILE
        metadata = json.loads(metadata_path.read_text())
        metadata["workflow_case"] = case
        from core.database import MailDraft, ScheduledMail, SessionLocal

        with SessionLocal() as db:
            if case.startswith("cancel-"):
                row = dict(
                    id="00000000-0000-4000-8000-000000000199",
                    account_id=metadata["account_id"],
                    to="recipient@example.invalid",
                    cc="",
                    bcc="",
                    subject="retained cancellation",
                    body="exact cancellation body",
                    html="",
                    in_reply_to="",
                    references="",
                    status="scheduled",
                    send_at="2099-01-01T09:00:00",
                    request_kind="schedule",
                    request_delay=None,
                )
                assert db.query(ScheduledMail).count() == 0
                db.add(ScheduledMail(**row))
                metadata["outgoing"] = row
            if case.startswith("delete-"):
                row = dict(
                    id="00000000-0000-4000-8000-000000000299",
                    account_id=metadata["account_id"],
                    to="recipient@example.invalid",
                    cc="",
                    bcc="",
                    subject="synthetic deletion draft",
                    body="exact deletion draft body",
                    in_reply_to="",
                    references="",
                )
                assert db.query(MailDraft).count() == 0
                db.add(MailDraft(**row))
                metadata["draft"] = row
            db.commit()
        fixture.write_json(metadata_path, metadata)

    fixture.seed_fixture = seed
    fixture.serve_fixture(guard)


CASES = [
    "cancel-newer-reader",
    "cancel-owner",
    "preview-newer-compose",
    "scope-newer-compose",
    "capture-normal",
    "delete-search",
    "delete-owner",
    "reader-return-task",
    "reader-return-event",
]


class Hold:
    def __init__(self, context, base, evidence, name, method, path, check=lambda request: True):
        self.context, self.origin, self.evidence = context, urlsplit(base), evidence
        self.name, self.method, self.path, self.check = name, method, path, check
        self.route = self.response = None
        self.hits = 0

    def matches(self, request):
        parsed = urlsplit(request.url)
        return (
            (parsed.scheme, parsed.netloc) == (self.origin.scheme, self.origin.netloc)
            and request.method == self.method
            and parsed.path == self.path
        )

    def install(self):
        def handler(route):
            if not self.matches(route.request) or self.hits:
                route.fallback()
                return
            assert self.check(route.request), "held request outside its reviewed fixture contract"
            self.response = route.fetch(max_redirects=0)
            assert self.response.ok, f"{self.name}: actual owned response failed"
            self.route = route
            self.hits += 1
            self.evidence["timing_events"].append(
                {
                    "hold": self.name,
                    "phase": "response-held",
                    "url": route.request.url,
                    "method": route.request.method,
                    "status": self.response.status,
                }
            )

        self.handler = handler
        self.context.route("**/*", handler)
        return self

    def wait(self, page):
        # Driver readiness polling only: the product request stays held until the next UI intent.
        deadline = time.monotonic() + 30
        while self.route is None and time.monotonic() < deadline:
            page.wait_for_timeout(10)
        assert self.route is not None, f"driver did not reach {self.name}"

    def release(self):
        assert self.route is not None
        self.route.fulfill(response=self.response)
        self.evidence["timing_events"].append({"hold": self.name, "phase": "released"})
        self.route = self.response = None

    def close(self):
        if self.route is not None:
            self.route.abort()
            self.route = self.response = None
        self.context.unroute("**/*", self.handler)


class TimingCases:
    def __init__(self, context, base, fixture, case, evidence):
        self.context, self.base, self.fixture, self.case, self.evidence = (
            context,
            base,
            fixture,
            case,
            evidence,
        )
        self.origin = urlsplit(base)
        self.holds, self.handlers = [], []
        self.preview_route = None
        self.preview_hits = 0
        self.cancel_scope = ""
        evidence.update(timing_events=[], observations={}, draft_reads=[])

    def owned(self, request):
        parsed = urlsplit(request.url)
        return (parsed.scheme, parsed.netloc) == (self.origin.scheme, self.origin.netloc)

    def hold(self, name, method, path, check=lambda request: True):
        gate = Hold(self.context, self.base, self.evidence, name, method, path, check).install()
        self.holds.append(gate)
        return gate

    def install(self):
        def handler(route):
            request, parsed = route.request, urlsplit(route.request.url)
            if not self.owned(request):
                route.fallback()  # Existing exact-origin boundary rejects it.
                return
            if (
                self.case.startswith("cancel-")
                and request.method == "GET"
                and parsed.path == "/api/mail/scheduled"
            ):
                query = parse_qs(parsed.query, keep_blank_values=True)
                if self.cancel_scope and query == {
                    "request_id": [self.fixture["outgoing"]["id"]],
                    "recovery_scope": [self.cancel_scope],
                }:
                    self.evidence["timing_events"].append(
                        {"phase": "owned-status-read", "url": request.url}
                    )
                    route.continue_()
                    return
            if self.case.startswith("reader-return-"):
                kind = self.case.removeprefix("reader-return-")
                endpoint = "/api/mail/make-task" if kind == "task" else "/api/mail/extract-event"
                if request.method == "POST" and parsed.path == endpoint:
                    assert not parsed.query
                    body = request.post_data_json
                    assert (
                        body["preview"] is True
                        and body["source"]["account_id"] == self.fixture["account_id"]
                    )
                    assert body["source"]["uid"] == "801" and body["source"]["folder"] == "INBOX"
                    self.preview_hits += 1
                    assert self.preview_hits <= 2, (
                        "only the held old preview and explicit fresh action are in this case"
                    )
                    candidate = (
                        {
                            "title": "synthetic returned task",
                            "priority": 0,
                            "notes": "",
                            "tags": "",
                            "project": "",
                            "due_date": "",
                        }
                        if kind == "task"
                        else {
                            "title": "synthetic returned event",
                            "start_dt": "2099-01-01T09:00:00Z",
                            "end_dt": "2099-01-01T10:00:00Z",
                            "all_day": False,
                            "location": "",
                            "description": "",
                        }
                    )
                    self.proposal = {
                        "preview": True,
                        "kind": kind,
                        "found": True,
                        "candidate": candidate,
                        "source": {
                            "kind": "mail",
                            "label": "synthetic source",
                            "excerpt": "exact synthetic body",
                        },
                    }
                    self.evidence["timing_events"].append(
                        {
                            "phase": "synthetic-return-preview",
                            "request": body,
                            "server_request_sent": False,
                            "proposal": self.proposal,
                            "ordinal": self.preview_hits,
                        }
                    )
                    if self.preview_hits == 1:
                        self.preview_route = route
                    else:
                        route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps(self.proposal),
                        )
                    return
            if (
                request.method == "POST"
                and parsed.path == "/api/mail/make-task"
                and self.case in ["preview-newer-compose", "scope-newer-compose", "capture-normal"]
            ):
                assert not parsed.query
                body = request.post_data_json
                assert (
                    body["preview"] is True
                    and body["source"]["account_id"] == self.fixture["account_id"]
                )
                assert body["source"]["uid"] == "801" and body["source"]["folder"] == "INBOX"
                self.preview_hits += 1
                assert self.preview_hits == 1
                self.proposal = {
                    "preview": True,
                    "kind": "task",
                    "candidate": {
                        "title": "synthetic task",
                        "priority": 0,
                        "notes": "",
                        "tags": "",
                        "project": "",
                        "recurrence": "",
                        "due_date": "",
                    },
                    "source": {
                        "kind": "mail",
                        "label": "synthetic source",
                        "excerpt": "exact synthetic body",
                    },
                }
                self.evidence["timing_events"].append(
                    {
                        "phase": "synthetic-preview",
                        "request": body,
                        "server_request_sent": False,
                        "proposal": self.proposal,
                    }
                )
                if self.case == "preview-newer-compose":
                    self.preview_route = route
                else:
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(self.proposal)
                    )
                return
            route.fallback()

        self.handlers.append(handler)
        self.context.route("**/*", handler)

    def open_reader(self, page, uid):
        page.locator(f'#mail-list .mail-row[data-uid="{uid}"] .mail-open').click()
        page.locator("#mail-to-task").wait_for(state="visible")
        expected = next(row[1] for row in self.fixture["messages"] if row[0] == uid)
        assert page.locator(".mail-reader-subject").inner_text() == expected
        page.wait_for_load_state("networkidle")
        return page.locator("#mail-main > :first-child").element_handle()

    def run(self, page):
        if self.case.startswith("reader-return-"):
            return self.reader_return_case(page)
        if self.case.startswith("cancel-"):
            return self.cancel_case(page)
        if self.case.startswith("delete-"):
            return self.delete_case(page)
        return self.capture_case(page)

    def reader_return_case(self, page):
        kind = self.case.removeprefix("reader-return-")
        selector = "#mail-to-task" if kind == "task" else "#mail-to-cal"
        original = self.open_reader(page, "801")
        old_button = page.locator(selector).element_handle()
        page.locator(selector).click()
        deadline = time.monotonic() + 30
        while self.preview_route is None and time.monotonic() < deadline:
            page.wait_for_timeout(10)
        assert self.preview_route is not None and self.preview_hits == 1, (
            "driver must reach the original preview hold"
        )
        page.get_by_role("tab", name="contacts", exact=True).click()
        page.locator("#mail-view").wait_for(state="hidden")
        page.get_by_role("tab", name="mail", exact=True).click()
        page.locator("#mail-compose-btn").wait_for(state="visible")
        retired = original.evaluate("node => !node.isConnected")
        self.evidence["observations"]["reader_retired_on_return"] = retired
        if retired:
            assert page.locator("#mail-main > *").count() == 0, (
                "retired reader returns to the message list"
            )
        self.preview_route.fulfill(
            status=200, content_type="application/json", body=json.dumps(self.proposal)
        )
        self.preview_route = None
        page.wait_for_function("node => !node.disabled", arg=old_button)
        assert page.locator(".capture-overlay").count() == 0, (
            "pre-departure preview must not open after return"
        )
        if retired:
            self.open_reader(page, "801")
        page.locator(selector).click()
        page.locator(".capture-overlay").wait_for(state="visible")
        assert self.preview_hits == 2, (
            "returned or explicitly reopened reader must accept a new capture"
        )
        assert page.locator("#capture-title").input_value() == "synthetic returned " + kind
        page.locator("#capture-cancel").click()
        assert page.locator(".capture-overlay").count() == 0
        self.evidence["observations"]["fresh_returned_capture_open_close"] = kind

    def cancel_case(self, page):
        row = self.fixture["outgoing"]
        original = self.open_reader(page, "801")

        def check(request):
            query = parse_qs(urlsplit(request.url).query, keep_blank_values=True)
            scope = query.get("recovery_scope", [""])[0]
            assert set(query) == {"recovery_scope", "reserve_if_missing"}
            assert query["reserve_if_missing"] == ["true"] and re.fullmatch("[a-f0-9]{64}", scope)
            self.cancel_scope = scope
            return True

        gate = self.hold("cancel", "POST", f"/api/mail/scheduled/{row['id']}/cancel", check)
        page.locator(f"#mail-outbox-cancel-{row['id']}").click()
        gate.wait(page)
        assert gate.response.json().get("ok") is True
        owner = self.open_reader(page, "802") if self.case == "cancel-newer-reader" else original
        gate.release()
        page.wait_for_function(
            "subject => document.querySelector('#mc-subj')?.value === subject || document.querySelector('#mail-outbox-open')?.textContent === 'open canceled message'",
            arg=row["subject"],
        )
        same = owner.evaluate(
            "node => node.isConnected && node === document.querySelector('#mail-main').firstElementChild"
        )
        key = "alles-mail-outbox:" + self.cancel_scope
        pending = page.evaluate("key => sessionStorage.getItem(key)", key)
        self.evidence["observations"].update(same_reader=same, retained_pending=pending)
        if self.case == "cancel-newer-reader":
            assert same, "F1 late cancellation replaced the newer reader"
            assert pending and json.loads(pending)["request_id"] == row["id"]
            page.locator("#mail-outbox-open").click()
        page.locator("#mc-subj").wait_for(state="visible")
        assert page.locator("#mc-to").input_value() == row["to"]
        assert page.locator("#mc-subj").input_value() == row["subject"]
        assert page.locator("#mc-html").inner_html() == row["body"]
        page.wait_for_function("key => sessionStorage.getItem(key) === null", arg=key)
        self.evidence["observations"]["exact_recovery_completed"] = True

    def capture_case(self, page):
        reader = self.open_reader(page, "801")
        scopes = (
            self.hold(
                "capture-scope",
                "GET",
                "/api/tasks/draft-scope",
                lambda request: not urlsplit(request.url).query,
            )
            if self.case == "scope-newer-compose"
            else None
        )
        page.locator("#mail-to-task").click()
        if self.case == "capture-normal":
            page.locator(".capture-overlay").wait_for(state="visible")
            assert page.locator("#capture-title").input_value() == "synthetic task"
            page.locator("#capture-cancel").click()
            assert page.locator(".capture-overlay").count() == 0
            self.evidence["observations"]["normal_capture_open_close"] = True
            return
        if scopes:
            scopes.wait(page)
        else:
            deadline = time.monotonic() + 30
            while self.preview_route is None and time.monotonic() < deadline:
                page.wait_for_timeout(10)
            assert self.preview_route is not None, "driver did not reach preview hold"
        signature = self.hold(
            "compose-signature",
            "GET",
            "/api/settings",
            lambda request: not urlsplit(request.url).query,
        )
        page.locator("#mail-compose-btn").click()
        signature.wait(page)
        assert reader.evaluate("node => node.isConnected"), (
            "driver must hold compose before old reader replacement"
        )
        try:
            if scopes:
                scopes.release()
            else:
                self.preview_route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(self.proposal)
                )
                self.preview_route = None
            page.wait_for_function(
                "() => document.querySelector('#mail-to-task')?.disabled === false"
            )
            overlays = page.locator(".capture-overlay").count()
            self.evidence["observations"].update(
                overlays_after_newer_intent=overlays,
                signature_still_held=signature.route is not None,
            )
            assert overlays == 0, "F3 stale capture overlay opened after accepted compose intent"
        finally:
            signature.release()
        page.locator("#mc-subj").wait_for(state="visible")

    def delete_case(self, page):
        draft = self.fixture["draft"]
        page.on(
            "request",
            lambda request: (
                self.evidence["draft_reads"].append(request.url)
                if self.owned(request)
                and request.method == "GET"
                and urlsplit(request.url).path == "/api/mail/drafts"
                else None
            ),
        )
        page.locator('.mail-nav-item[data-filter="drafts"]').click()
        button = page.locator(f'.mail-draft-del[data-id="{draft["id"]}"]')
        button.wait_for(state="visible")
        original = button.element_handle()

        def check(request):
            query = parse_qs(urlsplit(request.url).query, keep_blank_values=True)
            return set(query) == {"expected_revision", "recovery_scope"} and all(
                len(value) == 1 and re.fullmatch("[a-f0-9]{64}", value[0])
                for value in query.values()
            )

        gate = self.hold("draft-delete", "DELETE", f"/api/mail/drafts/{draft['id']}", check)
        button.click()
        gate.wait(page)
        assert gate.response.json().get("ok") is True
        query = "subject:café"
        if self.case == "delete-search":
            page.locator("#mail-search").click()
            page.locator("#mail-search").press_sequentially(query)
            page.locator("#mail-search").press("Enter")
            page.locator('#mail-list .mail-row[data-uid="802"]').wait_for(state="visible")
        before = len(self.evidence["draft_reads"])
        gate.release()
        page.wait_for_function("node => !node.disabled", arg=original)
        after = len(self.evidence["draft_reads"])
        self.evidence["observations"].update(
            draft_reads_before_release=before,
            draft_reads_after_completion=after,
            search_value=page.locator("#mail-search").input_value(),
            list_text=page.locator("#mail-list").inner_text(),
        )
        assert after == before + (self.case == "delete-owner"), (
            "F6 stale deletion completion refreshed the newer list"
        )
        if self.case == "delete-search":
            assert page.locator("#mail-search").input_value() == query
            assert page.locator('#mail-list .mail-row[data-uid="802"]').count() == 1
        else:
            assert page.locator(".mail-draft-row").count() == 0

    def close(self):
        if self.preview_route is not None:
            self.preview_route.abort()
            self.preview_route = None
        for gate in reversed(self.holds):
            gate.close()
        for handler in self.handlers:
            self.context.unroute("**/*", handler)


def observe_input(context, evidence):
    context.expose_binding(
        "__a17ObserveMailInput", lambda source, event: evidence["input_events"].append(event)
    )
    context.add_init_script("""(() => {
      for (const type of ['input', 'blur', 'pointerdown', 'pointerup', 'click']) {
        document.addEventListener(type, event => {
          const target = event.target;
          const role = target.matches?.('.mc-chip-input') ? target.closest('.mc-chipfield')?.dataset.role : null;
          const save = target.closest?.('#mc-save');
          if (!role && !save) return;
          const fields = save ? Object.fromEntries(['to','cc','bcc'].map(name => {
            const row = document.querySelector(`.mc-chipfield[data-role="${name}"]`);
            return [name, {raw: row.querySelector('.mc-chip-input').value, committed: row.querySelector('input[type=hidden]').value}];
          })) : null;
          window.__a17ObserveMailInput({type, role, save: Boolean(save), trusted: event.isTrusted, time: event.timeStamp, fields});
        }, true);
      }
    })();""")


def basic_case(page, args, evidence):
    if args.case == "recipients-save":

        def record(request):
            if request.method == "POST" and urlsplit(request.url).path == "/api/mail/drafts":
                evidence["saved_payloads"].append(request.post_data_json)

        page.on("request", record)
        for final_role in ["to", "cc", "bcc"]:
            previous_saved_toasts = page.locator(
                "#toast-container .toast.success"
            ).element_handles()
            page.locator("#mail-compose-btn").click()
            page.locator("#mc-subj").click()
            page.locator("#mc-subj").press_sequentially("synthetic café 日本語")
            page.locator("#mc-html").click()
            page.keyboard.type("exact synthetic body")
            page.locator("#mc-add-cc").click()
            page.locator("#mc-add-bcc").click()
            for role in ["to", "cc", "bcc"]:
                if role == final_role:
                    continue
                field = page.locator(f'.mc-chipfield[data-role="{role}"] .mc-chip-input')
                field.click()
                field.press_sequentially(f"{role}@example.invalid")
                field.press("Enter")
            final_input = page.locator(f'.mc-chipfield[data-role="{final_role}"] .mc-chip-input')
            save = page.locator("#mc-save")
            save.scroll_into_view_if_needed()
            final_input.click()
            point = save.bounding_box()
            assert (
                point
                and 0 <= point["y"]
                and point["y"] + point["height"] <= page.viewport_size["height"]
            ), "save must be visible before typing"
            page.mouse.move(point["x"] + point["width"] / 2, point["y"] + point["height"] / 2)
            input_start = len(evidence["input_events"])
            payload_start = len(evidence["saved_payloads"])
            final_input.press_sequentially(f"{final_role}@example.invalid")
            save.hover()  # Re-resolve the actual button after typing; preserves input focus.
            # Consecutive real pointer events: no sleep, synthetic .click(), focus
            # change, DOM write or extra protocol round trip between down and up.
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url == args.base.rstrip("/") + "/api/mail/drafts"
                    and len(evidence["saved_payloads"]) == payload_start + 1
                    and response.request.post_data_json == evidence["saved_payloads"][-1]
                )
            ) as saved_response:
                page.mouse.down()
                page.mouse.up()
            assert saved_response.value.ok
            saved_toast = page.wait_for_function(
                """previous => Array.from(
                  document.querySelectorAll('#toast-container .toast.success')
                ).find(node => node.textContent === 'draft saved' && !previous.includes(node))""",
                arg=previous_saved_toasts,
            )
            saved_toast.as_element().wait_for_element_state("visible")
            events = evidence["input_events"][input_start:]
            click = next(
                (event for event in events if event["type"] == "click" and event["save"]), None
            )
            blur = next(
                (
                    event
                    for event in events
                    if event["type"] == "blur" and event["role"] == final_role
                ),
                None,
            )
            assert click and blur and click["trusted"] and blur["trusted"], (
                "driver did not observe trusted save/blur events"
            )
            elapsed = click["time"] - blur["time"]
            trial = {
                "final_role": final_role,
                "blur_to_click_ms": elapsed,
                "click_fields": click["fields"],
                "events": events,
            }
            evidence["recipient_trials"].append(trial)
            assert 0 <= elapsed < 160, (
                "driver missed the existing blur window; not product RED evidence"
            )
            assert click["fields"][final_role]["raw"] == f"{final_role}@example.invalid", (
                "driver did not keep pending typed text through the trusted click"
            )
            assert any(
                event["type"] == "input" and event["trusted"] and event["role"] == final_role
                for event in events
            )
            assert len(evidence["saved_payloads"]) == payload_start + 1, evidence
            payload = evidence["saved_payloads"][-1]
            for role in ["to", "cc", "bcc"]:
                assert payload[role] == f"{role}@example.invalid", payload
            assert payload["subject"] == "synthetic café 日本語"
            page.locator("#mc-close").click()
            page.locator("#mc-subj").wait_for(state="detached")
    elif args.case == "filter":
        if args.pane == "composer":
            page.locator("#mail-compose-btn").click()
            field = "#mc-subj"
        elif args.pane == "account":
            open_mail_settings(page, "accounts")
            page.locator(".mail-acct-edit").first.click()
            field = "#ma-name"
        else:
            open_mail_settings(page, "rules & vacation responder")
            field = "#mr-value" if args.pane == "rules" else "#mv-body"
        page.locator(field).click()
        page.locator(field).press("ControlOrMeta+A")
        page.locator(field).press_sequentially("exact unsaved café 日本語")
        mounted = page.locator("#mail-main > :first-child").element_handle()
        page.locator('.mail-nav-item[data-filter="drafts"]').click()
        assert mounted.evaluate(
            "node => node.isConnected && node === document.querySelector('#mail-main').firstElementChild"
        )
        assert page.locator(field).input_value() == "exact unsaved café 日本語"
    else:
        open_mail_settings(page, "accounts")
        mounted = page.locator("#mail-main > :first-child").element_handle()
        page.get_by_role("tab", name="contacts", exact=True).click()
        page.get_by_role("tab", name="mail", exact=True).click()
        page.locator("#mail-accounts-close").wait_for(state="visible")
        assert mounted.evaluate(
            "node => !node.isConnected && node !== document.querySelector('#mail-main').firstElementChild"
        )
        page.locator("#mail-accounts-close").click()
        assert page.locator("#mail-accounts-close").count() == 0


def run(args):
    from browser_gate_safety import require_server_ownership
    from playwright.sync_api import sync_playwright

    base = args.base.rstrip("/")
    parsed = urlsplit(base)
    assert parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
    assert not parsed.path and not parsed.query and not parsed.fragment
    launch_path = args.launch_receipt.resolve()
    assert launch_path.parent == Path(os.environ["ALLES_BROWSER_ARTIFACTS"]).resolve()
    launch = json.loads(launch_path.read_text())
    proof = launch["pre_browser_proof"]
    assert proof["matches_reviewed_freeze"]
    assert proof["origin"] == base and proof["run_id"] == args.run_id
    fresh = source_proof(launch["expected_source"], launch["expected_acceptance"], args.guard)
    assert fresh["matches_reviewed_freeze"] and fresh["files"] == proof["files"]
    data, database = (
        Path(os.environ["ALLES_DATA"]).resolve(),
        Path(os.environ["ALLES_DB"]).resolve(),
    )
    assert str(data) == proof["owned_root"] and str(database) == proof["database"]
    assert database.is_relative_to(data) and not data.is_relative_to(ROOT / "data")
    assert os.environ["ALLES_TEST_DATA"] == "1" and os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert (data / ".alles-test-owner").read_text().strip() == args.run_id
    fixture_path = data / "mail-compact-fixture.json"
    fixture = json.loads(fixture_path.read_text())
    assert fixture["run_id"] == args.run_id and fixture["pid"] == proof["server_pid"]
    assert fixture["guard_sha256"] == GUARD_SHA256 and digest(args.guard) == GUARD_SHA256
    assert fixture["workflow_case"] == args.case
    require_server_ownership(base, args.run_id)
    destination = launch_path.parent / args.run_id
    destination.mkdir(exist_ok=False)
    evidence = {
        "status": "running",
        "case": args.case,
        "pane": args.pane,
        "width": args.width,
        "run_id": args.run_id,
        "unexpected": [],
        "page_errors": [],
        "saved_payloads": [],
        "console": [],
        "http_errors": [],
        "request_failed": [],
        "websockets": [],
        "expected_blocks": [],
        "served_assets": [],
        "asset_errors": [],
        "input_events": [],
        "recipient_trials": [],
        "timing_events": [],
        "render_artifacts": [],
        "pre_browser_proof": proof,
        "browser_driver_pid": os.getpid(),
        "fixture_sha256": digest(fixture_path),
    }
    page = context = browser = timing = None
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
                context = browser.new_context(
                    viewport={"width": args.width, "height": 900 if args.width == 1440 else 844},
                    service_workers="block",
                    reduced_motion="reduce",
                )
                install_boundary(context, base, evidence)
                if args.case in CASES:
                    timing = TimingCases(context, base, fixture, args.case, evidence)
                    timing.install()
                observe_input(context, evidence)
                response = context.request.post(base + "/api/setup/dismiss", max_redirects=0)
                assert response.ok
                page = context.new_page()
                page.on("pageerror", lambda error: evidence["page_errors"].append(str(error)))
                page.on(
                    "console",
                    lambda message: evidence["console"].append(
                        {"type": message.type, "text": message.text, "location": message.location}
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda request: evidence["request_failed"].append(
                        {"url": request.url, "method": request.method, "failure": request.failure}
                    ),
                )
                page.on(
                    "websocket",
                    lambda socket: evidence["websockets"].append(
                        {"url": socket.url, "action": "page observed websocket"}
                    ),
                )

                def response_seen(response):
                    if response.status >= 400:
                        evidence["http_errors"].append(
                            {"url": response.url, "status": response.status}
                        )
                    parsed = urlsplit(response.url)
                    path = parsed.path.lstrip("/")
                    if (parsed.scheme, parsed.netloc) == (
                        "http",
                        urlsplit(base).netloc,
                    ) and path in ["static/js/mail.js", "static/js/capture.js"]:
                        try:
                            raw = response.body()
                            evidence["served_assets"].append(
                                {
                                    "url": response.url,
                                    "path": path,
                                    "bytes": len(raw),
                                    "status": response.status,
                                    "sha256": hashlib.sha256(raw).hexdigest(),
                                    "expected_sha256": proof["files"][path],
                                }
                            )
                        except Exception as error:
                            evidence["asset_errors"].append(
                                {"url": response.url, "error": repr(error)}
                            )

                page.on("response", response_seen)
                page.goto(base + "/?view=inbox", wait_until="networkidle")
                page.get_by_role("tab", name="mail", exact=True).click()
                page.locator("#mail-compose-btn").wait_for(state="visible")
                page.wait_for_function(
                    "() => document.querySelector('#mail-list .mail-row') !== null"
                )
                if timing:
                    timing.run(page)
                elif args.case in LOADING_CASES:
                    loading_case(page, context, base, args.case, evidence)
                else:
                    basic_case(page, args, evidence)
                assert {row["path"] for row in evidence["served_assets"]} == {
                    "static/js/mail.js",
                    "static/js/capture.js",
                }, evidence
                assert all(
                    row["status"] == 200 and row["sha256"] == row["expected_sha256"]
                    for row in evidence["served_assets"]
                ), evidence
                assert not evidence["asset_errors"], evidence
                assert not evidence["unexpected"], evidence
                assert not evidence["page_errors"], evidence
                assert not evidence["http_errors"], evidence
                assert not evidence["websockets"], evidence
                assert not [row for row in evidence["console"] if row["type"] == "error"], evidence
                expected = {row["url"] for row in evidence["expected_blocks"]}
                assert not [
                    row for row in evidence["request_failed"] if row["url"] not in expected
                ], evidence
                evidence["status"] = "passed"
            finally:
                if page:
                    try:
                        screenshot = destination / "mail.png"
                        page.screenshot(path=str(screenshot), full_page=True)
                        evidence["render_artifacts"].append(
                            {"path": str(screenshot), "sha256": digest(screenshot)}
                        )
                        evidence["final_dom"] = page.locator("#mail-view").inner_text()
                    except Exception as error:
                        evidence["artifact_error"] = repr(error)
                if timing:
                    timing.close()
                if context:
                    context.close()
                if browser:
                    browser.close()
    except BaseException as error:
        evidence.update(
            status="failed",
            error=str(error),
            error_repr=repr(error),
            error_type=type(error).__name__,
            stack=traceback.format_exc(),
        )
        raise
    finally:
        write_json(destination / "observation.json", evidence)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-fixture", action="store_true")
    parser.add_argument("--guard", type=Path, required=True)
    parser.add_argument("--base")
    parser.add_argument("--run-id")
    parser.add_argument("--launch-receipt", type=Path)
    parser.add_argument("--case", choices=BASIC_CASES + CASES + LOADING_CASES, required=True)
    parser.add_argument(
        "--pane", choices=["composer", "account", "rules", "vacation"], default="composer"
    )
    parser.add_argument("--width", type=int, choices=[1440, 390], default=1440)
    args = parser.parse_args()
    if args.width == 390 and args.case not in ["accounts-round-trip", "recipients-save"]:
        parser.error("only accounts-round-trip and recipients-save have a prepared phone profile")
    if args.serve_fixture:
        serve_fixture(args.guard, args.case)
    else:
        assert args.base and args.run_id and args.launch_receipt
        run(args)
