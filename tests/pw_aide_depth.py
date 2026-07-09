"""aide surface depth smoke. :8893."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8893"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "aide"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")

ENDPOINTS = [
    {
        "id": "ep1",
        "name": "Audit",
        "provider": "openai",
        "models": ["audit-chat", "audit-pro"],
        "cached_models": ["audit-chat", "audit-pro"],
        "vision_models": ["audit-pro"],
        "image_models": [],
        "enabled": True,
    }
]


def _sse(*chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def _visible(pg, sel):
    return pg.eval_on_selector(
        sel,
        "el => !!el && el.offsetParent !== null && el.getBoundingClientRect().height > 0",
    )


def _api_router(state):
    def route_api(route):
        req = route.request
        u = urlparse(req.url)
        path = u.path
        qs = parse_qs(u.query)
        method = req.method

        def ok(data=None, status=200):
            route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps({} if data is None else data),
            )

        def stream(body):
            route.fulfill(status=200, content_type="text/event-stream", body=body)

        if path == "/api/auth/me":
            return ok({"authenticated": True, "auth_enabled": False, "username": "audit"})
        if path in ("/api/settings", "/api/appearance"):
            return ok(
                {
                    "base_domain": "localhost",
                    "setup_done": True,
                    "insights_enabled": True,
                    "user_model_distill": True,
                    "pidx_proactive_enabled": True,
                }
            )
        if path == "/api/models":
            return ok(ENDPOINTS)
        if path == "/api/models/refresh":
            return ok({"added": []})
        if path == "/api/projects":
            return ok([])
        if path == "/api/personas":
            return ok([])
        if path == "/api/cookbook":
            return ok([])
        if path == "/api/aide/suggestions":
            return ok([])

        if path == "/api/sessions" and method == "GET":
            return ok({"today": state["sessions"], "yesterday": [], "earlier": []})
        if path == "/api/sessions" and method == "POST":
            sid = f"s{len(state['sessions']) + 1}"
            sess = {
                "id": sid,
                "name": "audit chat",
                "model": "audit-chat",
                "endpoint_id": "ep1",
                "starred": False,
                "incognito": False,
            }
            state["sessions"].insert(0, sess)
            return ok(sess)
        if path.endswith("/history") and path.startswith("/api/sessions/"):
            sid = path.split("/")[3]
            sess = next((s for s in state["sessions"] if s["id"] == sid), state["sessions"][0])
            return ok(
                {
                    "session": sess,
                    "messages": [
                        {"role": "user", "content": "hello aide audit"},
                        {"role": "assistant", "content": "hello from fake model"},
                    ],
                }
            )
        if path.endswith("/auto-name") and path.startswith("/api/sessions/"):
            return ok({"name": "audit chat named"})
        if path.startswith("/api/sessions/") and method == "PATCH":
            return ok({"ok": True})

        if path == "/api/chat" and method == "POST":
            state["chat_posts"] += 1
            return stream(
                _sse(
                    {"delta": "hello from fake model"},
                    {"done": True, "usage": {"prompt_tokens": 7, "completion_tokens": 5}},
                )
            )
        if path == "/api/rag/ask":
            return ok({"answer": "docs answer from the vault", "sources": ["project.md"]})
        if path == "/api/research" and method == "POST":
            return stream(
                _sse(
                    {"type": "step", "text": "checking sources"},
                    {"type": "done", "report": "# research answer\nfound it", "sources": []},
                )
            )

        if path == "/api/compare/stats":
            return ok(
                {
                    "votes": 2,
                    "models": [
                        {"model": "audit-chat", "wins": 2, "losses": 0, "win_rate": 1.0}
                    ],
                }
            )
        if path == "/api/compare" and method == "POST":
            state["compare_posts"] += 1
            return ok({"compare_id": "cmp1", "count": 2})
        if path.startswith("/api/compare/cmp1/stream/"):
            idx = path.rsplit("/", 1)[-1]
            return stream(_sse({"delta": f"compare answer {idx}"}))
        if path.startswith("/api/compare"):
            return ok({"ok": True})

        if path == "/api/memories":
            return ok(
                [
                    {
                        "id": "mem1",
                        "text": "prefers short answers",
                        "category": "preference",
                        "pinned": True,
                    }
                ]
            )
        if path == "/api/insights":
            return ok(
                [
                    {
                        "id": "ins1",
                        "title": "ships best after checklists",
                        "body": "small steps get finished",
                        "evidence": ["task:audit"],
                        "pinned": False,
                    }
                ]
            )
        if path == "/api/memory/distilled":
            return ok(
                [
                    {
                        "id": "fact1",
                        "text": "likes clear summaries",
                        "confidence": 0.81,
                        "provenance": "sessions:3",
                        "vetoed": False,
                        "pinned": False,
                    }
                ]
            )
        if path == "/api/proactive/stats":
            return ok({"task": {"acted": 3, "dismissed": 1, "ignored": 1, "weight": 1.2}})
        if path.startswith("/api/insights/") or path.startswith("/api/memory/"):
            return ok({"ok": True, "ran": True, "count": 1})

        if path == "/api/reminders/due":
            return ok([])
        if path == "/api/reminders" and method == "GET":
            return ok(state["reminders"])
        if path == "/api/reminders" and method == "POST":
            item = {
                "id": f"r{len(state['reminders']) + 1}",
                "text": "new audit reminder",
                "trigger_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                "type": "reminder",
            }
            state["reminders"].insert(0, item)
            return ok(item)
        if path.startswith("/api/reminders/") and method == "DELETE":
            rid = path.rsplit("/", 1)[-1]
            state["reminders"] = [x for x in state["reminders"] if x["id"] != rid]
            return ok({"ok": True})

        if path == "/api/gallery" and method == "GET":
            return ok(state["gallery"])
        if path.startswith("/api/gallery/") and method == "DELETE":
            gid = path.rsplit("/", 1)[-1]
            state["gallery"] = [x for x in state["gallery"] if x["id"] != gid]
            return ok({"ok": True})

        if path == "/api/local-models/system":
            return ok(
                {
                    "cpu_name": "audit cpu",
                    "total_ram_gb": 32,
                    "has_gpu": True,
                    "gpu_name": "audit gpu",
                    "gpu_vram_gb": 16,
                    "backend": "llama.cpp",
                }
            )
        if path == "/api/local-models/catalog":
            search = (qs.get("search") or [""])[0].lower()
            model = {
                "name": "TinyLlama/Tiny-audit",
                "params_b": 1.1,
                "quant": "Q4_K_M",
                "run_mode": "gpu",
                "required_gb": 2,
                "speed_tps": 48,
                "fit_level": "perfect",
                "score": 97,
                "installed": True,
                "is_moe": False,
            }
            return ok({"models": [model] if "nope" not in search else []})

        if path == "/api/usage/summary":
            return ok(
                {
                    "total_tokens": 12000,
                    "total_prompt": 7000,
                    "total_completion": 5000,
                    "total_messages": 4,
                    "by_month": [{"name": "jul", "total": 12000}],
                    "by_model": [
                        {
                            "name": "audit-chat",
                            "prompt": 7000,
                            "completion": 5000,
                            "total": 12000,
                            "messages": 4,
                        }
                    ],
                }
            )

        if path == "/api/skills" and method == "GET":
            q = (qs.get("q") or [""])[0].lower()
            rows = state["skills"]
            if q:
                rows = [s for s in rows if q in (s["name"] + s["description"]).lower()]
            return ok(rows)
        if path == "/api/skills/audit-skill":
            return ok(
                {
                    **state["skills"][0],
                    "when_to_use": "when checking aide",
                    "body": "step one\nstep two",
                }
            )
        if path == "/api/skills/sources":
            return ok([])
        if path.startswith("/api/skills/"):
            return ok({"ok": True})

        return ok({})

    return route_api


def _nav(pg, view, target):
    pg.evaluate("(v) => window._navigateTo && window._navigateTo(v)", view)
    pg.wait_for_function(
        "(id) => document.getElementById(id)?.offsetParent !== null",
        arg=target,
        timeout=10000,
    )


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    future = datetime.now(timezone.utc) + timedelta(hours=3)
    state = {
        "chat_posts": 0,
        "compare_posts": 0,
        "sessions": [],
        "reminders": [
            {
                "id": "r1",
                "text": "audit reminder",
                "trigger_at": future.isoformat(),
                "type": "reminder",
            }
        ],
        "gallery": [
            {
                "id": "g1",
                "prompt": "audit image",
                "url": (
                    "data:image/svg+xml,"
                    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 60'%3E"
                    "%3Crect width='80' height='60' fill='%23222'/%3E"
                    "%3Ccircle cx='40' cy='30' r='16' fill='%23ddd'/%3E%3C/svg%3E"
                ),
            }
        ],
        "skills": [
            {
                "slug": "audit-skill",
                "name": "Audit Skill",
                "description": "checks aide surfaces",
                "when_to_use": "when auditing aide",
                "category": "coding",
                "pinned": True,
                "uses": 2,
                "last_used": 0,
                "source": "",
            }
        ],
    }

    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.route("**/api/**", _api_router(state))
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#composer-ta", timeout=15000)
        pg.wait_for_function("() => (window._endpoints || []).length === 1", timeout=10000)
        r["aide_shell_renders"] = _visible(pg, "#composer-outer") and _visible(pg, "#sidebar-toggle-btn")

        pg.fill("#composer-ta", "hello aide audit")
        pg.focus("#composer-ta")
        pg.keyboard.press("Control+Enter")
        pg.wait_for_function(
            "document.querySelector('#messages')?.textContent.includes('hello from fake model')",
            timeout=10000,
        )
        r["ctrl_enter_sends_once"] = state["chat_posts"] == 1
        r["chat_stream_renders_usage"] = (
            "hello from fake model" in (pg.text_content("#messages") or "")
            and "12 tok" in (pg.text_content("#session-token-count") or "")
        )

        pg.click("#docs-toggle-btn")
        pg.fill("#composer-ta", "where is the project")
        pg.press("#composer-ta", "Enter")
        pg.wait_for_function(
            "document.querySelector('.rag-ans')?.textContent.includes('docs answer')",
            timeout=10000,
        )
        r["docs_ask_mode_renders_answer"] = "project.md" in (pg.text_content(".rag-src") or "")

        pg.click("#docs-toggle-btn")
        pg.click("#research-toggle-btn")
        pg.fill("#composer-ta", "research this")
        pg.press("#composer-ta", "Enter")
        pg.wait_for_function(
            "document.querySelector('.rs-report')?.textContent.toLowerCase().includes('research answer')",
            timeout=10000,
        )
        r["research_mode_renders_report"] = "checking sources" in (
            pg.text_content(".rs-steps") or ""
        )

        _nav(pg, "models", "models-view")
        pg.wait_for_selector("#sidebar-model-list .sidebar-model-row", timeout=10000)
        models_txt = pg.text_content("#models-view") or ""
        r["models_view_lists_models"] = "audit" in models_txt.lower()

        _nav(pg, "compare", "compare-view")
        pg.wait_for_selector(".compare-model-row", timeout=10000)
        pg.click(".compare-model-row:nth-of-type(2)")
        pg.click(".compare-model-row:nth-of-type(3)")
        pg.fill("#compare-input", "compare these")
        pg.click("#compare-send-btn")
        pg.wait_for_function(
            "document.querySelector('#compare-grid')?.textContent.includes('compare answer 1')",
            timeout=10000,
        )
        r["compare_streams_two_models"] = (
            state["compare_posts"] == 1
            and "compare answer 0" in (pg.text_content("#compare-grid") or "")
            and "compare answer 1" in (pg.text_content("#compare-grid") or "")
        )

        _nav(pg, "brain", "brain-view")
        pg.wait_for_function(
            "document.querySelector('#brain-insights')?.textContent.includes('ships best')",
            timeout=10000,
        )
        brain_txt = pg.text_content("#brain-view") or ""
        r["brain_memory_intel_renders"] = all(
            x in brain_txt
            for x in [
                "prefers short answers",
                "ships best after checklists",
                "likes clear summaries",
                "task",
            ]
        )

        _nav(pg, "reminders", "reminders-view")
        pg.wait_for_function(
            "document.querySelector('#reminder-list')?.textContent.includes('audit reminder')",
            timeout=10000,
        )
        pg.click('#reminder-list .settings-list-row[data-id="r1"] button')
        pg.wait_for_function(
            "document.querySelector('#reminder-list')?.textContent.includes('no reminders')",
            timeout=10000,
        )
        r["reminders_list_and_cancel"] = not state["reminders"]

        _nav(pg, "gallery", "gallery-view")
        pg.wait_for_function(
            "document.querySelector('#gallery-grid')?.textContent.includes('audit image')",
            timeout=10000,
        )
        pg.click('.gallery-del[data-id="g1"]')
        pg.wait_for_function(
            "document.querySelector('#gallery-grid')?.textContent.includes('ai gallery empty')",
            timeout=10000,
        )
        r["gallery_renders_and_deletes"] = not state["gallery"]

        _nav(pg, "cookbook", "cookbook-view")
        pg.wait_for_function(
            "document.querySelector('#cb-table')?.textContent.includes('Tiny-audit')",
            timeout=10000,
        )
        r["cookbook_catalog_renders"] = (
            "audit cpu" in (pg.text_content("#cookbook-hw") or "")
            and "perfect" in (pg.text_content("#cb-table") or "")
        )

        _nav(pg, "skills", "skills-view")
        pg.wait_for_selector('.skl-card[data-slug="audit-skill"]', timeout=10000)
        pg.fill("#skl-search", "audit")
        pg.wait_for_timeout(300)
        pg.click('.skl-card[data-slug="audit-skill"]')
        pg.wait_for_selector("#skl-drawer.open", timeout=10000)
        pg.wait_for_function("document.getElementById('skl-d-name')?.value === 'Audit Skill'")
        r["skills_search_and_drawer"] = (
            "Audit Skill" in (pg.text_content("#skl-grid") or "")
            and "step one" in pg.input_value("#skl-d-body")
        )

        _nav(pg, "usage", "usage-view")
        pg.wait_for_function(
            "document.querySelector('#usage-body')?.textContent.includes('audit-chat')",
            timeout=10000,
        )
        r["usage_dashboard_renders"] = (
            "12.0k tokens" in (pg.text_content("#usage-total") or "")
            and "audit-chat" in (pg.text_content("#usage-body") or "")
        )

        pg.click("#topbar-settings-btn")
        pg.wait_for_selector("#settings-modal .s-modal", timeout=10000)
        r["settings_modal_opens"] = pg.is_visible("#settings-modal .s-modal")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        r["settings_modal_closes"] = not pg.is_visible("#settings-modal")

        pg.screenshot(path=str(EVID / "aide-depth.png"), full_page=True)
        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_aide_depth.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
