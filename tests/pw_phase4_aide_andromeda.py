"""Phase 4 Aide + Andromeda browser gate against throwaway ALLES_DATA."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import Page, Route

from core.database import ModelEndpoint, SessionLocal
from core.settings import save_settings

PORT = os.environ.get("PHASE4_PORT", os.environ.get("PORT", "8924"))
APEX = f"http://localhost:{PORT}"
AIDE = f"http://aide.localhost:{PORT}"
SERVER = f"http://server.localhost:{PORT}"
AUTH_PASSWORD = os.environ.get("PHASE4_AUTH_PASSWORD", "")
AUTH_STORAGE_STATE: dict | None = None


def new_context(browser, **options):
    if AUTH_STORAGE_STATE:
        options["storage_state"] = AUTH_STORAGE_STATE
    return browser.new_context(**options)


def seed_model() -> None:
    with SessionLocal() as db:
        endpoint = db.query(ModelEndpoint).filter_by(name="phase 4 local fixture").first()
        if not endpoint:
            endpoint = ModelEndpoint(
                name="phase 4 local fixture",
                base_url="http://127.0.0.1:11434/v1",
                cached_models='["phase4-local"]',
                enabled=True,
            )
            db.add(endpoint)
            db.commit()
            db.refresh(endpoint)
        endpoint_id = endpoint.id
    save_settings(
        {
            "model_roles": {
                "aide_chat": {"endpoint_id": endpoint_id, "model": "phase4-local"},
                "andromeda_answer": {"endpoint_id": endpoint_id, "model": "phase4-local"},
                "andromeda_verifier": {"endpoint_id": endpoint_id, "model": "phase4-local"},
                "jarvis": {"endpoint_id": endpoint_id, "model": "phase4-local"},
            },
            "andromeda_normal_results": True,
            "andromeda_overview": True,
            "andromeda_model_band": "standard",
        }
    )


def wire_errors(page: Page, errors: list[str], server_errors: list[str]) -> None:
    page.on(
        "console",
        lambda message: (
            errors.append(message.text)
            if message.type == "error" and "favicon" not in message.text
            else None
        ),
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            server_errors.append(f"{response.status} {response.url}")
            if response.status >= 500
            else None
        ),
    )


def authenticate_if_needed(page: Page, target: str = APEX) -> bool:
    if not AUTH_PASSWORD:
        page.goto(target, wait_until="domcontentloaded")
        return True
    page.goto(target, wait_until="domcontentloaded")
    page.wait_for_function(
        "document.querySelector('#login-screen')?.offsetParent !== null || !document.body.classList.contains('preboot')",
        timeout=20_000,
    )
    if not page.locator("#login-screen").is_visible():
        return page.locator("body.login-mode").count() == 0
    page.locator("#login-pw").fill(AUTH_PASSWORD)
    page.locator("#login-submit").click()
    page.wait_for_selector("#login-screen", state="hidden", timeout=20_000)
    page.wait_for_function(
        "!document.body.classList.contains('preboot') && !document.body.classList.contains('login-mode')",
        timeout=20_000,
    )
    return page.locator("body.login-mode").count() == 0


def mock_andromeda(route: Route, saved: list[dict]) -> None:
    request = route.request
    path = request.url.split("/api/andromeda", 1)[-1].split("?", 1)[0]
    if path == "/search":
        body = request.post_data_json
        query = body.get("query", "")
        no_ai = any(token.lower() == "!ai" for token in query.split())
        clean = " ".join(token for token in query.split() if token.lower() != "!ai")
        if "fail" in clean:
            payload = {
                "query": clean,
                "used_no_ai": no_ai,
                "normal_results_enabled": True,
                "overview_requested": not no_ai,
                "overview_seed": [],
                "status": "error",
                "results": [],
                "provider": "fixture",
                "elapsed_ms": 8,
                "error": "provider timeout",
                "failure_type": "provider_timeout",
                "attempted_sources": ["fixture"],
            }
        else:
            results = [
                {
                    "rank": 1,
                    "title": "official phase 4 docs",
                    "url": "https://docs.example.test/releases/4.0",
                    "snippet": "Version 4.0 was released with grounded citations.",
                    "publisher": "docs.example.test",
                    "source_kind": "official docs",
                    "source_quality": 1,
                    "provider": "fixture",
                    "elapsed_ms": 8,
                },
                {
                    "rank": 2,
                    "title": "source repository",
                    "url": "https://github.com/example/project/releases",
                    "snippet": "Release details and source history.",
                    "publisher": "github.com",
                    "source_kind": "release notes",
                    "source_quality": 2,
                    "provider": "fixture",
                    "elapsed_ms": 8,
                },
            ]
            payload = {
                "query": clean,
                "used_no_ai": no_ai,
                "normal_results_enabled": body.get("normal_results", True),
                "overview_requested": body.get("overview", True) and not no_ai,
                "overview_seed": results,
                "status": "ready" if body.get("normal_results", True) else "disabled",
                "results": results if body.get("normal_results", True) else [],
                "provider": "fixture",
                "elapsed_ms": 8,
                "error": "",
            }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        return
    if path == "/overview/preview":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "endpoint_id": "fixture-local",
                    "endpoint": "local fixture",
                    "model": "phase4-local",
                    "privacy_class": "local",
                    "reason": "role_default",
                    "price_metadata": {},
                }
            ),
        )
        return
    if path == "/overview":
        quote = "Version 4.0 was released with grounded citations."
        claim = {
            "text": "Version 4.0 was released with grounded citations.",
            "supported": True,
            "citations": [
                {
                    "source_id": "s1",
                    "quote": quote,
                    "url": "https://docs.example.test/releases/4.0",
                    "title": "official phase 4 docs",
                    "source_kind": "official docs",
                    "source_quality": 1,
                }
            ],
        }
        evidence = {
            "id": "s1",
            "title": "official phase 4 docs",
            "url": "https://docs.example.test/releases/4.0",
            "source_kind": "official docs",
            "source_quality": 1,
            "passages": [quote],
        }
        final = {
            "status": "ready",
            "summary": claim["text"],
            "claims": [claim],
            "rejected_claims": 0,
            "freshness": {"checked_on": "2026-07-12", "newest_version_seen": "4.0"},
        }
        stream = "".join(
            [
                f"data: {json.dumps({'type': 'evidence', 'sources': [evidence]})}\n\n",
                f"data: {json.dumps({'type': 'claim', 'claim': claim})}\n\n",
                f"data: {json.dumps({'type': 'overview', 'overview': final, 'elapsed_ms': 15})}\n\n",
                "data: [DONE]\n\n",
            ]
        )
        route.fulfill(status=200, content_type="text/event-stream", body=stream)
        return
    if path == "/saved" and request.method == "GET":
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "searches": [
                        {k: item[k] for k in ("id", "query", "checked_at", "created_at")}
                        for item in saved
                    ]
                }
            ),
        )
        return
    if path == "/saved" and request.method == "POST":
        body = request.post_data_json
        item = {
            "id": "saved-browser",
            "query": body["query"],
            "checked_at": "2026-07-12T00:00:00",
            "created_at": "2026-07-12T00:00:00",
            **body,
        }
        saved[:] = [item]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(item))
        return
    if path == "/saved/saved-browser":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(saved[0]))
        return
    route.continue_()


def mock_jarvis(route: Route, state: dict, handoffs: list[dict]) -> None:
    url = route.request.url
    preview = {
        "endpoint_id": "fixture-local",
        "endpoint": "local fixture",
        "model": "phase4-local",
        "privacy_class": "local",
    }
    if "/handoffs/preview" in url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(preview))
    elif url.endswith("/api/jarvis/handoffs"):
        handoffs.append(route.request.post_data_json)
        state.update({"id": "run-browser", "state": "queued"})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"id": "run-browser", "state": "queued", "result_summary": ""}),
        )
    elif "/api/jarvis/runs?" in url:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "id": state.get("id", "run-browser"),
                        "state": state.get("state", "succeeded"),
                        "result_summary": "reloaded Jarvis task",
                    }
                ]
            ),
        )
    elif url.endswith("/cancel"):
        state["state"] = "cancelled"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"id": state["id"], "state": "cancelled", "result_summary": ""}),
        )
    elif url.endswith("/retry"):
        state.update({"id": "run-browser-retry", "state": "succeeded"})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"id": state["id"], "state": "queued", "result_summary": ""}),
        )
    elif "/api/jarvis/runs/" in url:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": state.get("id", "run-browser"),
                    "state": state.get("state", "queued"),
                    "result_summary": "done" if state.get("state") == "succeeded" else "",
                }
            ),
        )
    else:
        route.continue_()


def mock_reloaded_agent(route: Route) -> None:
    if route.request.url.endswith("/sources"):
        body = {"files": ["project/a.md"], "urls": [], "searches": [], "commands": []}
    elif route.request.url.endswith("/revert"):
        body = {"restored": 1}
    else:
        route.continue_()
        return
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def check_aide(browser, viewport: dict, mobile: bool, results: dict) -> None:
    label = "mobile" if mobile else "desktop"
    context = new_context(
        browser,
        viewport=viewport,
        is_mobile=mobile,
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    errors, server_errors = [], []
    wire_errors(page, errors, server_errors)
    handoffs: list[dict] = []
    jarvis_state = {"id": "run-browser", "state": "queued"}
    page.route("**/api/jarvis/**", lambda route: mock_jarvis(route, jarvis_state, handoffs))
    page.route("**/api/agent/runs/reload-run/**", mock_reloaded_agent)
    results[f"{label}_aide_authenticated_gate"] = authenticate_if_needed(page, AIDE)
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    page.wait_for_selector("#chat", state="visible", timeout=20_000)
    results[f"{label}_chat_jarvis_selector"] = (
        page.locator("#mode-chat").inner_text() == "chat"
        and page.locator("#mode-jarvis").inner_text() == "jarvis"
    )
    results[f"{label}_aide_labels"] = (
        page.locator("#composer-ta").get_attribute("aria-label") == "message Aide"
        and page.locator("#more-tools-btn").get_attribute("aria-label") == "more tools"
        and page.locator(".mode-toggle").get_attribute("aria-label") == "Aide mode"
    )
    results[f"{label}_answer_only_option"] = (
        page.locator('#chat-behavior-select option[value="answer_only"]').count() == 1
    )
    results[f"{label}_old_modes_absent"] = (
        page.locator("#mode-research").count() == 0 and page.locator("#mode-rag").count() == 0
    )
    page.locator("#composer-ta").fill("draft survives mode switching")
    page.locator("#mode-jarvis").click()
    page.locator("#mode-chat").click()
    results[f"{label}_mode_switch_keeps_draft"] = (
        page.locator("#composer-ta").input_value() == "draft survives mode switching"
    )
    page.locator("#composer-ta").fill("")
    results[f"{label}_compare_not_sidebar"] = (
        page.locator('.sidebar .nav-item[data-view="compare"]').count() == 0
    )
    page.locator("#more-tools-btn").click()
    results[f"{label}_compare_is_action"] = page.get_by_text(
        "compare models", exact=True
    ).is_visible()
    page.keyboard.press("Escape")
    page.evaluate("window._openSettings('memory')")
    page.wait_for_selector("#s-pane-memory.active", timeout=10_000)
    results[f"{label}_memory_pause"] = page.locator("#mem-pause-btn").is_visible()
    page.keyboard.press("Escape")
    page.locator("#incognito-btn").click()
    results[f"{label}_incognito_state"] = page.locator("#incognito-bar").is_visible()
    page.locator("#incognito-exit").click()
    page.locator("#jump-latest").evaluate("button => { button.hidden = false; }")
    page.locator("#jump-latest").focus()
    page.keyboard.press("Enter")
    results[f"{label}_jump_latest_keyboard"] = page.locator("#jump-latest").is_hidden()
    page.evaluate(
        """async () => {
          const { appendAiMsg, showMessages } = await import('/static/js/sessions.js');
          showMessages();
          appendAiMsg(
            'finished work',
            '',
            [{name: 'edit_file', args: {path: 'project/a.md'}, diff: '-old\\n+new'}],
            {},
            'reload-run',
          );
        }"""
    )
    reloaded = page.locator(".agent-steps").last
    results[f"{label}_reload_run_controls"] = (
        reloaded.locator('[data-agent-sources="reload-run"]').count() == 1
        and reloaded.locator('[data-agent-revert="reload-run"]').count() == 1
    )
    reloaded.locator('[data-agent-sources="reload-run"]').click()
    page.wait_for_selector(".agent-sources")
    reloaded.locator('[data-agent-revert="reload-run"]').click()
    page.wait_for_function(
        "document.querySelector('[data-agent-revert=\"reload-run\"]')?.textContent.includes('reverted 1')"
    )
    results[f"{label}_reload_sources_revert_work"] = (
        "project/a.md" in reloaded.locator(".agent-sources").inner_text()
    )
    page.locator("#mode-jarvis").click()
    page.evaluate(
        """async () => {
          const endpoints = await fetch('/api/models').then(response => response.json());
          const endpoint = endpoints.find(value => (value.models || []).includes('phase4-local'));
          if (endpoint) (await import('/static/js/models.js?v=210')).selectModel(endpoint.id, 'phase4-local');
        }"""
    )
    page.locator("#composer-ta").fill("check this in the background")
    page.locator("#send-btn").click()
    try:
        page.wait_for_selector(".jarvis-handoff-card", timeout=10_000)
    except Exception:
        print(
            label,
            "hidden handoff ancestry",
            page.locator(".jarvis-handoff-card").evaluate(
                """card => {
                  const rows = [];
                  for (let node = card; node; node = node.parentElement) {
                    const style = getComputedStyle(node);
                    rows.push({
                      node: node.id || node.className || node.tagName,
                      display: style.display,
                      visibility: style.visibility,
                      opacity: style.opacity,
                      hidden: node.hidden,
                    });
                  }
                  return rows;
                }"""
            ),
        )
        raise
    page.wait_for_selector('[data-jarvis-action="cancel"]', timeout=10_000)
    results[f"{label}_durable_handoff_card"] = (
        "jarvis" in page.locator(".jarvis-handoff-card").inner_text().lower()
        and page.locator('[data-jarvis-action="cancel"]').is_visible()
    )
    results[f"{label}_handoff_payload"] = bool(
        handoffs
        and handoffs[-1].get("request") == "check this in the background"
        and handoffs[-1].get("session_id")
        and handoffs[-1].get("endpoint_override")
        and handoffs[-1].get("model_override") == "phase4-local"
    )
    if not results[f"{label}_handoff_payload"]:
        print(label, "handoff payload", handoffs[-1] if handoffs else None)
    page.locator('[data-jarvis-action="cancel"]').click()
    page.wait_for_selector('[data-jarvis-action="retry"]', timeout=10_000)
    page.locator('[data-jarvis-action="retry"]').click()
    page.wait_for_function(
        "document.querySelector('.jarvis-card-state')?.textContent.includes('succeeded')",
        timeout=10_000,
    )
    results[f"{label}_handoff_cancel_retry"] = (
        "succeeded" in page.locator(".jarvis-handoff-card").inner_text().lower()
    )
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#chat", state="visible", timeout=20_000)
    if mobile and page.locator("body.sidebar-hidden").count():
        page.locator("#sidebar-toggle-btn").click()
    page.wait_for_selector('.aide-run[data-state="succeeded"]', timeout=20_000)
    results[f"{label}_handoff_survives_reload"] = (
        "reloaded jarvis task"
        in page.locator('.aide-run[data-state="succeeded"]').inner_text().lower()
    )
    if mobile and not page.locator("body.sidebar-hidden").count():
        page.mouse.click(viewport["width"] - 8, viewport["height"] / 2)
    results[f"{label}_reduced_motion"] = page.evaluate(
        "matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    overflow = page.evaluate(
        "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth"
    )
    results[f"{label}_fits"] = overflow <= 2
    results[f"{label}_zero_console_errors"] = not errors
    results[f"{label}_zero_server_errors"] = not server_errors
    if errors:
        print(label, "Aide console errors", errors[:10])
    if server_errors:
        print(label, "Aide server errors", server_errors[:10])
    context.close()


def check_andromeda(browser, viewport: dict, mobile: bool, results: dict) -> None:
    label = "mobile" if mobile else "desktop"
    context = new_context(
        browser,
        viewport=viewport,
        is_mobile=mobile,
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    errors, server_errors, saved = [], [], []
    pending_requests: set[str] = set()
    page.on("request", lambda request: pending_requests.add(request.url))
    page.on("requestfinished", lambda request: pending_requests.discard(request.url))
    page.on("requestfailed", lambda request: pending_requests.discard(request.url))
    wire_errors(page, errors, server_errors)
    page.add_init_script(
        """
        const phase4Fetch = window.fetch.bind(window);
        window.fetch = (input, init = {}) => {
          const url = new URL(typeof input === 'string' ? input : input.url, location.href);
          let body = {};
          try { body = JSON.parse(init.body || '{}'); } catch {}
          if (url.pathname === '/api/andromeda/search' && body.query === 'offline search') {
            return Promise.reject(new TypeError('Failed to fetch'));
          }
          if (url.pathname === '/api/andromeda/overview' && body.query === 'cancel overview') {
            return new Promise((resolve, reject) => {
              const abort = () => reject(new DOMException('cancelled', 'AbortError'));
              if (init.signal?.aborted) abort();
              else init.signal?.addEventListener('abort', abort, { once: true });
            });
          }
          return phase4Fetch(input, init);
        };
        """
    )
    page.route("**/api/andromeda/**", lambda route: mock_andromeda(route, saved))
    results[f"{label}_andromeda_authenticated_gate"] = authenticate_if_needed(
        page, f"{APEX}/?app=andromeda"
    )
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    try:
        page.wait_for_selector("#andromeda-view", state="visible", timeout=20_000)
    except Exception:
        print(
            label,
            "Andromeda boot state",
            {
                "url": page.url,
                "body_class": page.locator("body").get_attribute("class"),
                "visible_views": page.locator(".page-view:visible").evaluate_all(
                    "views => views.map(view => view.id)"
                ),
                "errors": errors[:10],
                "server_errors": server_errors[:10],
                "pending": sorted(pending_requests)[:30],
            },
        )
        raise
    results[f"{label}_andromeda_space"] = (
        page.locator('.space-link[data-space="andromeda"]').get_attribute("aria-current") == "page"
    )
    page.locator("#andromeda-query").fill("latest phase 4 docs")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector(".andromeda-result", timeout=10_000)
    try:
        page.wait_for_selector(".andromeda-claim", timeout=10_000)
    except Exception:
        print(
            label,
            "Andromeda overview state",
            page.locator("#andromeda-overview-state").inner_text(),
            "model",
            page.locator("#andromeda-model").inner_text(),
            "overview html",
            page.locator("#andromeda-overview").inner_html(),
            "console errors",
            errors,
            "server errors",
            server_errors,
        )
        raise
    results[f"{label}_links_and_overview"] = (
        page.locator(".andromeda-result").count() == 2
        and page.locator(".andromeda-claim").count() == 1
    )
    results[f"{label}_citation_evidence"] = (
        page.locator(".andromeda-citation").count() == 1
        and page.locator("#andromeda-evidence-details").is_visible()
    )
    results[f"{label}_model_provider_visible"] = (
        "phase4-local" in page.locator("#andromeda-model").inner_text()
    )
    page.locator("#andromeda-save").click()
    page.wait_for_selector(".andromeda-saved-row", timeout=5_000)
    results[f"{label}_saved_search_visible"] = page.locator(".andromeda-saved-row").is_visible()

    page.locator("#andromeda-query").fill("cancel overview")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector("#andromeda-cancel-overview:not([hidden])", timeout=10_000)
    page.locator("#andromeda-cancel-overview").click()
    page.wait_for_function(
        "document.querySelector('#andromeda-overview-state').textContent.includes('stopped')"
    )
    results[f"{label}_overview_cancellation"] = (
        "normal links are unchanged"
        in page.locator("#andromeda-overview-state").inner_text().lower()
        and page.locator(".andromeda-result").count() == 2
    )

    page.locator("#andromeda-results-toggle").click()
    page.locator("#andromeda-query").fill("overview without visible links")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector(".andromeda-claim", timeout=10_000)
    results[f"{label}_overview_only"] = (
        page.locator(".andromeda-result").count() == 0
        and "normal results are off" in page.locator(".andromeda-empty").inner_text().lower()
    )

    page.locator("#andromeda-results-toggle").click()
    page.locator("#andromeda-overview-toggle").click()
    page.locator("#andromeda-query").fill("links without overview")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector(".andromeda-result", timeout=10_000)
    page.wait_for_function(
        "document.querySelector('#andromeda-status').textContent.includes('2 normal results ready')"
    )
    results[f"{label}_links_only"] = (
        page.locator(".andromeda-result").count() == 2
        and page.locator("#andromeda-overview").is_hidden()
    )

    page.locator("#andromeda-results-toggle").click()
    page.locator("#andromeda-query").fill("everything disabled")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector(".andromeda-empty", timeout=10_000)
    page.wait_for_function(
        "document.querySelector('#andromeda-status').textContent.includes('0 normal results ready')"
    )
    results[f"{label}_both_disabled"] = (
        "normal results are off" in page.locator(".andromeda-empty").inner_text().lower()
        and page.locator("#andromeda-overview").is_hidden()
    )
    page.locator("#andromeda-results-toggle").click()
    page.locator("#andromeda-overview-toggle").click()

    page.locator("#andromeda-query").fill("find a website !ai")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector(".andromeda-result", timeout=10_000)
    results[f"{label}_no_ai_is_one_search"] = page.locator("#andromeda-overview").is_hidden()

    context.set_offline(True)
    page.locator("#andromeda-query").fill("offline search")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_function(
        "document.querySelector('.andromeda-empty')?.textContent.includes('offline')"
    )
    results[f"{label}_offline_recovery"] = (
        "saved searches are still available"
        in page.locator(".andromeda-empty").inner_text().lower()
    )
    context.set_offline(False)

    page.locator("#andromeda-query").fill("fail search")
    page.locator("#andromeda-query").press("Enter")
    page.wait_for_selector("#andromeda-recovery:not([hidden])", timeout=10_000)
    recovery = page.locator("#andromeda-recovery").inner_text().lower()
    results[f"{label}_recovery_actions"] = all(
        value in recovery for value in ("retry", "broaden", "edit query", "normal results")
    )
    failure_copy = page.locator("#andromeda-overview-state").inner_text().lower()
    results[f"{label}_failure_details"] = (
        "provider timeout" in failure_copy and "fixture" in failure_copy
    )
    page.locator('[data-andromeda-recovery="edit"]').click()
    results[f"{label}_recovery_focus_return"] = page.evaluate(
        "document.activeElement?.id === 'andromeda-query'"
    )
    results[f"{label}_labels"] = (
        page.locator("#andromeda-query").get_attribute("aria-label") is None
        and page.locator('label[for="andromeda-query"]').count() == 1
        and page.locator("#andromeda-band").get_attribute("aria-label") == "overview model band"
    )
    results[f"{label}_reduced_motion"] = page.evaluate(
        "matchMedia('(prefers-reduced-motion: reduce)').matches"
    )
    overflow = page.evaluate(
        "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth"
    )
    results[f"{label}_fits"] = overflow <= 2
    results[f"{label}_zero_console_errors"] = not errors
    results[f"{label}_zero_server_errors"] = not server_errors
    if errors:
        print(label, "Andromeda console errors", errors[:10])
    if server_errors:
        print(label, "Andromeda server errors", server_errors[:10])
    context.close()


def check_server_searxng(browser, results: dict) -> None:
    context = new_context(
        browser,
        viewport={"width": 1280, "height": 800},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    errors, server_errors = [], []
    wire_errors(page, errors, server_errors)
    managed = {
        "service_id": "searxng",
        "installed": False,
        "owned": False,
        "available": False,
        "docker_version": "",
        "running": False,
        "healthy": False,
        "bind": "127.0.0.1:8888",
        "version": "2026.7.12-c19d86faa",
        "license": "AGPL-3.0",
        "support_verified": False,
        "spike_note": "no Docker daemon or supported runtime",
        "actions": [],
    }
    page.route(
        "**/api/system/searxng",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(managed)
        ),
    )
    results["server_authenticated_gate"] = authenticate_if_needed(page, SERVER)
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "document.querySelector('#server-searxng-status')?.textContent.includes('managed install unavailable')",
            timeout=20_000,
        )
    except Exception:
        print(
            "Server state",
            {
                "url": page.url,
                "body_class": page.locator("body").get_attribute("class"),
                "login_visible": page.locator("#login-screen").is_visible(),
                "shell_count": page.locator("#sys-shell").count(),
                "status_count": page.locator("#server-searxng-status").count(),
                "status": page.locator("#server-searxng-status").inner_text()
                if page.locator("#server-searxng-status").count()
                else "",
                "errors": errors[:10],
            },
        )
        raise
    state = page.locator("#server-searxng-status").inner_text()
    results["server_searxng_honest_state"] = all(
        value in state
        for value in ("managed install unavailable", "docker unavailable", "127.0.0.1:8888")
    )
    results["server_searxng_no_false_install"] = (
        page.locator('[data-searxng-action="install"]').count() == 0
    )
    results["server_searxng_no_false_managed_label"] = (
        page.locator("#server-searxng-title").inner_text().lower() == "optional searxng"
    )
    results["server_external_searxng_example_is_https"] = (
        page.locator("#s-searxng-url").get_attribute("placeholder") == "https://search.example.com"
    )
    results["server_searxng_zero_errors"] = not errors and not server_errors
    if errors:
        print("Server console errors", errors[:10])
    if server_errors:
        print("Server errors", server_errors[:10])
    context.close()


def main() -> int:
    if not os.environ.get("ALLES_DATA"):
        print("ALLES_DATA must be a throwaway directory", file=sys.stderr)
        return 2
    # The original checks below preserve the historical Chat/Jarvis Phase 4
    # evidence. The shipped product has since moved to one-mode Aide and a
    # managed-SearXNG settings surface, so the live gate must exercise those
    # current contracts instead of looking for controls that were removed on
    # purpose.
    from tests.pw_afterlife_aide_shell import run as run_aide
    from tests.pw_afterlife_andromeda import main as run_andromeda
    from tests.pw_phase6_andromeda_settings import run as run_andromeda_settings

    try:
        run_aide()
        run_andromeda()
        run_andromeda_settings()
    except Exception as exc:
        print(f"current Phase 4 browser gate failed: {exc}", file=sys.stderr)
        return 1
    print("current Phase 4 Aide and Andromeda browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
