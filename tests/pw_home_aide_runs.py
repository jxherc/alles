"""Exact Home/Aide jobs against real disposable records; failed replies are controlled."""

import json
import os
import sys
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.database import JarvisRunEvent, JarvisWorkflow, Session, SessionLocal
    from services import jarvis_handoff
    from services.delegated_actions import ActionRequest, hash_arguments, request_action
    from services.jarvis_store import create_prompt, create_run, transition_run

    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []

    def seed(name, state="failed", question=None, structured=False, approval=False, handoff=False):
        with SessionLocal() as db:
            session = Session(name=name)
            db.add(session)
            db.flush()
            if handoff:
                job = jarvis_handoff.create_handoff(db, session, name)
            else:
                workflow = JarvisWorkflow(name=name, enabled=False, capability_ceiling='["files"]')
                db.add(workflow)
                db.flush()
                job = create_run(db, workflow, session_id=session.id)
            if state != "queued" or question or approval:
                transition_run(db, job, "running")
            prompt_id = action_id = None
            if question:
                prompt = create_prompt(
                    db,
                    job,
                    kind="choice",
                    question=question,
                    options=[] if structured else ["first", "second"],
                    questions=[
                        {
                            "id": "surface",
                            "prompt": "choose a surface",
                            "selection": "single",
                            "choices": [
                                {"id": "docs", "label": "docs"},
                                {"id": "plan", "label": "plan"},
                            ],
                            "allow_free_text": True,
                        }
                    ]
                    if structured
                    else None,
                )
                prompt_id = prompt.id
            elif approval:
                action, allowed = request_action(
                    db,
                    ActionRequest(
                        origin="aide",
                        run_id=job.id,
                        session_id=session.id,
                        scope_kind="workflow",
                        scope_id=job.workflow_id,
                        capability="files",
                        action="write_file",
                        target=str(Path(os.environ["ALLES_DATA"]) / "approval-fixture.txt"),
                        data_summary="owned fixture content",
                        privacy_effect="changes one selected file",
                        cost="none",
                        arguments_hash=hash_arguments({"content": "owned fixture"}),
                        mutating=True,
                    ),
                    force_approval=True,
                )
                assert not allowed
                action_id = action.id
            elif state != "queued":
                transition_run(
                    db, job, state, safe_error="owned job failed" if state == "failed" else ""
                )
            db.commit()
            return {"id": job.id, "session": session.id, "prompt": prompt_id, "action": action_id}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        api = pw.request.new_context(base_url=base)
        assert api.post("/api/setup/dismiss").ok
        for host, width in [
            ("127.0.0.1", 1440),
            ("127.0.0.1", 390),
            ("localhost", 1440),
            ("localhost", 390),
        ]:
            home = f"http://{host}:{os.environ['PORT']}"
            aide = home if host == "127.0.0.1" else f"http://aide.localhost:{os.environ['PORT']}"
            profile = str(width) if host == "127.0.0.1" else f"localhost-{width}"
            context = browser.new_context(
                viewport={"width": width, "height": 900},
                service_workers="block",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, console = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console", lambda item: console.append(item.text) if item.type == "error" else None
            )
            panel = page.locator(".aide-run-detail")

            def record(name):
                rows.append(
                    {"scenario_id": "home.aide." + name, "profile": profile, "status": "passed"}
                )
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

            def open_job(job):
                page.goto(
                    aide + "/?view=chat&record_view=chat&record=" + job["id"],
                    wait_until="networkidle",
                )
                expect(panel).to_have_attribute("data-run-id", job["id"])
                expect(panel.locator("[data-run-state]")).not_to_be_empty()

            def lose_reply(route):
                response = route.fetch()
                assert response.ok, response.text()
                route.fulfill(status=503, json={"detail": "synthetic lost reply"})

            try:
                failed = seed("owned exact job " + profile)
                page.goto(home + "/?view=today", wait_until="networkidle")
                page.locator(f'[data-run="{failed["id"]}"]').focus()
                page.keyboard.press("Enter")
                expect(panel).to_have_attribute("data-run-id", failed["id"])
                expect(panel.locator("[data-run-state]")).to_have_text("failed")
                expect(panel.locator(".aide-run-result")).to_contain_text("owned job failed")
                assert failed["id"] in page.url
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                record("home-opens-exact-job")
                page.reload(wait_until="networkidle")
                expect(panel).to_have_attribute("data-run-id", failed["id"])
                expect(panel.locator("[data-run-state]")).to_have_text("failed")
                page.go_back(wait_until="networkidle")
                expect(page.locator("#today-view")).to_be_visible()
                expect(panel).to_have_count(0)
                page.go_forward(wait_until="networkidle")
                expect(panel).to_have_attribute("data-run-id", failed["id"])
                expect(panel.locator("[data-run-state]")).to_have_text("failed")
                record("reload-back-and-forward-preserve-job")
                panel.get_by_role("button", name="close", exact=True).focus()
                page.keyboard.press("Shift+Tab")
                assert panel.evaluate("node => node.contains(document.activeElement)")
                page.keyboard.press("Escape")
                expect(panel).to_have_count(0)
                expect(page.locator("#composer-ta")).to_be_focused()
                assert "record=" not in page.url
                record("keyboard-close-restores-chat")

                def fail_read(route):
                    route.fulfill(status=503, json={"detail": "synthetic job read unavailable"})

                page.route(aide + "/api/jarvis/runs/" + failed["id"], fail_read)
                page.goto(
                    aide + "/?view=chat&record_view=chat&record=" + failed["id"],
                    wait_until="networkidle",
                )
                expect(panel.locator(".aide-run-status")).to_contain_text(
                    "synthetic job read unavailable"
                )
                page.unroute(aide + "/api/jarvis/runs/" + failed["id"], fail_read)
                panel.get_by_role("button", name="refresh", exact=True).click()
                expect(panel.locator("[data-run-state]")).to_have_text("failed")
                record("failed-read-recovers-in-place")
                page.goto(
                    aide + "/?view=chat&record_view=chat&record=missing-owned-job",
                    wait_until="networkidle",
                )
                expect(panel.locator(".aide-run-status")).to_have_text(
                    "this job is no longer available"
                )
                expect(panel.get_by_role("button", name="retry job", exact=True)).to_be_hidden()
                record("missing-job-is-explicit")

                queued = seed("cancel job " + profile, state="queued")
                open_job(queued)
                page.route(aide + f"/api/jarvis/runs/{queued['id']}/cancel", lose_reply)
                panel.get_by_role("button", name="cancel job", exact=True).click()
                expect(panel.locator("[data-run-state]")).to_have_text("cancelled")
                assert api.get("/api/jarvis/runs/" + queued["id"]).json()["state"] == "cancelled"
                page.unroute(aide + f"/api/jarvis/runs/{queued['id']}/cancel", lose_reply)
                record("lost-cancel-reply-checks-current-state")

                choice = seed("choice " + profile, question="which owned option?")
                open_job(choice)
                card = panel.locator(".aide-question-card")
                expect(card.get_by_role("heading", name="which owned option?")).to_have_count(1)
                card.get_by_role("radio", name="first", exact=True).focus()
                page.keyboard.press("Space")
                answer_url = aide + f"/api/jarvis/prompts/{choice['prompt']}/answer"
                page.route(answer_url, fail_read)
                card.get_by_role("button", name="continue", exact=True).click()
                expect(card.locator("[data-question-status]")).to_have_text(
                    "could not save - try again"
                )
                expect(card.get_by_role("button", name="continue", exact=True)).to_be_focused()
                expect(card.get_by_role("radio", name="first", exact=True)).to_have_attribute(
                    "aria-checked", "true"
                )
                page.unroute(answer_url, fail_read)
                page.route(answer_url, lose_reply)
                card.get_by_role("button", name="continue", exact=True).click()
                expect(panel.locator("[data-run-state]")).to_have_text("queued")
                page.unroute(answer_url, lose_reply)
                expect(panel.locator(".aide-run-status")).to_be_focused()
                expect(panel.locator(".aide-run-status")).to_have_text("answer saved")
                page.screenshot(path=str(out / f"{profile}-answer.png"), full_page=True)
                saved = api.get("/api/jarvis/runs/" + choice["id"]).json()
                assert (
                    next(p for p in saved["prompts"] if p["id"] == choice["prompt"])["answer"]
                    == "first"
                )
                assert (
                    len([event for event in saved["events"] if event["kind"] == "choice_answered"])
                    == 1
                )
                record("choice-keeps-selection-and-confirms-lost-reply")

                structured = seed(
                    "structured " + profile, question="choose this job's scope", structured=True
                )
                open_job(structured)
                card = panel.locator(".aide-question-card")
                card.get_by_role("radio", name="docs", exact=True).click()
                card.locator("textarea").fill("keep this exact input 中文")
                panel.get_by_role("button", name="refresh", exact=True).click()
                expect(panel.locator(".aide-run-status")).to_have_text("")
                expect(card.locator("textarea")).to_have_value("keep this exact input 中文")
                expect(card.get_by_role("radio", name="docs", exact=True)).to_have_attribute(
                    "aria-checked", "true"
                )
                card.get_by_role("button", name="continue", exact=True).click()
                expect(panel.locator("[data-run-state]")).to_have_text("queued")
                answer = next(
                    p
                    for p in api.get("/api/jarvis/runs/" + structured["id"]).json()["prompts"]
                    if p["id"] == structured["prompt"]
                )["answer_data"]
                assert answer == {
                    "cancelled": False,
                    "answers": {
                        "surface": {"selected": ["docs"], "free_text": "keep this exact input 中文"}
                    },
                }
                record("structured-answer-survives-refresh")

                cancelled = seed(
                    "cancel question " + profile, question="choose or cancel", structured=True
                )
                open_job(cancelled)
                panel.locator(".aide-question-card").get_by_role(
                    "button", name="cancel", exact=True
                ).click()
                expect(panel.locator("[data-run-state]")).to_have_text("queued")
                expect(panel.locator(".aide-run-status")).to_have_text("question cancelled")
                expect(panel.locator(".aide-run-status")).to_be_focused()
                saved_prompt = next(
                    item
                    for item in api.get("/api/jarvis/runs/" + cancelled["id"]).json()["prompts"]
                    if item["id"] == cancelled["prompt"]
                )
                assert saved_prompt["answer_data"] == {"cancelled": True, "answers": {}}
                record("structured-question-cancel-is-durable")

                moved = seed("moved answer focus " + profile, question="choose once")
                open_job(moved)
                card = panel.locator(".aide-question-card")
                card.get_by_role("radio", name="first", exact=True).click()
                held = []

                def hold(route):
                    held.append((route, route.fetch()))

                moved_url = aide + f"/api/jarvis/prompts/{moved['prompt']}/answer"
                page.route(moved_url, hold)
                card.get_by_role("button", name="continue", exact=True).click()
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                assert len(held) == 1
                panel.get_by_role("button", name="close", exact=True).focus()
                route, response = held.pop()
                route.fulfill(response=response)
                page.unroute(moved_url, hold)
                expect(panel.locator("[data-run-state]")).to_have_text("queued")
                expect(panel.get_by_role("button", name="close", exact=True)).to_be_focused()
                record("answer-preserves-focus-moved-elsewhere")

                open_job(failed)
                held = []
                read_url = aide + "/api/jarvis/runs/" + failed["id"]
                page.route(read_url, hold)
                panel.get_by_role("button", name="refresh", exact=True).click()
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                assert len(held) == 1
                panel.get_by_role("button", name="close", exact=True).click()
                route, response = held.pop()
                route.fulfill(response=response)
                page.unroute(read_url, hold)
                page.wait_for_load_state("networkidle")
                expect(panel).to_have_count(0)
                expect(page.locator("#composer-ta")).to_be_focused()
                record("late-read-cannot-reopen-closed-job")

                for allow in [False, True]:
                    approval = seed(f"approval {allow} {profile}", approval=True)
                    open_job(approval)
                    expect(panel.locator("dl")).to_contain_text("changes one selected file")
                    expect(panel.locator("dl")).to_contain_text("owned fixture content")
                    page.screenshot(path=str(out / f"{profile}-approval.png"), full_page=True)
                    decision_url = aide + f"/api/delegation/actions/{approval['action']}/decision"
                    page.route(decision_url, lose_reply)
                    panel.get_by_role(
                        "button", name="allow this action" if allow else "deny", exact=True
                    ).click()
                    expect(panel.locator("[data-run-state]")).to_have_text(
                        "queued" if allow else "paused"
                    )
                    page.unroute(decision_url, lose_reply)
                    action = api.get("/api/delegation/actions/" + approval["action"]).json()
                    assert action["state"] == ("approved" if allow else "denied")
                    assert not Path(action["target"]).exists()
                    record("exact-approval-" + ("allow" if allow else "deny"))

                challenged = seed("owner challenge " + profile, approval=True)
                open_job(challenged)
                decision_url = aide + f"/api/delegation/actions/{challenged['action']}/decision"

                def challenge(route):
                    route.fulfill(status=403, json={"code": "recent_auth_required"})

                def owner_enabled(route):
                    route.fulfill(json={"enabled": True})

                page.route(decision_url, challenge)
                page.route(aide + "/api/auth/me", owner_enabled)
                panel.get_by_role("button", name="allow this action", exact=True).click()
                expect(page.locator(".dialog-input[type=password]")).to_be_visible()
                page.locator("[data-dialog-cancel]").click()
                expect(panel.locator(".aide-run-status")).to_have_text(
                    "owner confirmation cancelled"
                )
                assert (
                    api.get("/api/delegation/actions/" + challenged["action"]).json()["state"]
                    == "pending"
                )
                page.unroute(decision_url, challenge)
                page.unroute(aide + "/api/auth/me", owner_enabled)
                record("owner-challenge-cancel-keeps-action-pending")

                stale = seed("stale decision " + profile, approval=True)
                open_job(stale)
                expect(
                    panel.get_by_role("button", name="allow this action", exact=True)
                ).to_be_visible()
                action = api.get("/api/delegation/actions/" + stale["action"]).json()
                denied = api.post(
                    "/api/delegation/actions/" + stale["action"] + "/decision",
                    data={"allow": False, "exact_hash": action["exact_hash"]},
                )
                assert denied.ok, denied.text()
                panel.get_by_role("button", name="allow this action", exact=True).click()
                expect(panel.locator(".aide-run-status")).to_contain_text(
                    "approval was not confirmed"
                )
                assert (
                    api.get("/api/delegation/actions/" + stale["action"]).json()["state"]
                    == "denied"
                )
                panel.get_by_role("button", name="refresh", exact=True).click()
                expect(panel.locator("[data-run-state]")).to_have_text("paused")
                expect(
                    panel.get_by_role("button", name="allow this action", exact=True)
                ).to_have_count(0)
                record("stale-approval-cannot-reverse-a-decision")

                uncertain = seed("uncertain " + profile, state="uncertain")
                open_job(uncertain)
                expect(panel.locator(".aide-run-result")).to_contain_text("outcome is unknown")
                expect(panel.get_by_role("button", name="retry job", exact=True)).to_be_hidden()
                record("uncertain-job-cannot-retry")

                late_retry = seed("late retry " + profile, handoff=True)
                open_job(late_retry)
                held = []

                def hold_retry(route):
                    response = route.fetch()
                    assert response.ok, response.text()
                    held.append((route, response))

                late_url = aide + f"/api/jarvis/runs/{late_retry['id']}/retry"
                page.evaluate(
                    """url => {
                    window.__retryReplyHandled = false;
                    const original = window.fetch;
                    window.__retryOriginalFetch = original;
                    window.fetch = async (...args) => {
                        const response = await original(...args);
                        if (String(args[0]).endsWith(url)) {
                            const parse = response.json.bind(response);
                            response.json = async () => {
                                const data = await parse();
                                setTimeout(() => { window.__retryReplyHandled = true; }, 0);
                                return data;
                            };
                        }
                        return response;
                    };
                }""",
                    f"/api/jarvis/runs/{late_retry['id']}/retry",
                )
                page.route(late_url, hold_retry)
                panel.get_by_role("button", name="retry job", exact=True).click()
                deadline = time.monotonic() + 5
                while not held and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                assert len(held) == 1
                route, response = held.pop()
                late_child = response.json()["id"]
                panel.get_by_role("button", name="close", exact=True).click()
                route.fulfill(response=response)
                page.wait_for_function("window.__retryReplyHandled === true")
                page.evaluate("() => { window.fetch = window.__retryOriginalFetch; }")
                page.unroute(late_url, hold_retry)
                page.wait_for_load_state("networkidle")
                expect(panel).to_have_count(0)
                open_job(late_retry)
                panel.get_by_role("button", name="retry job", exact=True).click()
                expect(panel).to_have_attribute("data-run-id", late_child)
                with SessionLocal() as db:
                    children = [
                        event.run_id
                        for event in db.query(JarvisRunEvent).filter_by(kind="handoff_requested")
                        if json.loads(event.data).get("previous_run_id") == late_retry["id"]
                    ]
                    assert children == [late_child], children
                record("closed-retry-keeps-one-child")

                denied_navigation = seed("denied retry navigation " + profile, handoff=True)
                open_job(denied_navigation)
                page.evaluate(
                    "() => { window.__realOpenRecord = window._openRecord; window._openRecord = async () => false; }"
                )
                with page.expect_response(
                    lambda r: r.url.endswith(f"/runs/{denied_navigation['id']}/retry")
                ) as response:
                    panel.get_by_role("button", name="retry job", exact=True).click()
                saved_child = response.value.json()["id"]
                expect(panel.locator(".aide-run-status")).to_contain_text(
                    "retry saved; could not open the job"
                )
                page.wait_for_load_state("networkidle")
                page.evaluate("() => { window._openRecord = window.__realOpenRecord; }")
                panel.get_by_role("button", name="retry job", exact=True).click()
                expect(panel).to_have_attribute("data-run-id", saved_child)
                with SessionLocal() as db:
                    children = [
                        event.run_id
                        for event in db.query(JarvisRunEvent).filter_by(kind="handoff_requested")
                        if json.loads(event.data).get("previous_run_id") == denied_navigation["id"]
                    ]
                    assert children == [saved_child], children
                record("failed-child-navigation-keeps-one-child")

                moved_navigation = seed("moved retry navigation " + profile, handoff=True)
                open_job(moved_navigation)
                page.evaluate("""() => {
                    const original = window._openRecord;
                    window._openRecord = async (...args) => {
                        const opened = await original(...args);
                        await new Promise(resolve => { window.__finishChildNavigation = resolve; });
                        setTimeout(() => { window.__childNavigationHandled = true; }, 0);
                        return opened;
                    };
                }""")
                with page.expect_response(
                    lambda r: r.url.endswith(f"/runs/{moved_navigation['id']}/retry")
                ) as response:
                    panel.get_by_role("button", name="retry job", exact=True).click()
                moved_child = response.value.json()["id"]
                expect(panel).to_have_attribute("data-run-id", moved_child)
                page.wait_for_function("typeof window.__finishChildNavigation === 'function'")
                panel.get_by_role("button", name="close", exact=True).click()
                page.evaluate("() => { window.__finishChildNavigation(); }")
                page.wait_for_function("window.__childNavigationHandled === true")
                open_job(moved_navigation)
                panel.get_by_role("button", name="retry job", exact=True).click()
                expect(panel).to_have_attribute("data-run-id", moved_child)
                with SessionLocal() as db:
                    children = [
                        event.run_id
                        for event in db.query(JarvisRunEvent).filter_by(kind="handoff_requested")
                        if json.loads(event.data).get("previous_run_id") == moved_navigation["id"]
                    ]
                    assert children == [moved_child], children
                record("superseded-child-navigation-keeps-one-child")

                retry_job = seed("retry " + profile, handoff=True)
                open_job(retry_job)
                saved_retries = []

                def lose_retry(route):
                    response = route.fetch()
                    assert response.ok, response.text()
                    saved_retries.append(response.json())
                    route.fulfill(status=503, json={"detail": "synthetic lost retry response"})

                def fail_child(route):
                    if saved_retries and route.request.url.endswith("/" + saved_retries[-1]["id"]):
                        route.fulfill(
                            status=503, json={"detail": "synthetic confirmation unavailable"}
                        )
                    else:
                        route.continue_()

                page.route(aide + "/api/jarvis/runs/*", fail_child)
                retry_url = aide + f"/api/jarvis/runs/{retry_job['id']}/retry"
                page.route(retry_url, lose_retry)
                panel.get_by_role("button", name="retry job", exact=True).click()
                expect(panel.locator(".aide-run-status")).to_contain_text(
                    "could not confirm the retry"
                )
                assert len(saved_retries) == 1
                child_id = saved_retries[0]["id"]
                page.unroute(retry_url, lose_retry)
                page.unroute(aide + "/api/jarvis/runs/*", fail_child)
                page.reload(wait_until="networkidle")
                panel.get_by_role("button", name="retry job", exact=True).click()
                expect(panel).to_have_attribute("data-run-id", child_id)
                expect(panel.locator("[data-run-state]")).not_to_be_empty()
                with SessionLocal() as db:
                    events = db.query(JarvisRunEvent).filter_by(kind="handoff_requested").all()
                    children = [
                        event.run_id
                        for event in events
                        if json.loads(event.data).get("previous_run_id") == retry_job["id"]
                    ]
                    assert children == [child_id], children
                record("lost-retry-reload-creates-one-child")
                panel.get_by_role("button", name="open conversation", exact=True).click()
                expect(panel).to_have_count(0)
                assert retry_job["session"] in page.url
                record("open-exact-conversation")
                assert not errors, errors
                assert all(
                    any(code in item for code in ["503", "404", "400", "403"]) for item in console
                ), console
                record("console")
            except Exception as error:
                rows.append(
                    {
                        "scenario_id": "home.aide.failure",
                        "profile": profile,
                        "status": "failed",
                        "error": str(error),
                        "page_errors": errors,
                        "console": console,
                    }
                )
            finally:
                page.screenshot(path=str(out / f"{profile}-final.png"), full_page=True)
                context.close()
                (out / "scenarios.json").write_text(json.dumps(rows, indent=2))
        api.dispose()
        browser.close()
    raise SystemExit(any(row["status"] != "passed" for row in rows))


if __name__ == "__main__":
    run()
