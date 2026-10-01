"""Settings pane lifecycles against owned loopback servers and synthetic responses."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from browser_gate_safety import require_server_ownership  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from services.appearance import from_legacy  # noqa: E402


def permission_first_read_case(page, api, events, destination):
    rules = [{"tool": "example-existing-rule", "path": "", "action": "deny"}]
    assert api.patch("/api/settings", data={"permission_rules": rules}).ok
    fresh = page.context.new_page()
    fresh.on("pageerror", lambda error: events["pageerrors"].append(str(error)))
    fresh.on(
        "console",
        lambda message: (
            events["console_errors"].append(message.text) if message.type == "error" else None
        ),
    )
    try:
        fresh.goto("/?view=today", wait_until="networkidle")
        fresh.locator("#today-settings").click()
        fresh.wait_for_load_state("networkidle")
        reads, writes = [], []

        def initial_failure(route):
            if route.request.method == "GET":
                reads.append(True)
                route.fulfill(
                    status=503, json={"detail": "synthetic first permission read rejected"}
                )
            else:
                writes.append(route.request.method)
                route.continue_()

        fresh.route("**/api/settings", initial_failure)
        fresh.locator('.s-nav-item[data-pane="tools"]').click()
        expect(fresh.locator("#toast-container .toast.error").last).to_have_text(
            "could not load permission rules"
        )
        add = fresh.locator("#perm-rule-add-btn")
        expect(add).to_be_disabled()
        fresh.locator("#perm-rule-tool").fill("example-first-retry")
        add.dispatch_event("click")
        fresh.wait_for_load_state("networkidle")
        assert reads == [True, True] and writes == []
        assert api.get("/api/settings").json()["permission_rules"] == rules
        fresh.unroute("**/api/settings", initial_failure)
        fresh.locator("#settings-modal-close").click()
        fresh.locator("#today-settings").click()
        fresh.locator('.s-nav-item[data-pane="tools"]').click()
        expect(fresh.locator("#perm-rules-list")).to_contain_text("example-existing-rule")
        expect(add).to_be_enabled()
        add.click()
        expect(fresh.locator("#perm-rules-list")).to_contain_text("example-first-retry")
        assert [rule["tool"] for rule in api.get("/api/settings").json()["permission_rules"]] == [
            "example-existing-rule",
            "example-first-retry",
        ]
        fresh.wait_for_load_state("networkidle")
        (destination / "permission-first-read.json").write_text(
            json.dumps(
                {
                    "failed_reads": 2,
                    "unknown_collection_disabled": True,
                    "blocked_patches": 0,
                    "successful_reopen_ready": True,
                    "known_rule_and_retry_retained": True,
                },
                indent=2,
            )
        )
    finally:
        assert api.patch("/api/settings", data={"permission_rules": []}).ok
        fresh.close()


def connection_write_cases(page, api, pane, reopen, choose_edge, destination):
    cases = []
    failures = {"503": 0, "403": 0, "network": 0}

    def clear_toasts():
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    rules = [
        {"tool": "example-rule-a", "path": "", "action": "ask"},
        {"tool": "example-rule-b", "path": "", "action": "deny"},
    ]
    assert api.patch("/api/settings", data={"permission_rules": rules}).ok
    reopen("tools")
    expect(page.locator("#perm-rules-list .perm-rule-tool")).to_have_text(
        [rule["tool"] for rule in rules]
    )
    writes = []
    reject_read = False
    rejected_reads = []

    def rule_requests(route):
        nonlocal reject_read
        if route.request.method == "PATCH":
            writes.append(route)
            page.evaluate("count => window.__ruleWrites = count", len(writes))
        elif reject_read:
            reject_read = False
            rejected_reads.append(True)
            route.fulfill(status=503, json={"detail": "synthetic rule reload rejected"})
        else:
            route.continue_()

    page.route("**/api/settings", rule_requests)
    delete = page.locator("#perm-rules-list .perm-rule-del").first
    delete.click()
    page.wait_for_function("window.__ruleWrites === 1")
    expect(delete).to_be_disabled()
    delete.dispatch_event("click")
    reopen("tools")
    assert page.locator("#perm-rules-list .perm-rule-del").evaluate_all(
        "buttons => buttons.length === 2 && buttons.every(button => button.disabled)"
    )
    page.locator("#perm-rules-list .perm-rule-del").first.dispatch_event("click")
    assert len(writes) == 1
    assert writes[0].request.post_data_json["permission_rules"] == rules[1:]
    response = writes[0].fetch()
    assert response.ok
    writes[0].fulfill(response=response)
    expect(page.locator("#perm-rules-list .perm-rule-tool")).to_have_text(["example-rule-b"])
    assert api.get("/api/settings").json()["permission_rules"] == rules[1:]
    cases.append({"case": "same rule activation", "writes": 1, "adjacent_rule_retained": True})

    # Add and Delete share the whole rule collection, including a reopening read.
    page.locator("#perm-rule-tool").fill("example-rule-c")
    page.locator("#perm-rule-path").fill("/example/submitted")
    add = page.locator("#perm-rule-add-btn")
    add.click()
    page.wait_for_function("window.__ruleWrites === 2")
    page.locator("#perm-rule-tool").fill("example newer rule draft")
    reopen("tools")
    expect(add).to_be_disabled()
    expect(delete).to_be_disabled()
    delete.dispatch_event("click")
    add.dispatch_event("click")
    assert len(writes) == 2
    response = writes[-1].fetch()
    assert response.ok
    submitted = response.json()["permission_rules"]
    writes[-1].fulfill(response=response)
    expect(page.locator("#perm-rules-list .perm-rule-tool")).to_have_text(
        [rule["tool"] for rule in submitted]
    )
    expect(page.locator("#perm-rule-tool")).to_have_value("example newer rule draft")
    assert api.get("/api/settings").json()["permission_rules"] == submitted
    cases.append(
        {
            "case": "rule Add/Delete reopening",
            "writes": 1,
            "saved_rule_and_new_draft_retained": True,
        }
    )

    clear_toasts()
    delete.click()
    page.wait_for_function("window.__ruleWrites === 3")
    reject_read = True
    writes[-1].fulfill(status=503, json={"detail": "synthetic rule delete rejected"})
    failures["503"] += 2
    expect(add).to_be_enabled()
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "could not load permission rules"
    )
    assert rejected_reads == [True]
    expect(page.locator("#perm-rules-list .perm-rule-tool")).to_have_text(
        [rule["tool"] for rule in submitted]
    )
    assert api.get("/api/settings").json()["permission_rules"] == submitted
    # The retained row still targets its original rule after a failed reload.
    delete.click()
    page.wait_for_function("window.__ruleWrites === 4")
    response = writes[-1].fetch()
    assert response.ok
    writes[-1].fulfill(response=response)
    expect(page.locator("#perm-rules-list .perm-rule-tool")).to_have_text(["example-rule-c"])
    assert api.get("/api/settings").json()["permission_rules"] == submitted[1:]
    cases.append(
        {
            "case": "rule failure and retry",
            "failed_read_keeps_cache": True,
            "correct_rule_removed": True,
        }
    )
    page.unroute("**/api/settings", rule_requests)
    assert api.patch("/api/settings", data={"permission_rules": []}).ok

    # Same persisted service upserts and deletion cannot undo each other.
    for order in ("save-first", "delete-first"):
        service = "example-service-" + order
        response = api.post("/api/connections", data={"service": service, "token": "example"})
        assert response.ok
        record_id = response.json()["id"]
        other = api.post(
            "/api/connections", data={"service": service + "-other", "token": "example"}
        )
        assert other.ok
        other_id = other.json()["id"]
        reopen("tools")
        remove = page.locator(f'#conn-list button[data-id="{record_id}"]')
        expect(remove).to_be_visible()
        choose_edge("conn-service")
        page.locator("#conn-custom").fill(" " + service.upper() + " ")
        page.locator("#conn-token").fill("redacted-example")
        posts, deletes = [], []

        def service_post(route):
            if route.request.method == "POST":
                posts.append(route)
                page.evaluate("count => window.__servicePosts = count", len(posts))
            else:
                route.continue_()

        def service_delete(route):
            deletes.append(route)
            page.evaluate("count => window.__serviceDeletes = count", len(deletes))

        page.route("**/api/connections", service_post)
        page.route("**/api/connections/" + record_id, service_delete)
        page.evaluate("window.__servicePosts = 0; window.__serviceDeletes = 0")
        connect = page.locator("#conn-add-btn")
        (connect if order == "save-first" else remove).click()
        page.wait_for_function(
            "window.__servicePosts === 1"
            if order == "save-first"
            else "window.__serviceDeletes === 1"
        )
        reopen("tools")
        expect(connect).to_be_disabled()
        expect(remove).to_be_disabled()
        connect.dispatch_event("click")
        remove.dispatch_event("click")
        assert len(posts) == (1 if order == "save-first" else 0)
        assert len(deletes) == (0 if order == "save-first" else 1)
        # A different service remains independently writable.
        other_remove = page.locator(f'#conn-list button[data-id="{other_id}"]')
        expect(other_remove).to_be_enabled()
        with page.expect_response(
            lambda response: (
                response.request.method == "DELETE"
                and response.url.endswith("/api/connections/" + other_id)
            )
        ) as independent:
            other_remove.click()
        assert independent.value.ok
        assert not any(row["id"] == other_id for row in api.get("/api/connections").json())
        page.locator("#conn-custom").fill(service + "-new")
        if order == "delete-first":
            expect(connect).to_be_enabled()
        page.locator("#conn-custom").fill(service)
        expect(connect).to_be_disabled()
        held = (posts if order == "save-first" else deletes)[0]
        result = held.fetch()
        assert result.ok
        held.fulfill(response=result)
        expect(connect).to_be_enabled()
        if order == "save-first":
            expect(remove).to_be_enabled()
            assert (
                next(row for row in api.get("/api/connections").json() if row["id"] == record_id)[
                    "token_masked"
                ]
                == "reda…mple"
            )
        else:
            expect(remove).to_have_count(0)
            assert not any(row["id"] == record_id for row in api.get("/api/connections").json())
        page.unroute("**/api/connections", service_post)
        page.unroute("**/api/connections/" + record_id, service_delete)
        assert api.delete("/api/connections/" + record_id).ok
        assert api.delete("/api/connections/" + other_id).ok
        cases.append(
            {
                "case": "normalized service " + order,
                "posts": len(posts),
                "deletes": len(deletes),
                "competing_write_blocked": True,
                "different_service_enabled": True,
            }
        )

    for kind in ("connection", "mcp"):
        collection = "/api/connections" if kind == "connection" else "/api/mcp/servers"
        list_id = "conn-list" if kind == "connection" else "mcp-server-list"
        response = api.post(
            collection,
            data={"service": "example-delete", "token": "example"}
            if kind == "connection"
            else {"name": "example delete", "transport": "sse", "url": "http://127.0.0.1:1"},
        )
        assert response.ok
        record_id = response.json()["id"]
        independent_id = None
        if kind == "mcp":
            independent_record = api.post(
                collection,
                data={
                    "name": "example independent MCP",
                    "transport": "sse",
                    "url": "http://127.0.0.1:1",
                },
            )
            assert independent_record.ok
            independent_id = independent_record.json()["id"]
        reopen("tools")
        remove = page.locator(f'#{list_id} button[data-id="{record_id}"]')
        expect(remove).to_be_visible()
        held_deletes = []

        def hold_delete(route):
            held_deletes.append(route)
            page.evaluate("count => window.__connectorDeletes = count", len(held_deletes))

        pattern = "**" + collection + "/" + record_id
        page.route(pattern, hold_delete)
        for outcome in ("503", "403", "network"):
            clear_toasts()
            count = len(held_deletes) + 1
            remove.click()
            page.wait_for_function("count => window.__connectorDeletes === count", arg=count)
            remove.dispatch_event("click")
            reopen("tools")
            expect(remove).to_be_disabled()
            remove.dispatch_event("click")
            assert len(held_deletes) == count
            if independent_id is not None and outcome == "503":
                other_remove = page.locator(f'#{list_id} button[data-id="{independent_id}"]')
                expect(other_remove).to_be_enabled()
                with page.expect_response(
                    lambda response: (
                        response.request.method == "DELETE"
                        and response.url.endswith(collection + "/" + independent_id)
                    )
                ) as independent:
                    other_remove.click()
                assert independent.value.ok
                assert not any(row["id"] == independent_id for row in api.get(collection).json())
            if outcome == "network":
                held_deletes[-1].abort("failed")
            else:
                if outcome == "403":
                    page.route(
                        "**/api/auth/me", lambda route: route.fulfill(json={"enabled": True})
                    )
                held_deletes[-1].fulfill(
                    status=int(outcome), json={"detail": "synthetic delete rejected"}
                )
                if outcome == "403":
                    expect(page.locator("[data-dialog-cancel]")).to_be_visible()
                    page.locator("[data-dialog-cancel]").click()
                    page.unroute("**/api/auth/me")
            failures[outcome] += 1
            expect(page.locator("#toast-container .toast.error").last).to_have_text(
                "could not disconnect" if kind == "connection" else "could not remove mcp server"
            )
            expect(remove).to_be_enabled()
            assert any(row["id"] == record_id for row in api.get(collection).json())
            cases.append(
                {
                    "case": kind + " delete " + outcome,
                    "requests": 1,
                    "record_retained": True,
                    "control_released": True,
                    "independent_id_written": independent_id is not None and outcome == "503",
                }
            )
        page.unroute(pattern, hold_delete)
        remove.click()
        expect(remove).to_have_count(0)
        assert not any(row["id"] == record_id for row in api.get(collection).json())

        for rejected in (False, True, "after-ack"):
            response = api.post(
                collection,
                data={"service": "example-focused-delete", "token": "example"}
                if kind == "connection"
                else {
                    "name": "example focused delete",
                    "transport": "sse",
                    "url": "http://127.0.0.1:1",
                },
            )
            assert response.ok
            record_id = response.json()["id"]
            reopen("tools")
            remove = page.locator(f'#{list_id} button[data-id="{record_id}"]')
            expect(remove).to_be_visible()
            page.wait_for_load_state("networkidle")
            reads, held_deletes = [], []
            hold_read = True

            def current_read(route):
                nonlocal hold_read
                if route.request.method == "GET" and hold_read:
                    hold_read = False
                    snapshot = route.fetch()
                    assert snapshot.ok
                    reads.append((route, snapshot))
                    page.evaluate("window.__connectorReadHeld = true")
                else:
                    route.continue_()

            pattern = "**" + collection + "/" + record_id
            page.route("**" + collection, current_read)
            page.route(pattern, hold_delete)
            page.evaluate("window.__connectorReadHeld = false; window.__connectorDeletes = 0")
            reopen("tools")
            page.wait_for_function("window.__connectorReadHeld === true")
            remove.click()
            page.wait_for_function("window.__connectorDeletes === 1")
            remove.evaluate("button => window.__connectorBusyControl = button")
            focus = page.evaluate("document.activeElement.id")
            if rejected == "after-ack":
                result = held_deletes[0].fetch()
                assert result.ok
                held_deletes[0].fulfill(response=result)
                expect(remove).to_have_count(0)
                reads[0][0].fulfill(response=reads[0][1])
                page.wait_for_load_state("networkidle")
                expect(remove).to_have_count(0)
                assert not any(row["id"] == record_id for row in api.get(collection).json())
            else:
                if rejected:
                    reads[0][0].fulfill(
                        status=503, json={"detail": "synthetic current list rejected"}
                    )
                    failures["503"] += 1
                else:
                    reads[0][0].fulfill(response=reads[0][1])
                page.evaluate(
                    "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                )
                assert page.evaluate("window.__connectorBusyControl.isConnected")
                assert page.evaluate("document.activeElement.id") == focus
                expect(remove).to_be_disabled()
                clear_toasts()
                held_deletes[0].fulfill(
                    status=503, json={"detail": "synthetic focused delete rejected"}
                )
                failures["503"] += 1
                expect(page.locator("#toast-container .toast.error").last).to_have_text(
                    "could not disconnect"
                    if kind == "connection"
                    else "could not remove mcp server"
                )
                expect(remove).to_be_enabled()
                assert any(row["id"] == record_id for row in api.get(collection).json())
                assert api.delete(collection + "/" + record_id).ok
            page.unroute("**" + collection, current_read)
            page.unroute(pattern, hold_delete)
            cases.append(
                {
                    "case": kind + " current read " + str(rejected),
                    "busy_node_preserved": rejected != "after-ack",
                    "after_ack_stale_excluded": rejected == "after-ack",
                }
            )

    presets = [
        {"id": "filesystem", "name": "example preset", "description": "example connector"},
        {"id": "example-other", "name": "example other", "description": "independent example"},
    ]
    page.route("**/api/mcp/presets", lambda route: route.fulfill(json=presets))
    preset_posts = []

    def hold_preset(route):
        preset_posts.append(route)
        page.evaluate("count => window.__presetPosts = count", len(preset_posts))

    page.route("**/api/mcp/presets/filesystem", hold_preset)
    reopen("tools")
    button = page.locator('.mcp-preset[data-id="filesystem"]')
    expect(button).to_be_visible()
    button.click()
    page.wait_for_function("window.__presetPosts === 1")
    button.dispatch_event("click")
    reopen("tools")
    expect(button).to_be_disabled()
    expect(page.locator('.mcp-preset[data-id="example-other"]')).to_be_enabled()
    button.dispatch_event("click")
    assert len(preset_posts) == 1
    created = api.post(
        "/api/mcp/servers",
        data={"name": "example preset", "transport": "sse", "url": "http://127.0.0.1:1"},
    )
    assert created.ok
    preset_posts[0].fulfill(json=created.json())
    expect(button).to_be_enabled()
    expect(page.locator("#mcp-server-list")).to_contain_text("example preset")
    assert (
        len([row for row in api.get("/api/mcp/servers").json() if row["name"] == "example preset"])
        == 1
    )
    clear_toasts()
    button.click()
    page.wait_for_function("window.__presetPosts === 2")
    preset_posts[-1].fulfill(status=503, json={"detail": "synthetic preset rejected"})
    failures["503"] += 1
    expect(button).to_be_enabled()
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "could not add connector"
    )
    assert api.delete("/api/mcp/servers/" + created.json()["id"]).ok
    page.unroute("**/api/mcp/presets/filesystem", hold_preset)
    page.unroute("**/api/mcp/presets")
    cases.append(
        {
            "case": "preset ownership",
            "one_real_record": True,
            "independent_preset_enabled": True,
            "failure_released": True,
            "external_processes": 0,
        }
    )
    (destination / "connection-write-owners.json").write_text(json.dumps(cases, indent=2))
    return failures


def retained_write_cases(page, api, pane, reopen, destination):
    cases = []
    failures = {"503": 0, "network": 0}

    def clear_toasts():
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    for kind in ("persona", "persona-doc", "cookbook", "webhook"):
        parent_id = None
        if kind.startswith("persona"):
            response = api.post(
                "/api/personas",
                data={"name": "example delete " + kind, "system_prompt": "example prompt"},
            )
            assert response.ok
            parent_id = response.json()["id"]
            reopen("personas")
            if kind == "persona-doc":
                response = api.post(
                    f"/api/personas/{parent_id}/docs",
                    data={"title": "example doc", "content": "example text"},
                )
                assert response.ok
                collection = f"/api/personas/{parent_id}/docs"
                page.locator(f'#persona-list .persona-row[data-id="{parent_id}"] .row-name').click()
                list_id = "persona-docs"
            else:
                collection, list_id = "/api/personas", "persona-list"
        else:
            collection = "/api/cookbook" if kind == "cookbook" else "/api/webhooks"
            response = api.post(
                collection,
                data={"name": "example-delete-command", "prompt": "example prompt"}
                if kind == "cookbook"
                else {
                    "name": "example delete webhook",
                    "url": "http://127.0.0.1:1/example",
                    "events": ["message"],
                },
            )
            assert response.ok
            list_id = "cookbook-list" if kind == "cookbook" else "webhook-list"
            reopen("personas" if kind == "cookbook" else "developer")
        record_id = response.json()["id"]
        remove = page.locator(f'#{list_id} button[data-id="{record_id}"]').filter(has_text="remove")
        expect(remove).to_be_visible()
        held = []

        def hold_delete(route):
            held.append(route)
            page.evaluate("count => window.__retainedDeletes = count", len(held))

        pattern = "**" + collection + "/" + record_id
        page.route(pattern, hold_delete)
        error = {
            "persona": "persona could not be removed",
            "persona-doc": "knowledge file could not be removed",
            "cookbook": "command could not be removed",
            "webhook": "webhook could not be removed",
        }[kind]
        for outcome in ("503", "network"):
            clear_toasts()
            count = len(held) + 1
            remove.click()
            page.wait_for_function("count => window.__retainedDeletes === count", arg=count)
            expect(remove).to_be_disabled()
            remove.dispatch_event("click")
            reopen("developer" if kind == "webhook" else "personas")
            expect(remove).to_be_disabled()
            remove.dispatch_event("click")
            assert len(held) == count
            if outcome == "503":
                held[-1].fulfill(status=503, json={"detail": "synthetic retained delete rejected"})
            else:
                held[-1].abort("failed")
            failures[outcome] += 1
            expect(page.locator("#toast-container .toast.error").last).to_have_text(error)
            expect(remove).to_be_enabled()
            assert any(row["id"] == record_id for row in api.get(collection).json())
            cases.append(
                {
                    "case": kind + " delete " + outcome,
                    "record_retained": True,
                    "error_reported_and_owner_released": True,
                }
            )
        page.unroute(pattern, hold_delete)
        remove.click()
        expect(remove).to_have_count(0)
        assert not any(row["id"] == record_id for row in api.get(collection).json())
        if kind == "persona-doc":
            assert api.delete("/api/personas/" + parent_id).ok
            page.locator("#persona-cancel-btn").click()

    specs = [
        (
            "persona",
            "personas",
            "/api/personas",
            "persona-add-btn",
            ["persona-name", "persona-prompt", "persona-initial"],
            ["example submitted persona", "example old prompt", "example old greeting"],
        ),
        (
            "cookbook",
            "personas",
            "/api/cookbook",
            "cookbook-add-btn",
            ["cookbook-name", "cookbook-desc", "cookbook-prompt"],
            ["example-submitted-command", "example old description", "example old prompt"],
        ),
        (
            "token",
            "developer",
            "/api/tokens",
            "token-add-btn",
            ["token-name"],
            ["example submitted token"],
        ),
        (
            "webhook",
            "developer",
            "/api/webhooks",
            "wh-add-btn",
            ["wh-name", "wh-url"],
            ["example submitted webhook", "http://127.0.0.1:1/example-hook"],
        ),
    ]
    for kind, name, collection, button_id, fields, values in specs:
        reopen(name)
        held = []

        def hold_create(route):
            if route.request.method == "POST":
                held.append(route)
                page.evaluate("count => window.__retainedCreates = count", len(held))
            else:
                route.continue_()

        pattern = "**" + collection
        page.route(pattern, hold_create)
        button = page.locator("#" + button_id)
        for outcome in ("newer", "failure"):
            for field, value in zip(fields, values, strict=True):
                page.locator("#" + field).fill(value)
            clear_toasts()
            count = len(held) + 1
            button.click()
            page.wait_for_function("count => window.__retainedCreates === count", arg=count)
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            if outcome == "newer":
                for field in fields:
                    page.locator("#" + field).fill(
                        "http://127.0.0.1:2/example-new-hook"
                        if field == "wh-url"
                        else "example newer " + field
                    )
            draft = {field: page.locator("#" + field).input_value() for field in fields}
            reopen(name)
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            assert len(held) == count
            assert {field: page.locator("#" + field).input_value() for field in fields} == draft
            if outcome == "failure":
                held[-1].fulfill(status=503, json={"detail": "synthetic retained create rejected"})
                failures["503"] += 1
                expect(page.locator("#toast-container .toast.error").last).to_be_visible()
                assert page.locator("#toast-container .toast.success").count() == 0
                expect(button).to_be_enabled()
                assert {field: page.locator("#" + field).input_value() for field in fields} == draft
                # A corrected retry of the unchanged form succeeds and clears it.
                button.click()
                count += 1
                page.wait_for_function("count => window.__retainedCreates === count", arg=count)
            response = held[-1].fetch()
            assert response.ok, response.text()
            saved = response.json()
            held[-1].fulfill(response=response)
            expect(button).to_be_enabled()
            if outcome == "newer":
                assert {field: page.locator("#" + field).input_value() for field in fields} == draft
            else:
                assert all(page.locator("#" + field).input_value() == "" for field in fields)
            record = next(row for row in api.get(collection).json() if row["id"] == saved["id"])
            assert record["name"] == values[0]
            if kind == "token":
                expect(page.locator("#token-reveal")).to_contain_text(saved["token"])
                page.locator("#token-reveal").evaluate(
                    "element => { element.textContent = 'redacted'; element.style.display = 'none'; }"
                )
            assert api.delete(collection + "/" + saved["id"]).ok
            cases.append(
                {
                    "case": kind + " create " + outcome,
                    "duplicate_suppressed": True,
                    "submitted_old_record_readback": True,
                    "newer_draft_retained": outcome == "newer",
                    "unchanged_retry_clears": outcome == "failure",
                    "one_time_result_retained": kind == "token",
                }
            )
        page.unroute(pattern, hold_create)

    # A late initial list cannot hide an acknowledged real command creation.
    pane("general")
    reads = []

    def hold_cookbook_read(route):
        if route.request.method == "GET":
            response = route.fetch()
            assert response.ok
            reads.append((route, response))
            page.evaluate("count => window.__retainedCookbookReads = count", len(reads))
        else:
            route.continue_()

    page.route("**/api/cookbook", hold_cookbook_read)
    pane("personas")
    page.wait_for_function("window.__retainedCookbookReads === 1")
    page.locator("#cookbook-name").fill("example-list-ack-command")
    page.locator("#cookbook-prompt").fill("example prompt")
    page.locator("#cookbook-add-btn").click()
    page.wait_for_function("window.__retainedCookbookReads === 2")
    reads[1][0].fulfill(response=reads[1][1])
    expect(page.locator("#cookbook-list")).to_contain_text("/example-list-ack-command")
    saved = next(
        row for row in api.get("/api/cookbook").json() if row["name"] == "example-list-ack-command"
    )
    reads[0][0].fulfill(response=reads[0][1])
    page.wait_for_load_state("networkidle")
    expect(page.locator("#cookbook-list")).to_contain_text("/example-list-ack-command")
    assert any(row["id"] == saved["id"] for row in api.get("/api/cookbook").json())
    page.unroute("**/api/cookbook", hold_cookbook_read)
    page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    def failed_cookbook_read(route):
        if route.request.method == "GET":
            route.fulfill(status=503, json={"detail": "synthetic command list rejected"})
        else:
            route.continue_()

    page.route("**/api/cookbook", failed_cookbook_read)
    reopen("personas")
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "commands could not be loaded"
    )
    expect(page.locator("#cookbook-list")).to_contain_text("/example-list-ack-command")
    assert any(row["id"] == saved["id"] for row in api.get("/api/cookbook").json())
    failures["503"] += 1
    page.unroute("**/api/cookbook", failed_cookbook_read)
    reopen("personas")
    expect(page.locator("#cookbook-list")).to_contain_text("/example-list-ack-command")
    assert api.delete("/api/cookbook/" + saved["id"]).ok
    cases.extend(
        [
            {"case": "cookbook late list", "fresh_ack_retained": True, "old_read_excluded": True},
            {
                "case": "cookbook current list failure",
                "known_row_retained": True,
                "error_reported": True,
                "normal_read_recovers": True,
            },
        ]
    )
    (destination / "retained-write-owners.json").write_text(json.dumps(cases, indent=2))
    return failures


def retained_list_cases(page, api, pane, reopen, destination):
    cases = []
    for kind, name, collection, list_id, button_id, fields, values in (
        (
            "persona",
            "personas",
            "/api/personas",
            "persona-list",
            "persona-add-btn",
            ["persona-name", "persona-prompt"],
            ["example list persona", "example prompt"],
        ),
        (
            "token",
            "developer",
            "/api/tokens",
            "token-list",
            "token-add-btn",
            ["token-name"],
            ["example list token"],
        ),
        (
            "webhook",
            "developer",
            "/api/webhooks",
            "webhook-list",
            "wh-add-btn",
            ["wh-name", "wh-url"],
            ["example list webhook", "http://127.0.0.1:1/example"],
        ),
        (
            "persona-doc",
            "personas",
            None,
            "persona-docs",
            "persona-doc-add",
            ["persona-doc-title", "persona-doc-content"],
            ["example list document", "example text"],
        ),
    ):
        page.wait_for_load_state("networkidle")
        parent_id = None
        if kind == "persona-doc":
            parent = api.post("/api/personas", data={"name": "example document list parent"})
            assert parent.ok
            parent_id = parent.json()["id"]
            collection = f"/api/personas/{parent_id}/docs"
            reopen("personas")
            parent_row = page.locator(
                f'#persona-list .persona-row[data-id="{parent_id}"] .row-name'
            )
            expect(parent_row).to_be_visible()
        else:
            pane("general")
        reads = []
        writes, picker_reads = [], []
        if kind == "persona":
            # The chat picker reads the same API after a successful save. Hold
            # only the Settings loader so those independent refreshes stay live.
            page.evaluate("""() => {
                window.__settingsListOriginalFetch = window.fetch;
                window.fetch = function(input, options) {
                    if (input === '/api/personas' && (!options?.method || options.method === 'GET') &&
                        new Error().stack.includes('at loadPersonas ')) {
                        options = { ...options, headers: new Headers(options?.headers) };
                        options.headers.set('x-alles-test-settings-read', 'personas');
                    }
                    return window.__settingsListOriginalFetch.apply(this, [input, options]);
                };
            }""")

        def delayed_list(route):
            if route.request.method == "GET":
                if (
                    kind == "persona"
                    and route.request.headers.get("x-alles-test-settings-read") != "personas"
                ):
                    picker_reads.append(True)
                    route.continue_()
                    return
                snapshot = route.fetch()
                assert snapshot.ok
                reads.append((route, snapshot))
                page.evaluate("count => window.__retainedListReads = count", len(reads))
            else:
                writes.append(route.request.method)
                route.continue_()

        pattern = "**" + collection
        page.route(pattern, delayed_list)
        page.evaluate("window.__retainedListReads = 0")
        if parent_id:
            parent_row.click()
        else:
            pane(name)
        page.wait_for_function("window.__retainedListReads === 1")
        for field, value in zip(fields, values, strict=True):
            page.locator("#" + field).fill(value)
        page.locator("#" + button_id).click()
        page.wait_for_function("window.__retainedListReads === 2")
        reads[1][0].fulfill(response=reads[1][1])
        expect(page.locator("#" + list_id)).to_contain_text(values[0])
        saved = next(
            row
            for row in api.get(collection).json()
            if row.get("name", row.get("title")) == values[0]
        )
        reads[0][0].fulfill(response=reads[0][1])
        page.wait_for_load_state("networkidle")
        expect(page.locator("#" + list_id)).to_contain_text(values[0])
        assert any(row["id"] == saved["id"] for row in api.get(collection).json())
        assert len(reads) == 2
        assert writes == ["POST"]
        if kind == "persona":
            assert len(picker_reads) == 2
        page.unroute(pattern, delayed_list)
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

        def failed_list(route):
            if route.request.method == "GET":
                if (
                    kind == "persona"
                    and route.request.headers.get("x-alles-test-settings-read") != "personas"
                ):
                    route.continue_()
                    return
                route.fulfill(status=503, json={"detail": "synthetic retained list rejected"})
            else:
                route.continue_()

        page.route(pattern, failed_list)
        if parent_id:
            parent_row.click()
        else:
            reopen(name)
        expect(page.locator("#toast-container .toast.error").last).to_have_text(
            {
                "persona": "personas could not be loaded",
                "token": "tokens could not be loaded",
                "webhook": "webhooks could not be loaded",
                "persona-doc": "knowledge files could not be loaded",
            }[kind]
        )
        expect(page.locator("#" + list_id)).to_contain_text(values[0])
        assert any(row["id"] == saved["id"] for row in api.get(collection).json())
        page.unroute(pattern, failed_list)
        if parent_id:
            parent_row.click()
        else:
            reopen(name)
        expect(page.locator("#" + list_id)).to_contain_text(values[0])
        page.wait_for_load_state("networkidle")
        if kind == "persona":
            page.evaluate("""() => {
                window.fetch = window.__settingsListOriginalFetch;
                delete window.__settingsListOriginalFetch;
            }""")
        if kind == "token":
            page.locator("#token-reveal").evaluate(
                "element => { element.textContent = 'redacted'; element.style.display = 'none'; }"
            )
        assert api.delete(collection + "/" + saved["id"]).ok
        if parent_id:
            assert api.delete("/api/personas/" + parent_id).ok
            page.locator("#persona-cancel-btn").click()
        cases.extend(
            [
                {
                    "case": kind + " initial list after acknowledged create",
                    "fresh_row_retained": True,
                    "stale_read_excluded": True,
                    "server_readback": True,
                    "one_create_post": True,
                    "picker_refreshes_preserved": kind == "persona",
                },
                {
                    "case": kind + " current list failure",
                    "known_row_retained": True,
                    "error_reported": True,
                    "normal_read_recovers": True,
                },
            ]
        )

    # Knowledge files remain attached to the persona currently being edited.
    parents = []
    for label in ("A", "B"):
        response = api.post("/api/personas", data={"name": "example doc parent " + label})
        assert response.ok
        parent_id = response.json()["id"]
        assert api.post(
            f"/api/personas/{parent_id}/docs",
            data={"title": "example doc " + label, "content": "example text"},
        ).ok
        parents.append(parent_id)
    reopen("personas")
    held = []

    def delayed_parent_a(route):
        snapshot = route.fetch()
        assert snapshot.ok
        held.append((route, snapshot))
        page.evaluate("window.__parentDocReadHeld = true")

    pattern = f"**/api/personas/{parents[0]}/docs"
    page.route(pattern, delayed_parent_a)
    page.locator(f'#persona-list .persona-row[data-id="{parents[0]}"] .row-name').click()
    page.wait_for_function("window.__parentDocReadHeld === true")
    page.locator(f'#persona-list .persona-row[data-id="{parents[1]}"] .row-name').click()
    expect(page.locator("#persona-name")).to_have_value("example doc parent B")
    expect(page.locator("#persona-docs")).to_contain_text("example doc B")
    held[0][0].fulfill(response=held[0][1])
    page.wait_for_load_state("networkidle")
    expect(page.locator("#persona-docs")).to_contain_text("example doc B")
    expect(page.locator("#persona-docs")).not_to_contain_text("example doc A")
    page.unroute(pattern, delayed_parent_a)
    page.locator("#persona-cancel-btn").click()
    for parent_id in parents:
        assert api.delete("/api/personas/" + parent_id).ok
    cases.append({"case": "persona document identity", "late_A_cannot_publish_into_B": True})
    (destination / "retained-list-owners.json").write_text(json.dumps(cases, indent=2))
    return 4


def persona_write_cases(page, api, reopen, destination):
    cases = []
    failures = {"503": 0, "404": 0, "network": 0}

    def fixture(label):
        response = api.post(
            "/api/personas",
            data={"name": "example parent " + label, "system_prompt": "example initial prompt"},
        )
        assert response.ok
        return response.json()["id"]

    def edit(parent_id):
        reopen("personas")
        page.locator(f'#persona-list .persona-row[data-id="{parent_id}"] .row-name').click()
        expect(page.locator("#persona-extra")).to_be_visible()
        page.wait_for_load_state("networkidle")

    def remove(parent_id):
        return page.locator(f'#persona-list [data-persona-remove][data-id="{parent_id}"]')

    for outcome in ("newer", "editor-B", "503", "network", "unchanged"):
        parent_id = fixture("document " + outcome)
        second_id = fixture("editor B") if outcome == "editor-B" else None
        edit(parent_id)
        page.locator("#persona-doc-title").fill("example submitted document")
        page.locator("#persona-doc-content").fill("example submitted text")
        held = []

        def document_request(route):
            if route.request.method == "POST":
                held.append(route)
                page.evaluate("count => window.__personaDocWrites = count", len(held))
            else:
                route.continue_()

        pattern = f"**/api/personas/{parent_id}/docs"
        page.route(pattern, document_request)
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")
        add = page.locator("#persona-doc-add")
        add.click()
        page.wait_for_function("window.__personaDocWrites === 1")
        expect(add).to_be_disabled()
        add.dispatch_event("click")
        expect(remove(parent_id)).to_be_disabled()
        remove(parent_id).dispatch_event("click")
        if second_id:
            page.locator(f'#persona-list .persona-row[data-id="{second_id}"] .row-name').click()
            expect(page.locator("#persona-name")).to_have_value("example parent editor B")
            expect(remove(second_id)).to_be_enabled()
        if outcome in {"newer", "editor-B"}:
            page.locator("#persona-doc-title").fill("example newer document")
            page.locator("#persona-doc-content").fill("example newer text")
        draft = {
            field: page.locator("#" + field).input_value()
            for field in ("persona-doc-title", "persona-doc-content")
        }
        reopen("personas")
        if not second_id:
            expect(add).to_be_disabled()
            add.dispatch_event("click")
        assert len(held) == 1
        assert any(row["id"] == parent_id for row in api.get("/api/personas").json())
        if outcome in {"503", "network"}:
            if outcome == "503":
                held[0].fulfill(status=503, json={"detail": "synthetic document add rejected"})
            else:
                held[0].abort("failed")
            failures[outcome] += 1
            expect(page.locator("#toast-container .toast.error").last).to_be_visible()
            assert page.locator("#toast-container .toast.success").count() == 0
            expect(add).to_be_enabled()
            assert {field: page.locator("#" + field).input_value() for field in draft} == draft
            assert api.get(f"/api/personas/{parent_id}/docs").json() == []
            add.click()
            page.wait_for_function("window.__personaDocWrites === 2")
        response = held[-1].fetch()
        assert response.ok
        assert held[-1].request.post_data_json == {
            "title": "example submitted document",
            "content": "example submitted text",
        }
        held[-1].fulfill(response=response)
        expect(add).to_be_enabled()
        expect(page.locator("#toast-container .toast.success").last).to_have_text(
            "knowledge file added"
        )
        if outcome in {"newer", "editor-B"}:
            assert {field: page.locator("#" + field).input_value() for field in draft} == draft
        else:
            assert all(page.locator("#" + field).input_value() == "" for field in draft)
        saved = api.get(f"/api/personas/{parent_id}/docs").json()
        assert len(saved) == 1 and saved[0]["title"] == "example submitted document"
        if second_id:
            expect(page.locator("#persona-name")).to_have_value("example parent editor B")
            expect(page.locator("#persona-docs")).not_to_contain_text("example submitted document")
            assert api.get(f"/api/personas/{second_id}/docs").json() == []
        page.unroute(pattern, document_request)
        page.locator("#persona-cancel-btn").click()
        assert api.delete("/api/personas/" + parent_id).ok
        if second_id:
            assert api.delete("/api/personas/" + second_id).ok
        cases.append(
            {
                "case": "document Add " + outcome,
                "one_actual_document": True,
                "duplicate_suppressed": True,
                "parent_delete_blocked": True,
                "newer_editor_preserved": outcome in {"newer", "editor-B"},
                "unchanged_and_error_retry_clear": outcome not in {"newer", "editor-B"},
            }
        )

    for operation in ("save", "document"):
        for order in ("write-first", "delete-first"):
            parent_id = fixture(operation + " " + order)
            other_id = fixture("independent " + operation + " " + order)
            edit(parent_id)
            page.locator("#persona-name").fill("example submitted parent update")
            page.locator("#persona-doc-title").fill("example submitted child")
            page.locator("#persona-doc-content").fill("example child text")
            held, forbidden = [], []
            dispatched = []

            def observe_parent_write(request):
                if request.method in {"PATCH", "POST", "DELETE"} and (
                    request.url.endswith(f"/api/personas/{parent_id}")
                    or request.url.endswith(f"/api/personas/{parent_id}/docs")
                ):
                    dispatched.append(request.method)

            page.on("request", observe_parent_write)
            method = (
                "DELETE" if order == "delete-first" else "PATCH" if operation == "save" else "POST"
            )
            target = f"/api/personas/{parent_id}" + ("/docs" if method == "POST" else "")

            def parent_write(route):
                if route.request.method == method:
                    held.append(route)
                    page.evaluate("count => window.__parentWrites = count", len(held))
                elif route.request.method in {"PATCH", "POST", "DELETE"}:
                    forbidden.append(route.request.method)
                    route.continue_()
                else:
                    route.continue_()

            pattern = "**" + target
            page.route(pattern, parent_write)
            write_button = page.locator(
                "#persona-add-btn" if operation == "save" else "#persona-doc-add"
            )
            (remove(parent_id) if order == "delete-first" else write_button).click()
            page.wait_for_function("window.__parentWrites === 1")
            reopen("personas")
            expect(remove(parent_id)).to_be_disabled()
            expect(write_button).to_be_disabled()
            remove(parent_id).dispatch_event("click")
            write_button.dispatch_event("click")
            assert len(held) == 1 and forbidden == [] and dispatched == [method]
            # A different parent may be removed while the first is pending.
            expect(remove(other_id)).to_be_enabled()
            with page.expect_response(
                lambda response: (
                    response.request.method == "DELETE"
                    and response.url.endswith("/api/personas/" + other_id)
                )
            ) as independent:
                remove(other_id).click()
            assert independent.value.ok
            assert not any(row["id"] == other_id for row in api.get("/api/personas").json())
            assert dispatched == [method]
            assert any(row["id"] == parent_id for row in api.get("/api/personas").json())
            if order == "delete-first" and operation == "document":
                assert api.get(f"/api/personas/{parent_id}/docs").json() == []
            response = held[0].fetch()
            assert response.ok
            held[0].fulfill(response=response)
            if order == "delete-first":
                expect(remove(parent_id)).to_have_count(0)
                assert not any(row["id"] == parent_id for row in api.get("/api/personas").json())
            elif operation == "save":
                expect(page.locator("#toast-container .toast.success").last).to_have_text(
                    "persona updated"
                )
                assert (
                    next(row for row in api.get("/api/personas").json() if row["id"] == parent_id)[
                        "name"
                    ]
                    == "example submitted parent update"
                )
            else:
                expect(page.locator("#persona-docs")).to_contain_text("example submitted child")
                assert len(api.get(f"/api/personas/{parent_id}/docs").json()) == 1
            page.unroute(pattern, parent_write)
            page.remove_listener("request", observe_parent_write)
            if page.locator("#persona-cancel-btn").is_visible():
                page.locator("#persona-cancel-btn").click()
            if any(row["id"] == parent_id for row in api.get("/api/personas").json()):
                assert api.delete("/api/personas/" + parent_id).ok
            cases.append(
                {
                    "case": operation + " / parent Delete " + order,
                    "one_owned_request": True,
                    "conflicting_write_blocked": True,
                    "independent_parent_deleted": True,
                    "actual_acknowledgment_readback": True,
                }
            )

    # A real externally removed parent still yields the existing PATCH error contract.
    parent_id = fixture("404 control")
    edit(parent_id)
    page.locator("#persona-name").fill("example disappeared parent update")
    held = []

    def missing_parent(route):
        if route.request.method == "PATCH":
            held.append(route)
            page.evaluate("window.__missingParentPatch = true")
        else:
            route.continue_()

    pattern = f"**/api/personas/{parent_id}"
    page.route(pattern, missing_parent)
    page.locator("#toast-container").evaluate("element => element.replaceChildren()")
    page.locator("#persona-add-btn").click()
    page.wait_for_function("window.__missingParentPatch === true")
    assert api.delete("/api/personas/" + parent_id).ok
    response = held[0].fetch()
    assert response.status == 404
    held[0].fulfill(response=response)
    failures["404"] += 1
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "persona could not be saved"
    )
    expect(page.locator("#persona-add-btn")).to_be_enabled()
    expect(page.locator("#persona-name")).to_have_value("example disappeared parent update")
    assert page.locator("#toast-container .toast.success").count() == 0
    page.unroute(pattern, missing_parent)
    page.locator("#persona-cancel-btn").click()
    cases.append(
        {
            "case": "missing parent PATCH control",
            "actual_404_error": True,
            "draft_retained": True,
            "owner_released": True,
        }
    )
    (destination / "persona-write-owners.json").write_text(json.dumps(cases, indent=2))
    return failures


def persona_token_action_cases(page, api, reopen, destination):
    cases = []
    failures = {"503": 0, "403": 0, "network": 0}
    page.evaluate("""() => {
        window.__settingsClipboardWrites = [];
        Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
            writeText: async text => window.__settingsClipboardWrites.push(text)
        }});
    }""")
    response = api.post(
        "/api/personas", data={"name": "example closure persona", "system_prompt": "example prompt"}
    )
    assert response.ok
    parent_id = response.json()["id"]
    reopen("personas")
    row = page.locator(f'#persona-list .persona-row[data-id="{parent_id}"]')
    row.locator(".row-name").click()
    share = page.locator("#persona-share-btn")
    held = []

    def share_request(route):
        held.append(route)
        page.evaluate("count => window.__shareRequests = count", len(held))

    pattern = f"**/api/personas/{parent_id}/share"
    page.route(pattern, share_request)
    for outcome in ("503", "network"):
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")
        count = len(held) + 1
        share.click()
        page.wait_for_function("count => window.__shareRequests === count", arg=count)
        if outcome == "503":
            held[-1].fulfill(status=503, json={"detail": "synthetic share rejected"})
        else:
            held[-1].abort("failed")
        failures[outcome] += 1
        expect(page.locator("#toast-container .toast.error").last).to_have_text("share failed")
        assert page.evaluate("window.__settingsClipboardWrites.length") == 0
        assert page.locator("#toast-container .toast.success").count() == 0
        cases.append({"case": "share " + outcome, "clipboard_writes": 0, "false_success": False})
    share.click()
    page.wait_for_function("window.__shareRequests === 3")
    reopen("personas")
    share.click()
    page.wait_for_function("window.__shareRequests === 4")
    receipts = []
    for request in held[-2:]:
        response = request.fetch()
        assert response.ok
        receipts.append(response.json()["url"])
        request.fulfill(response=response)
    page.wait_for_function("window.__settingsClipboardWrites.length === 2")
    assert receipts[0] == receipts[1] and receipts[0].startswith("/s/")
    assert (
        page.evaluate("window.__settingsClipboardWrites.map(value => new URL(value).pathname)")
        == receipts
    )
    page.unroute(pattern, share_request)
    cases.append(
        {
            "case": "share held reopening control",
            "equal_valid_receipts": True,
            "clipboard_writes": 2,
            "idempotent_protocol_retained": True,
        }
    )

    duplicate = row.get_by_role("button", name="duplicate", exact=True)
    held = []

    def duplicate_request(route):
        held.append(route)
        page.evaluate("count => window.__duplicateRequests = count", len(held))

    pattern = f"**/api/personas/{parent_id}/duplicate"
    page.route(pattern, duplicate_request)
    for outcome in ("503", "network"):
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")
        count = len(held) + 1
        duplicate.click()
        page.wait_for_function("count => window.__duplicateRequests === count", arg=count)
        if outcome == "503":
            held[-1].fulfill(status=503, json={"detail": "synthetic duplication rejected"})
        else:
            held[-1].abort("failed")
        failures[outcome] += 1
        expect(page.locator("#toast-container .toast.error").last).to_be_visible()
        expect(duplicate).to_be_enabled()
        assert not any(
            record["name"] == "example closure persona copy"
            for record in api.get("/api/personas").json()
        )
        cases.append(
            {"case": "duplicate " + outcome, "no_copy": True, "visible_error_and_retry": True}
        )
    duplicate.click()
    page.wait_for_function("window.__duplicateRequests === 3")
    duplicate.dispatch_event("click")
    reopen("personas")
    expect(duplicate).to_be_disabled()
    duplicate.dispatch_event("click")
    assert len(held) == 3
    response = held[-1].fetch()
    assert response.ok
    held[-1].fulfill(response=response)
    expect(duplicate).to_be_enabled()
    expect(page.locator("#toast-container .toast.success").last).to_have_text("duplicated")
    copies = [
        record
        for record in api.get("/api/personas").json()
        if record["name"] == "example closure persona copy"
    ]
    assert len(copies) == 1
    duplicate.click()
    page.wait_for_function("window.__duplicateRequests === 4")
    response = held[-1].fetch()
    assert response.ok
    held[-1].fulfill(response=response)
    expect(duplicate).to_be_enabled()
    copies = [
        record
        for record in api.get("/api/personas").json()
        if record["name"] == "example closure persona copy"
    ]
    assert len(copies) == 2 and len({record["id"] for record in copies}) == 2
    page.unroute(pattern, duplicate_request)
    page.locator("#persona-cancel-btn").click()
    for record in copies:
        assert api.delete("/api/personas/" + record["id"]).ok
    assert api.delete("/api/personas/" + parent_id).ok
    cases.append(
        {
            "case": "duplicate held and sequential controls",
            "overlapping_posts": 1,
            "sequential_actual_copies": 2,
        }
    )

    for outcome in ("503", "network", "403", "held-success"):
        response = api.post(
            "/api/tokens", data={"name": "example closure token " + outcome, "scopes": ["read"]}
        )
        assert response.ok
        token_id = response.json()["id"]
        reopen("developer")
        revoke = page.locator(f'#token-list button[data-id="{token_id}"]')
        expect(revoke).to_be_visible()
        held, reauth = [], []

        def revoke_request(route):
            held.append(route)
            page.evaluate("count => window.__revokeRequests = count", len(held))

        pattern = f"**/api/tokens/{token_id}"
        page.route(pattern, revoke_request)
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")
        revoke.click()
        page.wait_for_function("window.__revokeRequests === 1")
        revoke.dispatch_event("click")
        reopen("developer")
        expect(revoke).to_be_disabled()
        revoke.dispatch_event("click")
        assert len(held) == 1
        if outcome == "held-success":
            response = held[0].fetch()
            assert response.ok
            held[0].fulfill(response=response)
            expect(revoke).to_have_count(0)
            assert not any(record["id"] == token_id for record in api.get("/api/tokens").json())
            assert page.locator("#toast-container .toast.error").count() == 0
        else:
            if outcome == "network":
                held[0].abort("failed")
            else:
                if outcome == "403":
                    page.route(
                        "**/api/auth/me", lambda route: route.fulfill(json={"enabled": True})
                    )
                    page.route(
                        "**/api/auth/reauth",
                        lambda route: (reauth.append(True), route.fulfill(json={"ok": True})),
                    )
                held[0].fulfill(
                    status=int(outcome), json={"detail": "synthetic token revocation rejected"}
                )
                if outcome == "403":
                    expect(page.locator('.dialog-input[type="password"]')).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(page.locator('.dialog-input[type="password"]')).to_have_count(0)
                    page.unroute("**/api/auth/me")
                    page.unroute("**/api/auth/reauth")
            failures[outcome] += 1
            expect(page.locator("#toast-container .toast.error").last).to_have_text(
                "token could not be revoked"
            )
            expect(revoke).to_be_enabled()
            assert len(held) == 1 and reauth == []
            assert any(record["id"] == token_id for record in api.get("/api/tokens").json())
            assert api.delete("/api/tokens/" + token_id).ok
        page.unroute(pattern, revoke_request)
        cases.append(
            {
                "case": "revoke " + outcome,
                "delete_requests": 1,
                "reauth_posts": 0,
                "saved_state_verified": True,
                "pending_owner_released": True,
            }
        )

    # A successful backend write with an unreadable one-time receipt is an error.
    reopen("developer")
    page.locator("#token-reveal").evaluate(
        "element => { element.textContent = ''; element.style.display = 'none'; }"
    )
    page.locator("#token-name").fill("example parse submitted")
    held = []

    def truncated_token(route):
        if route.request.method == "POST":
            held.append(route)
            page.evaluate("window.__truncatedTokenHeld = true")
        else:
            route.continue_()

    page.route("**/api/tokens", truncated_token)
    page.locator("#toast-container").evaluate("element => element.replaceChildren()")
    button = page.locator("#token-add-btn")
    button.click()
    page.wait_for_function("window.__truncatedTokenHeld === true")
    page.locator("#token-name").fill("example newer parse draft")
    response = held[0].fetch()
    assert response.ok
    token_id = response.json()["id"]
    held[0].fulfill(status=200, content_type="application/json", body='{"id":')
    expect(page.locator("#toast-container .toast.error").last).to_have_text(
        "token could not be created"
    )
    expect(button).to_be_enabled()
    expect(page.locator("#token-name")).to_have_value("example newer parse draft")
    expect(page.locator("#token-reveal")).to_be_hidden()
    expect(page.locator("#token-reveal")).to_have_text("")
    assert page.locator("#toast-container .toast.success").count() == 0
    assert len(held) == 1
    saved = next(record for record in api.get("/api/tokens").json() if record["id"] == token_id)
    assert saved["name"] == "example parse submitted"
    reopen("developer")
    expect(page.locator("#token-list")).to_contain_text("example parse submitted")
    expect(page.locator("#token-name")).to_have_value("example newer parse draft")
    assert len(held) == 1
    page.unroute("**/api/tokens", truncated_token)
    assert api.delete("/api/tokens/" + token_id).ok
    page.evaluate("delete navigator.clipboard; delete window.__settingsClipboardWrites")
    cases.append(
        {
            "case": "truncated successful token receipt",
            "actual_post_count": 1,
            "record_retained": True,
            "newer_draft_retained": True,
            "no_false_reveal_or_success": True,
            "no_automatic_post_retry": True,
        }
    )
    (destination / "persona-token-actions.json").write_text(json.dumps(cases, indent=2))
    return failures


def local_preset_cases(page, reopen, destination):
    cases = []
    failures = {"503": 0, "network": 0}
    state = {
        "presets": [],
        "held": [],
        "writes": [],
        "jobs": {},
        "job_reads": [],
        "held_jobs": [],
        "hold_job": False,
        "hold_status": False,
        "held_status": [],
        "status_reads": 0,
    }
    unexpected = []

    def local_response(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path == "/api/local-models/status":
            state["status_reads"] += 1
            if state["hold_status"]:
                state["held_status"].append(route)
                page.evaluate("n => window.__presetStatusHeld = n", len(state["held_status"]))
            else:
                route.fulfill(
                    json={
                        "ollama": {
                            "installed": True,
                            "running": True,
                            "base_url": "http://127.0.0.1:1",
                        },
                        "hardware": {"ram_gb": 16, "gpus": []},
                        "presets": state["presets"],
                    }
                )
        elif request.method == "GET" and path.startswith("/api/local-models/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            assert job_id in state["jobs"], job_id
            state["job_reads"].append(job_id)
            if state["hold_job"]:
                state["held_jobs"].append(route)
                page.evaluate("n => window.__presetJobHeld = n", len(state["held_jobs"]))
            else:
                route.fulfill(json=state["jobs"][job_id])
        elif request.method == "POST" and path in {
            "/api/local-models/download_model",
            "/api/local-models/serve",
            "/api/local-models/delete",
        }:
            model = request.post_data_json["model"]
            state["writes"].append({"path": path, "model": model})
            if model == state["other"]:
                assert path == "/api/local-models/serve"
                route.fulfill(json={"ok": True, "model": model})
            else:
                assert model == state["model"]
                state["held"].append(route)
                page.evaluate("n => window.__presetHeld = n", len(state["held"]))
        else:
            unexpected.append({"method": request.method, "path": path})
            route.fulfill(status=503, json={"detail": "unexpected synthetic model route blocked"})

    page.route("**/api/local-models/**", local_response)

    def clear():
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    def button(action, model=None):
        return page.locator(f'[data-local-{action}="{model or state["model"]}"]')

    def ready():
        expect(page.locator("#s-local-ollama")).to_contain_text("Ollama: running")
        expect(page.locator("#s-local-presets")).to_contain_text(state["model"])

    def prepare(action, outcome):
        state.update(
            model=f"example-preset-{action}-{outcome}",
            other=f"example-independent-{action}-{outcome}",
            held=[],
            writes=[],
            jobs={},
            job_reads=[],
            held_jobs=[],
            hold_job=False,
            hold_status=False,
            held_status=[],
            status_reads=0,
        )
        state["presets"] = [
            {
                "model": state["model"],
                "label": "example preset",
                "installed": action != "download",
                "fit": "fits_cpu",
                "fit_reason": "example fit",
            },
            {
                "model": state["other"],
                "label": "example independent",
                "installed": True,
                "fit": "fits_cpu",
                "fit_reason": "example fit",
            },
        ]
        page.evaluate(
            "window.__presetHeld = 0; window.__presetJobHeld = 0; window.__presetStatusHeld = 0"
        )
        reopen("models")
        ready()
        clear()

    def begin(action):
        button(action).click()
        if action == "remove":
            expect(page.locator("[data-dialog-confirm]")).to_be_visible()
            page.locator("[data-dialog-confirm]").click()
        page.wait_for_function("window.__presetHeld === 1")

    def locked(action):
        row = page.locator(f'#s-local-presets [data-local-model="{state["model"]}"]')
        expected = {"download": "queued", "serve": "serving...", "remove": "removing..."}[action]
        expect(button(action)).to_be_disabled()
        expect(button(action)).to_have_text(expected)
        expect(row.locator("[data-local-state]")).to_have_text(expected)
        for control in row.locator("button").all():
            expect(control).to_be_disabled()
            control.dispatch_event("click")
        page.wait_for_timeout(50)
        assert len(state["held"]) == 1
        assert page.locator("[data-dialog-confirm]").count() == 0

    def success(action, route):
        if action == "download":
            state["presets"][0]["installed"] = True
            job_id = "example-preset-job"
            state["jobs"][job_id] = {"id": job_id, "status": "done", "model": state["model"]}
            route.fulfill(json={"id": job_id, "status": "queued", "model": state["model"]})
        else:
            if action == "remove":
                state["presets"][0]["installed"] = False
            route.fulfill(json={"ok": True, "model": state["model"]})
        expect(page.locator("#toast-container .toast.success").last).to_be_visible()
        expect(
            button({"download": "remove", "remove": "download", "serve": "serve"}[action])
        ).to_be_enabled()
        ready()

    try:
        # All model endpoints are intercepted; these prove client ownership, not real jobs.
        for action in ("download", "serve", "remove"):
            for outcome in ("reopen-success", "reopen-503", "reopen-network", "active-success"):
                prepare(action, outcome)
                begin(action)
                locked(action)
                button("serve", state["other"]).click()
                expect(page.locator("#toast-container .toast.success").last).to_contain_text(
                    "selected"
                )
                ready()
                locked(action)
                clear()
                if outcome != "active-success":
                    reopen("models")
                    ready()
                    locked(action)
                if outcome.endswith("503") or outcome.endswith("network"):
                    if outcome.endswith("503"):
                        state["held"][0].fulfill(
                            status=503, json={"detail": "synthetic example local action rejected"}
                        )
                        failures["503"] += 1
                        expect(page.locator("#toast-container .toast.error").last).to_have_text(
                            "synthetic example local action rejected"
                        )
                    else:
                        state["held"][0].abort("failed")
                        failures["network"] += 1
                        expect(page.locator("#toast-container .toast.error").last).to_be_visible()
                    expect(button(action)).to_be_enabled()
                    clear()
                    button(action).click()
                    if action == "remove":
                        page.locator("[data-dialog-confirm]").click()
                    page.wait_for_function("window.__presetHeld === 2")
                    success(action, state["held"][1])
                    target_count = 2
                else:
                    success(action, state["held"][0])
                    target_count = 1
                page.wait_for_load_state("networkidle")
                assert (
                    sum(write["model"] == state["model"] for write in state["writes"])
                    == target_count
                )
                assert sum(write["model"] == state["other"] for write in state["writes"]) == 1
                cases.append(
                    {
                        "action": action,
                        "outcome": outcome,
                        "overlapping_target_posts": 1,
                        "completed_retry_posts": target_count - 1,
                        "independent_model_posts": 1,
                        "current_busy_controls_retained": True,
                        "terminal_release": True,
                        "mock_model_dispatch_only": True,
                    }
                )

        # A queued/running job retains the claim until its mocked terminal response.
        for terminal in ("done", "error", "network"):
            prepare("download", "poll-" + terminal)
            state["hold_job"] = True
            begin("download")
            job_id = "example-preset-progress"
            state["jobs"][job_id] = {"id": job_id, "status": "running", "model": state["model"]}
            state["held"][0].fulfill(
                json={"id": job_id, "status": "queued", "model": state["model"]}
            )
            page.wait_for_function("window.__presetJobHeld === 1")
            reopen("models")
            ready()
            locked("download")
            state["held_jobs"][0].fulfill(json=state["jobs"][job_id])
            expect(button("download")).to_have_text("pulling...")
            page.wait_for_function("window.__presetJobHeld === 2")
            reopen("models")
            ready()
            expect(button("download")).to_be_disabled()
            expect(button("download")).to_have_text("pulling...")
            button("download").dispatch_event("click")
            assert len(state["held"]) == 1
            state["hold_job"] = False
            if terminal == "network":
                state["held_jobs"][1].abort("failed")
                failures["network"] += 1
                expect(button("download")).to_be_enabled()
            elif terminal == "error":
                state["held_jobs"][1].fulfill(
                    json={
                        "id": job_id,
                        "status": "error",
                        "model": state["model"],
                        "error": "synthetic example job rejected",
                    }
                )
                expect(page.locator("#toast-container .toast.error").last).to_have_text(
                    "synthetic example job rejected"
                )
                expect(button("download")).to_be_enabled()
            else:
                state["presets"][0]["installed"] = True
                state["held_jobs"][1].fulfill(
                    json={"id": job_id, "status": "done", "model": state["model"]}
                )
                expect(button("remove")).to_be_enabled()
            if terminal != "done":
                clear()
                button("download").click()
                page.wait_for_function("window.__presetHeld === 2")
                success("download", state["held"][1])
            page.wait_for_load_state("networkidle")
            assert len(state["job_reads"]) == (2 if terminal == "done" else 3)
            cases.append(
                {
                    "action": "download",
                    "outcome": "poll-" + terminal,
                    "queued_and_running_reopen_locked": True,
                    "job_reads": len(state["job_reads"]),
                    "overlapping_posts": 1,
                    "terminal_release_and_retry": True,
                    "mock_jobs_only": True,
                }
            )

        # Cancel restores the disabled origin after it is enabled; newer focus survives.
        for focus_case in ("origin", "other-field"):
            prepare("remove", "cancel-" + focus_case)
            if focus_case == "origin":
                button("remove").focus()
                button("remove").click()
            else:
                page.locator("#s-local-custom").fill("example cancel focus draft")
                page.locator("#s-local-custom").focus()
                button("remove").dispatch_event("click")
            expect(page.locator("[data-dialog-cancel]")).to_be_focused()
            expect(button("remove")).to_be_disabled()
            page.keyboard.press("Escape")
            expect(page.locator("[data-dialog-confirm]")).to_have_count(0)
            expect(button("remove")).to_be_enabled()
            expect(
                button("remove") if focus_case == "origin" else page.locator("#s-local-custom")
            ).to_be_focused()
            assert state["writes"] == []
            cases.append(
                {
                    "action": "remove",
                    "outcome": "cancel-" + focus_case,
                    "mutation_posts": 0,
                    "focus_restored_without_stealing_newer_control": True,
                }
            )
        # A current status response may replace the row while confirmation owns focus.
        for focus_case in ("origin", "other-field", "newer-pane"):
            prepare("remove", "held-status-" + focus_case)
            page.wait_for_load_state("networkidle")
            prior_reads = state["status_reads"]
            original = button("remove").element_handle()
            state["hold_status"] = True
            page.locator("#s-local-refresh-btn").click()
            page.wait_for_function("window.__presetStatusHeld === 1")
            if focus_case == "other-field":
                page.locator("#s-local-custom").fill("example held status focus draft")
                page.locator("#s-local-custom").focus()
                button("remove").dispatch_event("click")
            else:
                button("remove").focus()
                button("remove").click()
            expect(page.locator("[data-dialog-cancel]")).to_be_focused()
            expect(button("remove")).to_be_disabled()
            if focus_case == "newer-pane":
                navigation = page.locator('.s-nav-item[data-pane="general"]')
                navigation.dispatch_event("click")
                navigation.focus()
                expect(page.locator("#s-pane-general")).to_be_visible()
            state["hold_status"] = False
            state["held_status"][0].fulfill(
                json={
                    "ollama": {
                        "installed": True,
                        "running": True,
                        "base_url": "http://127.0.0.1:2",
                    },
                    "hardware": {"ram_gb": 16, "gpus": []},
                    "presets": state["presets"],
                }
            )
            if focus_case == "newer-pane":
                page.wait_for_load_state("networkidle")
            else:
                expect(page.locator("#s-local-ollama")).to_contain_text("http://127.0.0.1:2")
                assert not original.evaluate("element => element.isConnected")
            expect(button("remove")).to_be_disabled()
            expect(button("serve", state["other"])).to_be_enabled()
            if focus_case == "newer-pane":
                page.locator(".dialog-overlay").dispatch_event("keydown", {"key": "Escape"})
            else:
                page.keyboard.press("Escape")
            expect(page.locator("[data-dialog-confirm]")).to_have_count(0)
            expect(button("remove")).to_be_enabled()
            if focus_case == "origin":
                expect(button("remove")).to_be_focused()
            elif focus_case == "other-field":
                expect(page.locator("#s-local-custom")).to_be_focused()
                expect(page.locator("#s-local-custom")).to_have_value(
                    "example held status focus draft"
                )
            else:
                expect(navigation).to_be_focused()
                expect(page.locator("#s-pane-general")).to_be_visible()
                assert not button("remove").evaluate(
                    "element => element === document.activeElement"
                )
            assert len(state["held_status"]) == 1 and state["status_reads"] == prior_reads + 1
            assert state["writes"] == []
            cases.append(
                {
                    "action": "remove",
                    "outcome": "held-status-cancel-" + focus_case,
                    "held_current_status_reads": 1,
                    "mutation_posts": 0,
                    "current_row_replaced_and_focus_restored": focus_case == "origin",
                    "other_field_or_navigation_preserved": focus_case != "origin",
                    "other_model_control_available": True,
                }
            )
        # Removing a preset rechecks the owner after the asynchronous confirmation.
        prepare("remove", "confirmation-race")
        button("remove").click()
        expect(page.locator("[data-dialog-confirm]")).to_be_visible()
        expect(button("remove")).to_be_disabled()
        button("remove").dispatch_event("click")
        assert page.locator("[data-dialog-confirm]").count() == 1
        button("serve").dispatch_event("click")
        page.wait_for_function("window.__presetHeld === 1")
        page.locator("[data-dialog-confirm]").click()
        reopen("models")
        ready()
        locked("serve")
        assert [write["path"] for write in state["writes"]] == ["/api/local-models/serve"]
        success("serve", state["held"][0])
        clear()
        button("remove").click()
        page.keyboard.press("Escape")
        expect(page.locator("[data-dialog-confirm]")).to_have_count(0)
        expect(button("remove")).to_be_enabled()
        assert len(state["held"]) == 1
        cases.append(
            {
                "action": "remove",
                "outcome": "confirmation-race-and-cancel",
                "competing_serve_posts": 1,
                "remove_posts": 0,
                "duplicate_dialogs": 0,
                "confirmation_recheck": True,
            }
        )
        assert unexpected == [], unexpected
        (destination / "local-preset-pending.json").write_text(
            json.dumps(
                {
                    "cases": cases,
                    "unexpected_model_routes": unexpected,
                    "all_model_routes_mocked": True,
                    "real_jobs_processes_removals_claimed": False,
                },
                indent=2,
            )
        )
    finally:
        page.unroute("**/api/local-models/**", local_response)
    return failures


def developer_focus_webhook_cases(page, api, pane, reopen, destination):
    cases = []
    failures = {"503": 0, "403": 0, "network": 0}

    def clear():
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    response = api.post("/api/tokens", data={"name": "example focus revoke", "scopes": ["read"]})
    assert response.ok
    token_id = response.json()["id"]
    hooks = []
    for label in ("a", "b"):
        response = api.post(
            "/api/webhooks",
            data={
                "name": "example pending webhook " + label,
                "url": "http://127.0.0.1:1/example",
                "events": ["message"],
            },
        )
        assert response.ok
        hooks.append(response.json()["id"])
    token_baseline = {record["id"] for record in api.get("/api/tokens").json()}
    held, reauth = [], []

    def token_request(route):
        if route.request.method == "POST" or route.request.method == "DELETE":
            held.append(route)
            page.evaluate("n => window.__focusTokenHeld = n", len(held))
        else:
            route.continue_()

    def owner_status(route):
        route.fulfill(json={"enabled": True})

    def owner_confirm(route):
        reauth.append(True)
        route.fulfill(json={"ok": True})

    page.route("**/api/tokens", token_request)
    page.route(f"**/api/tokens/{token_id}", token_request)
    page.route("**/api/auth/me", owner_status)
    page.route("**/api/auth/reauth", owner_confirm)
    try:
        for action in ("generate", "revoke"):
            for focus_case in ("origin", "newer-field", "newer-pane"):
                reopen("developer")
                expect(page.locator("#token-list")).to_contain_text("example focus revoke")
                clear()
                page.locator("#token-name").fill("example cancel focus draft")
                read_scope = page.locator('[data-token-scope="read"]')
                if "active" not in (read_scope.get_attribute("class") or "").split():
                    read_scope.click()
                button = (
                    page.locator("#token-add-btn")
                    if action == "generate"
                    else page.locator(f'#token-list [data-token-revoke][data-id="{token_id}"]')
                )
                button.focus()
                expected = len(held) + 1
                button.click()
                page.wait_for_function("n => window.__focusTokenHeld === n", arg=expected)
                expect(button).to_be_disabled()
                if focus_case == "newer-field":
                    page.locator("#token-name").focus()
                elif focus_case == "newer-pane":
                    pane("general")
                held[-1].fulfill(
                    status=403, json={"detail": "synthetic owner confirmation required"}
                )
                failures["403"] += 1
                expect(page.locator('.dialog-input[type="password"]')).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator('.dialog-input[type="password"]')).to_have_count(0)
                expect(button).to_be_enabled()
                expect(page.locator("#toast-container .toast.error").last).to_have_text(
                    "synthetic owner confirmation required"
                    if action == "generate"
                    else "token could not be revoked"
                )
                if focus_case == "origin":
                    expect(button).to_be_focused()
                elif focus_case == "newer-field":
                    expect(page.locator("#token-name")).to_be_focused()
                else:
                    expect(page.locator("#s-pane-general")).to_be_visible()
                    expect(page.locator('.s-nav-item[data-pane="general"]')).to_be_focused()
                assert len(held) == expected and reauth == []
                assert {record["id"] for record in api.get("/api/tokens").json()} == token_baseline
                expect(page.locator("#token-name")).to_have_value("example cancel focus draft")
                cases.append(
                    {
                        "action": "token-" + action,
                        "focus_case": focus_case,
                        "action_requests": 1,
                        "reauth_posts": 0,
                        "actual_records_retained": True,
                        "draft_retained": True,
                        "focus_contract_preserved": True,
                    }
                )
        # Valid current-owner retry uses the actual owned API, with its one-time result hidden.
        reopen("developer")
        clear()
        page.locator("#token-name").fill("example successful focus retry")
        button = page.locator("#token-add-btn")
        expected = len(held) + 1
        button.click()
        page.wait_for_function("n => window.__focusTokenHeld === n", arg=expected)
        response = held[-1].fetch()
        assert response.ok
        created_id = response.json()["id"]
        held[-1].fulfill(response=response)
        expect(button).to_be_enabled()
        expect(page.locator("#token-list")).to_contain_text("example successful focus retry")
        expect(page.locator("#token-reveal")).to_be_visible()
        page.locator("#token-reveal").evaluate(
            "element => { element.textContent = ''; element.style.display = 'none'; }"
        )
        assert api.delete("/api/tokens/" + created_id).ok
        cases.append(
            {
                "action": "token-generate",
                "focus_case": "actual-success-after-cancel",
                "actual_post_count": 1,
                "one_time_ack_preserved": True,
                "receipt_hidden_before_capture": True,
            }
        )
    finally:
        page.unroute("**/api/tokens", token_request)
        page.unroute(f"**/api/tokens/{token_id}", token_request)
        page.unroute("**/api/auth/me", owner_status)
        page.unroute("**/api/auth/reauth", owner_confirm)
        assert api.delete("/api/tokens/" + token_id).ok

    held = []

    def webhook_test(route):
        assert route.request.method == "POST"
        held.append(route)
        page.evaluate("n => window.__webhookTestHeld = n", len(held))

    def button(wid):
        return page.locator(f'#webhook-list [data-webhook-test][data-id="{wid}"]')

    def begin(wid):
        prior = len(held)
        button(wid).click()
        page.wait_for_function("n => window.__webhookTestHeld === n", arg=prior + 1)
        expect(button(wid)).to_be_disabled()
        expect(button(wid)).to_have_text("…")
        return prior

    page.route("**/api/webhooks/*/test", webhook_test)
    try:
        a, b = hooks
        reopen("developer")
        expect(button(a)).to_be_enabled()
        clear()
        index = begin(a)
        box = button(a).bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        button(a).dispatch_event("click")
        reopen("developer")
        expect(button(a)).to_be_disabled()
        expect(button(a)).to_have_text("…")
        button(a).dispatch_event("click")
        expect(button(b)).to_be_enabled()
        other = begin(b)
        held[other].fulfill(json={"status": "ok", "error": ""})
        expect(button(b)).to_be_enabled()
        expect(button(a)).to_be_disabled()
        assert len(held) == index + 2
        assert held[index].request.url != held[other].request.url
        clear()
        held[index].fulfill(json={"status": "ok", "error": ""})
        expect(button(a)).to_be_enabled()
        expect(page.locator("#toast-container .toast.success").last).to_have_text(
            "webhook delivered ✓"
        )
        cases.append(
            {
                "action": "webhook-test",
                "case": "held-reopen-current-controls",
                "same_id_posts": 1,
                "independent_id_posts": 1,
                "pointer_and_programmatic_overlap_suppressed": True,
                "current_busy_label": True,
                "no_outbound_delivery": True,
            }
        )
        for outcome in (
            "503-status-ok",
            "503-detail",
            "network",
            "logical-error",
            "success",
            "sequential-success",
        ):
            clear()
            index = begin(a)
            if outcome == "network":
                held[index].abort("failed")
                failures["network"] += 1
            elif outcome.startswith("503"):
                held[index].fulfill(
                    status=503,
                    json={"status": "ok", "error": ""}
                    if outcome.endswith("status-ok")
                    else {"detail": "synthetic webhook test rejected"},
                )
                failures["503"] += 1
            else:
                held[index].fulfill(
                    json={"status": "error", "error": "example provider failure"}
                    if outcome == "logical-error"
                    else {"status": "ok", "error": ""}
                )
            expect(button(a)).to_be_enabled()
            if outcome.startswith("503") or outcome == "network":
                expect(page.locator("#toast-container .toast.error").last).to_have_text(
                    "test failed"
                )
                assert page.locator("#toast-container .toast.success").count() == 0
            elif outcome == "logical-error":
                expect(page.locator("#toast-container .toast.error").last).to_have_text(
                    "failed: example provider failure"
                )
            else:
                expect(page.locator("#toast-container .toast.success").last).to_have_text(
                    "webhook delivered ✓"
                )
            assert len(held) == index + 1
            assert {record["id"] for record in api.get("/api/webhooks").json()} >= set(hooks)
            cases.append(
                {
                    "action": "webhook-test",
                    "case": outcome,
                    "mocked_test_posts": 1,
                    "exact_success_or_error": True,
                    "pending_released": True,
                    "actual_records_retained": True,
                    "no_outbound_delivery": True,
                }
            )
    finally:
        page.unroute("**/api/webhooks/*/test", webhook_test)
        for wid in hooks:
            assert api.delete("/api/webhooks/" + wid).ok
    (destination / "developer-focus-webhook.json").write_text(json.dumps(cases, indent=2))
    return failures


def webhook_mutual_action_cases(page, api, reopen, destination):
    cases = []
    failures = {"503": 0, "network": 0}
    tests, deletes, fixtures = [], [], []
    page.evaluate("window.__mutualWebhookTests = 0; window.__mutualWebhookDeletes = 0")

    def clear():
        page.locator("#toast-container").evaluate("element => element.replaceChildren()")

    def create(label):
        response = api.post(
            "/api/webhooks",
            data={
                "name": "example mutual webhook " + label,
                "url": "http://127.0.0.1:1/example",
                "events": ["message"],
            },
        )
        assert response.ok
        wid = response.json()["id"]
        fixtures.append(wid)
        return wid

    def control(wid, action):
        marker = "test" if action == "test" else "remove"
        return page.locator(f'#webhook-list [data-webhook-{marker}][data-id="{wid}"]')

    def hold_test(route):
        assert route.request.method == "POST"
        tests.append(route)
        page.evaluate("count => window.__mutualWebhookTests = count", len(tests))

    def webhook_request(route):
        if route.request.url.endswith("/test"):
            hold_test(route)
        elif route.request.method == "DELETE":
            deletes.append(route)
            page.evaluate("count => window.__mutualWebhookDeletes = count", len(deletes))
        else:
            route.continue_()

    def begin(wid, action):
        writes = tests if action == "test" else deletes
        prior = len(writes)
        control(wid, action).click()
        marker = "__mutualWebhookTests" if action == "test" else "__mutualWebhookDeletes"
        page.wait_for_function(f"count => window.{marker} === count", arg=prior + 1)
        expect(control(wid, "test")).to_be_disabled()
        expect(control(wid, "delete")).to_be_disabled()
        expect(control(wid, "test")).to_have_text("…" if action == "test" else "test")
        return prior

    def blocked(wid, action):
        before = (len(tests), len(deletes))
        button = control(wid, action)
        expect(button).to_be_disabled()
        button.scroll_into_view_if_needed()
        box = button.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        button.dispatch_event("click")
        page.evaluate(
            """({wid, action}) => {
              const marker = action === 'test' ? 'test' : 'remove';
              const button = document.querySelector(`#webhook-list [data-webhook-${marker}][data-id="${wid}"]`);
              return action === 'test' ? window._testWebhook(button) : window._rmWebhook(button);
            }""",
            {"wid": wid, "action": action},
        )
        assert (len(tests), len(deletes)) == before

    def settle_delete(index):
        response = deletes[index].fetch()
        assert response.ok
        deletes[index].fulfill(response=response)

    def present(wid):
        return any(record["id"] == wid for record in api.get("/api/webhooks").json())

    page.route("**/api/webhooks/**", webhook_request)
    try:
        for action in ("test", "delete"):
            opposite = "delete" if action == "test" else "test"
            for outcome in ("success", "503", "network"):
                wid = create(action + " " + outcome)
                reopen("developer")
                expect(control(wid, "test")).to_be_enabled()
                expect(control(wid, "delete")).to_be_enabled()
                clear()
                before = (len(tests), len(deletes))
                index = begin(wid, action)
                blocked(wid, opposite)
                draft = "example editable mutual draft " + action + " " + outcome
                page.locator("#wh-name").fill(draft)
                prior_row_control = control(wid, "test").element_handle()
                reopen("developer")
                page.wait_for_function("element => !element.isConnected", arg=prior_row_control)
                expect(control(wid, "test")).to_be_disabled()
                expect(control(wid, "delete")).to_be_disabled()
                expect(control(wid, "test")).to_have_text("…" if action == "test" else "test")
                blocked(wid, opposite)
                page.locator("#wh-name").focus()
                assert present(wid)
                writes = tests if action == "test" else deletes
                if outcome == "network":
                    writes[index].abort("failed")
                    failures["network"] += 1
                elif outcome == "503":
                    writes[index].fulfill(
                        status=503, json={"detail": "synthetic mutual webhook action rejected"}
                    )
                    failures["503"] += 1
                elif action == "test":
                    writes[index].fulfill(json={"status": "ok", "error": ""})
                else:
                    settle_delete(index)
                if action == "delete" and outcome == "success":
                    expect(control(wid, "test")).to_have_count(0)
                    expect(control(wid, "delete")).to_have_count(0)
                    assert not present(wid)
                else:
                    expect(control(wid, "test")).to_be_enabled()
                    expect(control(wid, "test")).to_have_text("test")
                    expect(control(wid, "delete")).to_be_enabled()
                    assert present(wid)
                    if outcome != "success":
                        expect(page.locator("#toast-container .toast.error").last).to_have_text(
                            "test failed" if action == "test" else "webhook could not be removed"
                        )
                    else:
                        expect(page.locator("#toast-container .toast.success").last).to_have_text(
                            "webhook delivered ✓"
                        )
                expect(page.locator("#wh-name")).to_have_value(draft)
                expect(page.locator("#wh-name")).to_be_focused()
                assert (len(tests), len(deletes)) == (
                    before[0] + (action == "test"),
                    before[1] + (action == "delete"),
                )
                if outcome != "success":
                    assert page.locator("#toast-container .toast.success").count() == 0
                    clear()
                    retry = begin(wid, action)
                    if action == "test":
                        tests[retry].fulfill(json={"status": "ok", "error": ""})
                        expect(control(wid, "test")).to_be_enabled()
                        expect(control(wid, "delete")).to_be_enabled()
                        expect(page.locator("#toast-container .toast.success").last).to_have_text(
                            "webhook delivered ✓"
                        )
                        assert present(wid)
                    else:
                        settle_delete(retry)
                        expect(control(wid, "delete")).to_have_count(0)
                        assert not present(wid)
                cases.append(
                    {
                        "action": action,
                        "outcome": outcome,
                        "case": "same-ID-mutual-claim-current-and-reopen",
                        "conflicting_pointer_event_and_direct_calls": 0,
                        "original_action_requests": 1,
                        "retry_requests": outcome != "success",
                        "current_controls_release_or_removed": True,
                        "actual_record_matches_action": True,
                        "newer_draft_and_focus_retained": True,
                        "all_Test_POSTs_intercepted_before_dispatch": True,
                    }
                )
        for first in ("test", "delete"):
            a, b = create("independent a " + first), create("independent b " + first)
            reopen("developer")
            expect(control(a, "test")).to_be_enabled()
            expect(control(b, "delete")).to_be_enabled()
            clear()
            index = begin(a, first)
            other_action = "delete" if first == "test" else "test"
            expect(control(b, other_action)).to_be_enabled()
            other = begin(b, other_action)
            if other_action == "test":
                tests[other].fulfill(json={"status": "ok", "error": ""})
                expect(control(b, "test")).to_be_enabled()
                expect(control(b, "delete")).to_be_enabled()
                expect(page.locator("#toast-container .toast.success").last).to_have_text(
                    "webhook delivered ✓"
                )
            else:
                settle_delete(other)
                expect(control(b, "delete")).to_have_count(0)
                assert not present(b)
            expect(control(a, "test")).to_be_disabled()
            expect(control(a, "delete")).to_be_disabled()
            if first == "test":
                tests[index].fulfill(json={"status": "ok", "error": ""})
                expect(control(a, "test")).to_be_enabled()
                expect(control(a, "delete")).to_be_enabled()
            else:
                settle_delete(index)
                expect(control(a, "delete")).to_have_count(0)
                assert not present(a)
            cases.append(
                {
                    "action": first,
                    "case": "different-ID-actions-independent",
                    "test_POSTs": 1,
                    "actual_DELETEs": 1,
                    "other_ID_completes_while_origin_pending": True,
                    "all_Test_POSTs_intercepted_before_dispatch": True,
                }
            )
        wid = create("completed sequential actions")
        reopen("developer")
        expect(control(wid, "test")).to_be_enabled()
        before = (len(tests), len(deletes))
        for _ in range(2):
            clear()
            index = begin(wid, "test")
            tests[index].fulfill(json={"status": "ok", "error": ""})
            expect(control(wid, "test")).to_be_enabled()
            expect(control(wid, "delete")).to_be_enabled()
            expect(page.locator("#toast-container .toast.success").last).to_have_text(
                "webhook delivered ✓"
            )
        index = begin(wid, "delete")
        settle_delete(index)
        expect(control(wid, "delete")).to_have_count(0)
        assert not present(wid)
        assert (len(tests) - before[0], len(deletes) - before[1]) == (2, 1)
        cases.append(
            {
                "case": "completed-sequential-Test-Test-Delete",
                "Test_POSTs": 2,
                "actual_DELETEs": 1,
                "all_Test_POSTs_intercepted_before_dispatch": True,
                "actual_record_removed": True,
            }
        )
    finally:
        page.unroute("**/api/webhooks/**", webhook_request)
        remaining = {record["id"] for record in api.get("/api/webhooks").json()}
        for wid in fixtures:
            if wid in remaining:
                assert api.delete("/api/webhooks/" + wid).ok
    assert len(cases) == 9
    assert failures == {"503": 2, "network": 2}
    (destination / "webhook-mutual-actions.json").write_text(json.dumps(cases, indent=2))
    return failures


def exercise(page, api, endpoint, destination):
    events = {"pageerrors": [], "console_errors": [], "writes": []}
    page.on("pageerror", lambda error: events["pageerrors"].append(str(error)))
    page.on(
        "console",
        lambda message: (
            events["console_errors"].append(message.text) if message.type == "error" else None
        ),
    )
    page.on(
        "request",
        lambda request: (
            events["writes"].append({"url": request.url, "method": request.method})
            if request.method in {"PATCH", "PUT", "POST", "DELETE"}
            else None
        ),
    )
    page.goto("/?view=today", wait_until="networkidle")
    page.locator("#today-settings").click()
    permission_first_read_case(page, api, events, destination)

    def assert_layout(locale=False):
        bounds = page.evaluate(
            """(locale) => {
                const modal = document.querySelector('#settings-modal .s-modal').getBoundingClientRect();
                const outside = [];
                if (locale) {
                    document.querySelectorAll('.locale-segmented button').forEach(button => {
                        const box = button.getBoundingClientRect();
                        const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
                        let node;
                        while ((node = walker.nextNode())) {
                            if (!node.textContent.trim()) continue;
                            const range = document.createRange();
                            range.selectNodeContents(node);
                            for (const text of range.getClientRects()) {
                                if (text.left < box.left - 1 || text.right > box.right + 1 ||
                                    text.top < box.top - 1 || text.bottom > box.bottom + 1) {
                                    outside.push({label: button.textContent.trim(),
                                        button: box.toJSON(), text: text.toJSON()});
                                }
                            }
                        }
                    });
                }
                return {modal: modal.toJSON(), viewport: {width: innerWidth, height: innerHeight}, outside};
            }""",
            locale,
        )
        box, viewport = bounds["modal"], bounds["viewport"]
        assert box["left"] >= -1 and box["right"] <= viewport["width"] + 1, bounds
        assert box["top"] >= -1 and box["bottom"] <= viewport["height"] + 1, bounds
        assert bounds["outside"] == [], bounds

    assert_layout()

    def pane(name):
        page.locator(f'.s-nav-item[data-pane="{name}"]').click()
        expect(page.locator(f"#s-pane-{name}")).to_be_visible()
        assert_layout(locale=name == "notifications")

    def close_and_reopen(name):
        page.locator("#settings-modal-close").click()
        expect(page.locator("#today-settings")).to_be_focused()
        page.locator("#today-settings").click()
        pane(name)

    # A disposed language read cannot update the latest opening or clear its draft.
    pending = []
    old_settings = api.get("/api/settings").json() | {"region": "TW"}

    def delayed_settings(route):
        if route.request.method == "GET" and not pending:
            pending.append(route)
            page.evaluate("window.__settingsPaneReadReady = true")
        else:
            route.continue_()

    page.route("**/api/settings", delayed_settings)
    pane("notifications")
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "true")
    page.wait_for_function("window.__settingsPaneReadReady === true")
    assert len(pending) == 1
    pane("home")
    pane("notifications")
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    pending[0].fulfill(json=old_settings)
    expect(page.locator("#s-region-trigger")).to_have_attribute("data-value", "")
    page.unroute("**/api/settings", delayed_settings)
    clock = page.locator('[data-locale-format="clock_format"][data-value="24"]')
    clock.click()
    close_and_reopen("notifications")
    expect(clock).to_have_attribute("aria-checked", "true")
    expect(page.locator("#locale-settings-load-state")).to_contain_text("unsaved")
    page.locator("#s-locale-save").click()
    expect(page.locator("#locale-settings-workbench")).to_have_attribute("aria-busy", "false")
    expect(page.locator("#s-locale-save")).to_be_focused()
    assert api.get("/api/settings").json()["clock_format"] == "24"

    # Reopening Home keeps edits and still has exactly one save listener.
    pane("home")
    expect(page.locator("#home-settings-workbench")).to_have_attribute("aria-busy", "false")
    page.locator('[data-home-density="compact"]').click()
    close_and_reopen("home")
    expect(page.locator('[data-home-density="compact"]')).to_have_attribute("aria-checked", "true")
    before = sum(
        item["method"] == "PUT" and item["url"].endswith("/api/today/preferences")
        for item in events["writes"]
    )
    page.locator("#home-settings-save").click()
    expect(page.locator("#home-settings-save-state")).to_have_text("saved just now")
    expect(page.locator("#home-settings-save")).to_be_focused()
    assert api.get("/api/today/preferences").json()["density"] == "compact"
    assert (
        sum(
            item["method"] == "PUT" and item["url"].endswith("/api/today/preferences")
            for item in events["writes"]
        )
        == before + 1
    )

    # Successful saves remain owned by their pane when it closes and reopens.
    held_saves = {}
    for name, route_url, method, workbench, button, value in (
        (
            "home",
            "**/api/today/preferences",
            "PUT",
            "home-settings-workbench",
            "home-settings-save",
            "comfortable",
        ),
        (
            "notifications",
            "**/api/settings",
            "PATCH",
            "locale-settings-workbench",
            "s-locale-save",
            "12",
        ),
    ):
        pane(name)
        expect(page.locator(f"#{workbench}")).to_have_attribute("aria-busy", "false")
        choice = (
            f'[data-home-density="{value}"]'
            if name == "home"
            else f'[data-locale-format="clock_format"][data-value="{value}"]'
        )
        page.locator(choice).click()
        held = []

        def hold_pane_save(route, request, expected_method=method):
            if request.method == expected_method:
                response = route.fetch()
                assert response.ok
                held.append((route, response))
                page.evaluate("window.__settingsPaneHeldSaveReady = true")
            else:
                route.continue_()

        page.evaluate("window.__settingsPaneHeldSaveReady = false")
        page.route(route_url, hold_pane_save)
        page.locator(f"#{button}").click()
        page.wait_for_function("window.__settingsPaneHeldSaveReady === true")
        expect(page.locator(f"#{button}")).to_be_disabled()
        close_and_reopen(name)
        expect(page.locator(f"#{workbench}")).to_have_attribute("aria-busy", "true")
        expect(page.locator(f"#{button}")).to_be_disabled()
        expect(page.locator(choice)).to_have_attribute("aria-checked", "true")
        pane("general")
        held[0][0].fulfill(response=held[0][1])
        expect(page.locator(f"#{workbench}")).to_have_attribute("aria-busy", "false")
        expect(page.locator('.s-nav-item[data-pane="general"]')).to_be_focused()
        assert len(held) == 1
        page.unroute(route_url, hold_pane_save)
        pane(name)
        expect(page.locator(f"#{workbench}")).to_have_attribute("aria-busy", "false")
        expect(page.locator(choice)).to_have_attribute("aria-checked", "true")
        saved = api.get("/api/today/preferences" if name == "home" else "/api/settings").json()
        assert saved["density" if name == "home" else "clock_format"] == value
        held_saves[name] = {"writes": len(held), "saved": value, "focus": "general"}
    (destination / "pending-save-lifecycle.json").write_text(json.dumps(held_saves, indent=2))

    # The settings shortcut disposes a portal menu from the previous pane.
    oauth_endpoint = {
        "id": "example-oauth",
        "name": "example OAuth",
        "base_url": "https://model.example.test",
        "provider": "gemini",
        "provider_label": "Gemini",
        "auth_type": "oauth",
        "auth_status": "ready",
        "provider_adapter": "gemini",
        "catalog_status": "ready",
        "health_status": "healthy",
        "models": ["example-model"],
    }
    model_fixture = [oauth_endpoint] + api.get("/api/models").json()
    page.route("**/api/models", lambda route: route.fulfill(json=model_fixture))
    pane("models")
    menu = page.locator('[data-role-select="aide_chat"]')
    menu.click()
    expect(page.locator(".custom-dropdown-panel")).to_be_visible()
    page.keyboard.press("Control+,")
    expect(page.locator("#s-pane-general")).to_be_visible()
    expect(page.locator(".custom-dropdown-panel")).to_have_count(0)
    expect(menu).to_have_attribute("aria-expanded", "false")

    # OAuth starts only create temporary UI for the opening that requested them.
    pane("models")
    page.locator("#s-gemini-oauth-toggle").click()
    page.locator("#s-gemini-client-id").fill("example-client")
    page.locator("#s-gemini-client-secret").fill("example")
    page.locator("#s-gemini-project-id").fill("example-project")
    page.evaluate(
        """() => {
            const h = window.__settingsPaneOAuth = {
                open: window.open, interval: window.setInterval, clear: window.clearInterval,
                opens: [], created: [], cleared: [], intervals: new Map(), next: 100000,
                popup: {closed: false},
            };
            window.open = (...args) => { h.opens.push(args); return h.popup; };
            window.setInterval = (callback, delay, ...args) => {
                if (delay !== 2000) return h.interval(callback, delay, ...args);
                const id = ++h.next;
                h.intervals.set(id, {callback, args});
                h.created.push({id, delay});
                return id;
            };
            window.clearInterval = id => {
                if (!h.intervals.has(id)) return h.clear(id);
                h.intervals.delete(id);
                h.cleared.push(id);
            };
        }"""
    )
    oauth_starts = []
    oauth_evidence = {}

    def hold_oauth_start(route):
        assert route.request.method == "POST"
        assert route.request.post_data_json == {
            "client_id": "example-client",
            "client_secret": "example",
            "project_id": "example-project",
        }
        oauth_starts.append(route)
        page.evaluate("count => window.__settingsPaneOAuthStarts = count", len(oauth_starts))

    def oauth_snapshot():
        return page.evaluate(
            """() => {
                const h = window.__settingsPaneOAuth;
                return {opens: h.opens, created: h.created, cleared: h.cleared,
                    active: [...h.intervals.keys()]};
            }"""
        )

    page.route("**/api/models/oauth/gemini/start", hold_oauth_start)
    start = page.locator("#s-gemini-oauth-start")
    for mode in ("close", "reopen"):
        expected_starts = len(oauth_starts) + 1
        start.click()
        page.wait_for_function(
            "count => window.__settingsPaneOAuthStarts === count", arg=expected_starts
        )
        expect(start).to_be_disabled()
        if mode == "close":
            page.locator("#settings-modal-close").click()
            expect(page.locator("#today-settings")).to_be_focused()
        else:
            close_and_reopen("models")
            expect(start).to_be_disabled()
        oauth_starts[-1].fulfill(json={"authorization_url": "https://oauth.example.test/authorize"})
        expect(start).to_be_enabled()
        expect(start).to_have_text("open Google authorization")
        oauth_evidence[mode] = oauth_snapshot()
        (destination / "oauth-lifecycle.json").write_text(json.dumps(oauth_evidence, indent=2))
        assert oauth_evidence[mode]["opens"] == []
        assert oauth_evidence[mode]["created"] == []
        assert oauth_evidence[mode]["active"] == []
        if mode == "close":
            expect(page.locator("#settings-modal")).to_be_hidden()
            expect(page.locator("#today-settings")).to_be_focused()
            page.locator("#today-settings").click()
            pane("models")

    expected_starts = len(oauth_starts) + 1
    start.click()
    page.wait_for_function(
        "count => window.__settingsPaneOAuthStarts === count", arg=expected_starts
    )
    oauth_starts[-1].fulfill(json={"authorization_url": "https://oauth.example.test/authorize"})
    page.wait_for_function("window.__settingsPaneOAuth.intervals.size === 1")
    expect(start).to_be_enabled()
    active = oauth_snapshot()
    assert active["opens"] == [
        ["https://oauth.example.test/authorize", "alles-gemini-oauth", "popup,width=620,height=760"]
    ]
    assert len(active["created"]) == 1
    page.wait_for_load_state("networkidle")
    reads = []

    def count_oauth_reads(request):
        if request.method == "GET" and urlsplit(request.url).path == "/api/models":
            reads.append(request.url)

    page.on("request", count_oauth_reads)
    page.evaluate(
        """async () => {
            const timer = window.__settingsPaneOAuth.intervals.values().next().value;
            await timer.callback(...timer.args);
        }"""
    )
    assert len(reads) == 1
    page.remove_listener("request", count_oauth_reads)
    pane("general")
    oauth_evidence["active-disposed"] = oauth_snapshot()
    assert oauth_evidence["active-disposed"]["active"] == []
    assert oauth_evidence["active-disposed"]["cleared"] == active["active"]
    (destination / "oauth-lifecycle.json").write_text(json.dumps(oauth_evidence, indent=2))
    page.unroute("**/api/models/oauth/gemini/start", hold_oauth_start)
    page.evaluate(
        """() => {
            const h = window.__settingsPaneOAuth;
            window.open = h.open;
            window.setInterval = h.interval;
            window.clearInterval = h.clear;
            delete window.__settingsPaneOAuth;
        }"""
    )

    # Optional vision failures retry the created endpoint, including across reopen.
    partial_evidence = []
    partial_posts = []
    partial_patches = []
    partial_card_writes = []
    held_partial_card = None
    reject_partial_vision = False

    def hold_partial_create(route):
        partial_posts.append(route)
        page.evaluate("n => window.__settingsPartialPosts = n", len(partial_posts))

    def hold_partial_vision(route):
        nonlocal reject_partial_vision
        if route.request.method == "PATCH" and "vision_models" in route.request.post_data_json:
            if reject_partial_vision:
                reject_partial_vision = False
                route.fulfill(status=503, json={"detail": "synthetic partial vision rejected"})
            else:
                partial_patches.append(route)
                page.evaluate("n => window.__settingsPartialPatches = n", len(partial_patches))
        elif (
            held_partial_card
            and route.request.method in {"PATCH", "POST", "DELETE"}
            and f"/endpoint/{held_partial_card}" in route.request.url
        ):
            partial_card_writes.append(route)
            page.evaluate("n => window.__settingsPartialCardWrites = n", len(partial_card_writes))
        else:
            route.continue_()

    page.route("**/api/models/endpoint", hold_partial_create)
    page.route("**/api/models/endpoint/**", hold_partial_vision)
    for outcome in (
        "unchanged",
        "vision-only",
        "vision-cleared",
        "new-config",
        "deleted",
        "missing",
        "retry-claim",
        "card-claim",
    ):
        pane("models")
        if page.locator("#s-ep-add-details").get_attribute("open") is None:
            page.locator("#s-ep-add-details summary").click()
        name = f"example partial {outcome}"
        page.locator("#s-ep-name").fill(name)
        page.locator("#s-ep-url").fill("http://127.0.0.1:1")
        for id in ("s-ep-adapter", "s-ep-auth"):
            page.locator(f"#{id}").focus()
            page.keyboard.press("End")
            page.keyboard.press("Enter")
        page.locator("#s-ep-manual").fill("example-submitted-model")
        page.locator("#s-ep-vision").fill("example-submitted-vision")
        button = page.locator("#s-ep-add-btn")
        posts_before = len(partial_posts)
        reject_partial_vision = True
        button.click()
        page.wait_for_function("n => window.__settingsPartialPosts === n", arg=posts_before + 1)
        response = partial_posts[-1].fetch()
        assert response.ok, response.text()
        created_id = response.json()["id"]
        partial_posts[-1].fulfill(response=response)
        expect(button).to_be_enabled()
        expect(page.locator("#toast-container .toast").last).to_have_text(
            "failed: synthetic partial vision rejected"
        )
        partial = next(ep for ep in api.get("/api/models").json() if ep["id"] == created_id)
        assert partial["models"] == ["example-submitted-model"] and partial["vision_models"] == []
        if outcome == "vision-only":
            page.locator("#s-ep-vision").fill("example-corrected-vision")
        elif outcome == "vision-cleared":
            page.locator("#s-ep-vision").fill("")
        elif outcome == "new-config":
            page.locator("#s-ep-name").fill("example separate create")
            page.locator("#s-ep-manual").fill("example-newer-model")
        elif outcome == "deleted":
            model_fixture.append(partial)
            close_and_reopen("models")
            removal = page.locator(f'[data-del="{created_id}"]')
            expect(removal).to_be_visible()
            removal.click()
            page.locator("[data-dialog-confirm]").click()
            expect(page.locator("#toast-container .toast").last).to_have_text("endpoint removed")
            model_fixture.remove(partial)
        elif outcome == "missing":
            assert api.delete(f"/api/models/endpoint/{created_id}").ok
        elif outcome in {"retry-claim", "card-claim"}:
            model_fixture.append(partial)
        close_and_reopen("models")
        patches_before = len(partial_patches)
        card_writes_before = len(partial_card_writes)
        if outcome in {"retry-claim", "card-claim"}:
            card = page.locator(f'[data-id="{created_id}"]')
            expect(card).to_be_visible()
            held_partial_card = created_id
        if outcome == "card-claim":
            card.locator("[data-edit-list]").click()
            card.locator("[data-save-list]").click()
            page.wait_for_function(
                "n => window.__settingsPartialCardWrites === n", arg=card_writes_before + 1
            )
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            close_and_reopen("models")
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            assert len(partial_patches) == patches_before
            assert len(partial_posts) == posts_before + 1
            page.locator("#s-ep-name").fill("example independent create")
            page.locator("#s-ep-manual").fill("example-newer-model")
            expect(button).to_be_enabled()
        button.click()
        if outcome in {"new-config", "deleted", "card-claim"}:
            page.wait_for_function("n => window.__settingsPartialPosts === n", arg=posts_before + 2)
            response = partial_posts[-1].fetch()
            assert response.ok, response.text()
            retry_id = response.json()["id"]
            partial_posts[-1].fulfill(response=response)
            assert retry_id != created_id
        else:
            retry_id = created_id
        page.wait_for_function("n => window.__settingsPartialPatches === n", arg=patches_before + 1)
        expect(button).to_be_disabled()
        button.dispatch_event("click")
        if outcome == "retry-claim":
            for action in ("save-list", "probe", "test-ep", "del"):
                control = card.locator(f"[data-{action}]")
                expect(control).to_be_disabled()
                control.dispatch_event("click")
            expect(page.locator(".dialog-overlay")).to_have_count(0)
            expect(page.locator(f'[data-probe="{endpoint}"]')).to_be_enabled()
            assert len(partial_card_writes) == card_writes_before
        close_and_reopen("models")
        expect(button).to_be_disabled()
        button.dispatch_event("click")
        assert len(partial_posts) == posts_before + (
            2 if outcome in {"new-config", "deleted", "card-claim"} else 1
        )
        assert len(partial_patches) == patches_before + 1
        assert partial_patches[-1].request.url.endswith(f"/endpoint/{retry_id}")
        if outcome == "card-claim":
            expect(card.locator("[data-save-list]")).to_be_disabled()
            expect(page.locator(f'[data-probe="{endpoint}"]')).to_be_enabled()
            response = partial_card_writes[-1].fetch()
            assert response.ok
            partial_card_writes[-1].fulfill(response=response)
            expect(card.locator("[data-save-list]")).to_be_enabled()
        response = partial_patches[-1].fetch()
        partial_patches[-1].fulfill(response=response)
        expect(button).to_be_enabled()
        if outcome == "missing":
            assert response.status == 404
            expect(page.locator("#toast-container .toast").last).to_have_text(
                "failed: model endpoint not found"
            )
            expect(page.locator("#s-ep-name")).to_have_value(name)
        else:
            assert response.ok, response.text()
            expect(page.locator("#s-ep-name")).to_have_value("")
            records = api.get("/api/models").json()
            saved = next(ep for ep in records if ep["id"] == retry_id)
            expected_vision = (
                []
                if outcome == "vision-cleared"
                else [
                    "example-corrected-vision"
                    if outcome == "vision-only"
                    else "example-submitted-vision"
                ]
            )
            assert saved["vision_models"] == expected_vision
            assert saved["models"] == [
                "example-newer-model"
                if outcome in {"new-config", "card-claim"}
                else "example-submitted-model"
            ]
            if outcome in {"new-config", "card-claim"}:
                old = next(ep for ep in records if ep["id"] == created_id)
                assert old["name"] == name and old["vision_models"] == []
            assert api.delete(f"/api/models/endpoint/{retry_id}").ok
        if outcome in {"new-config", "card-claim"}:
            assert api.delete(f"/api/models/endpoint/{created_id}").ok
        if outcome in {"retry-claim", "card-claim"}:
            model_fixture.remove(partial)
            held_partial_card = None
        partial_evidence.append(
            {
                "outcome": outcome,
                "posts": len(partial_posts) - posts_before,
                "retry_id": retry_id,
                "one_retry_patch": True,
                "closed_pending_repeats_excluded": True,
            }
        )
    page.unroute("**/api/models/endpoint", hold_partial_create)
    page.unroute("**/api/models/endpoint/**", hold_partial_vision)
    (destination / "provider-partial-retry.json").write_text(json.dumps(partial_evidence, indent=2))

    # Endpoint writes keep their actual controls across reopening and serialize newer drafts.
    endpoint_writes = []
    endpoint_evidence = []
    endpoint_read_failure = False
    endpoint_confirmation_read = False
    confirmation_reads = []

    def hold_endpoint_write(route):
        assert route.request.method in {"PATCH", "POST", "DELETE"}
        endpoint_writes.append(route)
        page.evaluate("count => window.__settingsPaneEndpointWrites = count", len(endpoint_writes))

    def pending_endpoint_read(route):
        nonlocal endpoint_read_failure, endpoint_confirmation_read
        if endpoint_confirmation_read:
            endpoint_confirmation_read = False
            confirmation_reads.append(route)
            page.evaluate(
                "count => window.__settingsConfirmationReads = count", len(confirmation_reads)
            )
        elif endpoint_read_failure:
            endpoint_read_failure = False
            route.fulfill(status=503, json={"detail": "synthetic pending endpoint read rejected"})
        else:
            route.fulfill(json=model_fixture)

    def endpoint_pending(endpoint_id, count):
        for action in ("save-list", "probe", "test-ep", "del", "auth-refresh", "auth-revoke"):
            for button in page.locator(f'[data-{action}="{endpoint_id}"]').all():
                expect(button).to_be_disabled()
                button.dispatch_event("click")
        expect(page.locator(".dialog-overlay")).to_have_count(0)
        assert len(endpoint_writes) == count
        assert page.evaluate("window.__settingsPanePendingEndpoint.isConnected")
        expect(page.locator(f'[data-editor="{endpoint_id}"] [data-edit-models]')).to_be_editable()

    def reopen_pending_endpoint():
        page.evaluate(
            "window.__settingsPanePendingRoles = document.querySelector('[data-role-select]')"
        )
        close_and_reopen("models")
        page.wait_for_function("window.__settingsPanePendingRoles.isConnected === false")

    page.route("**/api/models/endpoint/**", hold_endpoint_write)
    page.route("**/api/models", pending_endpoint_read)
    pane("models")
    page.wait_for_load_state("networkidle")
    clean_editor = page.locator(f'[data-editor="{endpoint}"]')
    page.locator(f'[data-edit-list="{endpoint}"]').click()
    assert clean_editor.get_attribute("data-dirty") is None
    endpoint_save = page.locator(f'[data-save-list="{endpoint}"]')
    endpoint_save.click()
    page.wait_for_function("window.__settingsPaneEndpointWrites === 1")
    endpoint_save.evaluate("el => window.__settingsPanePendingEndpoint = el")
    reopen_pending_endpoint()
    endpoint_pending(endpoint, 1)
    expect(endpoint_save).to_have_text("saving…")

    # Refresh-all skips the saving endpoint while an independent endpoint still progresses.
    page.locator("#s-ep-refresh-all").click()
    page.wait_for_function("window.__settingsPaneEndpointWrites === 2")
    assert endpoint_writes[-1].request.url.endswith("/example-oauth/probe")
    page.locator("#s-ep-refresh-all").dispatch_event("click")
    endpoint_pending(endpoint, 2)
    expect(page.locator('[data-probe="example-oauth"]')).to_be_disabled()
    endpoint_writes[-1].fulfill(json={"models": ["example-model"]})
    expect(page.locator("#s-ep-refresh-all")).to_be_enabled()
    expect(page.locator('[data-probe="example-oauth"]')).to_be_enabled()
    clean_editor.locator("[data-edit-models]").fill("example-newer")
    endpoint_pending(endpoint, 2)
    response = endpoint_writes[0].fetch()
    assert response.ok
    endpoint_writes[0].fulfill(response=response)
    expect(endpoint_save).to_be_enabled()
    expect(clean_editor.locator("[data-edit-models]")).to_have_value("example-newer")
    assert clean_editor.get_attribute("data-dirty") is not None
    actual = next(ep for ep in api.get("/api/models").json() if ep["id"] == endpoint)
    assert actual["models"] == ["fixture-a", "fixture-b"]
    endpoint_save.click()
    page.wait_for_function("window.__settingsPaneEndpointWrites === 3")
    assert endpoint_writes[-1].request.post_data_json["models"] == ["example-newer"]
    response = endpoint_writes[-1].fetch()
    assert response.ok
    endpoint_writes[-1].fulfill(response=response)
    expect(endpoint_save).to_be_enabled()
    actual = next(ep for ep in api.get("/api/models").json() if ep["id"] == endpoint)
    assert actual["models"] == ["example-newer"]
    assert api.patch(
        f"/api/models/endpoint/{endpoint}", data={"models": ["fixture-a", "fixture-b"]}
    ).ok
    page.wait_for_load_state("networkidle")
    endpoint_evidence.append(
        {
            "action": "save",
            "serial_patches": 2,
            "newer_draft_committed_last": True,
            "refresh_all_skipped_busy_and_ran_independent": True,
        }
    )

    # A failed read and failed write release the same retained controls for retry.
    page.locator(f'[data-edit-list="{endpoint}"]').click()
    endpoint_save.click()
    page.wait_for_function("window.__settingsPaneEndpointWrites === 4")
    endpoint_save.evaluate("el => window.__settingsPanePendingEndpoint = el")
    endpoint_read_failure = True
    reopen_pending_endpoint()
    endpoint_pending(endpoint, 4)
    endpoint_writes[-1].fulfill(status=503, json={"detail": "synthetic endpoint save rejected"})
    expect(endpoint_save).to_be_enabled()
    expect(page.locator('[data-role-select="aide_chat"]')).to_have_count(1)
    page.wait_for_load_state("networkidle")
    if not clean_editor.is_visible():
        page.locator(f'[data-edit-list="{endpoint}"]').click()
    endpoint_save.click()
    page.wait_for_function("window.__settingsPaneEndpointWrites === 5")
    response = endpoint_writes[-1].fetch()
    assert response.ok
    endpoint_writes[-1].fulfill(response=response)
    expect(endpoint_save).to_be_enabled()
    page.wait_for_load_state("networkidle")
    endpoint_evidence.append({"action": "save", "read_and_write_failure_recovered": True})

    for action, path in (("probe", "probe"), ("test-ep", "test"), ("del", "")):
        for rejected in (False, True):
            count = len(endpoint_writes) + 1
            control = page.locator(f'[data-{action}="{endpoint}"]')
            control.click()
            if action == "del":
                page.locator("[data-dialog-confirm]").click()
            page.wait_for_function(
                "count => window.__settingsPaneEndpointWrites === count", arg=count
            )
            assert endpoint_writes[-1].request.url.endswith(
                f"/{endpoint}" + (f"/{path}" if path else "")
            )
            control.evaluate("el => window.__settingsPanePendingEndpoint = el")
            reopen_pending_endpoint()
            endpoint_pending(endpoint, count)
            expect(control).to_have_text(
                {"probe": "refreshing…", "test-ep": "testing…", "del": "removing…"}[action]
            )
            if rejected:
                endpoint_writes[-1].fulfill(
                    status=503, json={"detail": f"synthetic endpoint {action} rejected"}
                )
            else:
                endpoint_writes[-1].fulfill(json={"models": ["fixture-a", "fixture-b"], "ok": True})
            expect(control).to_be_enabled()
            page.wait_for_load_state("networkidle")
            endpoint_evidence.append(
                {"action": action, "rejected": rejected, "reopen_repeat_guard_and_release": True}
            )

    # An action begun while a confirmation is open wins the endpoint claim.
    for action, competing in (("del", "probe"), ("auth-revoke", "auth-refresh")):
        endpoint_id = endpoint if action == "del" else "example-oauth"
        count = len(endpoint_writes) + 1
        page.locator(f'[data-{action}="{endpoint_id}"]').click()
        page.locator(f'[data-{competing}="{endpoint_id}"]').dispatch_event("click")
        page.wait_for_function("count => window.__settingsPaneEndpointWrites === count", arg=count)
        page.locator("[data-dialog-confirm]").click()
        assert len(endpoint_writes) == count
        assert endpoint_writes[-1].request.method == "POST"
        endpoint_writes[-1].fulfill(json={"models": ["fixture-a", "fixture-b"], "ok": True})
        expect(page.locator(f'[data-{action}="{endpoint_id}"]')).to_be_enabled()
        page.wait_for_load_state("networkidle")
        endpoint_evidence.append({"action": action, "confirmation_rechecks_claim": True})
    # A current read during confirmation keeps the actual control and cancel focus.
    for action in ("del", "auth-revoke"):
        endpoint_id = endpoint if action == "del" else "example-oauth"
        control = page.locator(f'[data-{action}="{endpoint_id}"]')
        endpoint_confirmation_read = True
        reads = len(confirmation_reads) + 1
        close_and_reopen("models")
        page.wait_for_function("count => window.__settingsConfirmationReads === count", arg=reads)
        control.evaluate("el => window.__settingsConfirmationOwner = el")
        control.click()
        expect(page.locator("[data-dialog-confirm]")).to_be_visible()
        confirmation_reads[-1].fulfill(json=model_fixture)
        page.wait_for_load_state("networkidle")
        assert page.evaluate("window.__settingsConfirmationOwner.isConnected")
        page.keyboard.press("Escape")
        expect(control).to_be_focused()
        assert page.evaluate("document.activeElement === window.__settingsConfirmationOwner")
        count = len(endpoint_writes) + 1
        control.click()
        page.locator("[data-dialog-confirm]").click()
        page.wait_for_function("count => window.__settingsPaneEndpointWrites === count", arg=count)
        expect(control).to_be_disabled()
        expect(control).to_have_text("removing…" if action == "del" else "revoking…")
        assert page.evaluate("window.__settingsConfirmationOwner.isConnected")
        control.evaluate("el => window.__settingsPanePendingEndpoint = el")
        reopen_pending_endpoint()
        endpoint_pending(endpoint_id, count)
        expect(control).to_have_text("removing…" if action == "del" else "revoking…")
        finished_model_reads = []

        def confirmation_followup_finished(request):
            if request.method == "GET" and urlsplit(request.url).path == "/api/models":
                finished_model_reads.append(request.url)
                page.evaluate(
                    "count => window.__settingsConfirmationFollowups = count",
                    len(finished_model_reads),
                )

        page.evaluate("window.__settingsConfirmationFollowups = 0")
        page.on("requestfinished", confirmation_followup_finished)
        endpoint_writes[-1].fulfill(json={"ok": True})
        expect(control).to_be_enabled()
        page.wait_for_function("window.__settingsConfirmationFollowups === 2")
        page.remove_listener("requestfinished", confirmation_followup_finished)
        endpoint_evidence.append(
            {"action": action, "held_confirmation_read_keeps_busy_and_cancel_focus": True}
        )
    page.unroute("**/api/models/endpoint/**", hold_endpoint_write)
    page.unroute("**/api/models", pending_endpoint_read)
    (destination / "provider-endpoint-pending.json").write_text(
        json.dumps(endpoint_evidence, indent=2)
    )

    # Current opening reads cannot detach clean controls during keyboard interaction.
    focused_reads = []
    focus_evidence = []

    def hold_focused_read(route):
        assert route.request.method == "GET"
        focused_reads.append(route)
        page.evaluate("count => window.__settingsPaneFocusedReads = count", len(focused_reads))

    page.route("**/api/models", hold_focused_read)
    for rejected in (False, True):
        pane("general")
        expected_reads = len(focused_reads) + 1
        pane("models")
        page.wait_for_function(
            "count => window.__settingsPaneFocusedReads === count", arg=expected_reads
        )
        role_control = page.locator('[data-role-select="aide_chat"]')
        role_control.focus()
        role_control.evaluate("el => window.__settingsPaneFocusedControl = el")
        page.keyboard.press("End")
        expect(page.locator(".custom-dropdown-panel")).to_be_visible()
        if rejected:
            focused_reads[-1].fulfill(
                status=503, json={"detail": "synthetic focused role load rejected"}
            )
        else:
            focused_reads[-1].fulfill(json=model_fixture)
        page.wait_for_load_state("networkidle")
        expect(role_control).to_be_focused()
        assert page.evaluate("window.__settingsPaneFocusedControl.isConnected")
        expect(page.locator(".custom-dropdown-panel")).to_be_visible()
        page.keyboard.press("Enter")
        expect(page.locator(".custom-dropdown-panel")).to_have_count(0)
        expect(role_control).to_be_focused()
        assert role_control.get_attribute("data-value")
        focus_evidence.append(
            {"control": "role", "rejected": rejected, "node_and_focus_kept": True}
        )

        # A real save resets the dirty flag and still refreshes authoritative role state.
        page.unroute("**/api/models", hold_focused_read)
        page.locator("#s-role-save-btn").click()
        expect(page.locator("#s-role-save-btn")).to_be_enabled()
        assert api.get("/api/settings").json()["model_roles"]["aide_chat"]["model"] == "fixture-b"
        page.route("**/api/models", hold_focused_read)

    for selector in ("[data-edit-models]", "[data-edit-adapter]"):
        for rejected in (False, True):
            pane("general")
            expected_reads = len(focused_reads) + 1
            pane("models")
            page.wait_for_function(
                "count => window.__settingsPaneFocusedReads === count", arg=expected_reads
            )
            clean_editor = page.locator(f'[data-editor="{endpoint}"]')
            if not clean_editor.is_visible():
                page.locator(f'[data-edit-list="{endpoint}"]').click()
            assert clean_editor.get_attribute("data-dirty") is None
            control = clean_editor.locator(selector)
            control.focus()
            control.evaluate("el => window.__settingsPaneFocusedControl = el")
            if selector == "[data-edit-adapter]":
                page.keyboard.press("End")
                expect(page.locator(".custom-dropdown-panel")).to_be_visible()
            if rejected:
                focused_reads[-1].fulfill(
                    status=503, json={"detail": "synthetic focused endpoint load rejected"}
                )
            else:
                focused_reads[-1].fulfill(json=model_fixture)
            page.wait_for_load_state("networkidle")
            expect(control).to_be_focused()
            assert page.evaluate("window.__settingsPaneFocusedControl.isConnected")
            assert clean_editor.get_attribute("data-dirty") is None
            if selector == "[data-edit-adapter]":
                expect(page.locator(".custom-dropdown-panel")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator(".custom-dropdown-panel")).to_have_count(0)
                expect(control).to_be_focused()
            else:
                expect(control).to_have_value("fixture-a, fixture-b")
            page.locator(f'[data-edit-list="{endpoint}"]').click()
            focus_evidence.append(
                {"control": selector, "rejected": rejected, "clean_node_and_focus_kept": True}
            )
    page.unroute("**/api/models", hold_focused_read)
    (destination / "provider-focused-loads.json").write_text(json.dumps(focus_evidence, indent=2))

    # Read-only refreshes keep role and endpoint editor drafts separately.
    pane("models")
    expect(page.locator("#s-ep-list")).to_contain_text("pane fixture")
    role = page.locator('[data-role-select="aide_chat"]')
    role.focus()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    role_value = role.get_attribute("data-value")
    assert role_value
    page.locator(f'[data-edit-list="{endpoint}"]').click()
    editor = page.locator(f'[data-editor="{endpoint}"]')
    editor.locator("[data-edit-models]").fill("fixture-b, newer-owner-edit")
    close_and_reopen("models")
    expect(role).to_have_attribute("data-value", role_value)
    expect(editor.locator("[data-edit-models]")).to_have_value("fixture-b, newer-owner-edit")

    # Grant writes recover their own controls without replacing dirty endpoint editors.
    page.locator('[data-edit-list="example-oauth"]').click()
    oauth_draft = page.locator('[data-editor="example-oauth"] [data-edit-models]')
    oauth_draft.fill("example-owner-draft")
    grant_writes = []

    def hold_grant_write(route):
        assert route.request.method == "POST"
        grant_writes.append(route)
        page.evaluate("count => window.__settingsPaneGrantWrites = count", len(grant_writes))

    page.route("**/api/models/endpoint/example-oauth/auth/**", hold_grant_write)
    for action in ("refresh", "revoke"):
        grant = page.locator(f'[data-auth-{action}="example-oauth"]')
        for rejected in (False, True):
            expected_writes = len(grant_writes) + 1
            grant.click()
            if action == "revoke":
                page.locator(".dialog-overlay [data-dialog-confirm]").click()
            page.wait_for_function(
                "count => window.__settingsPaneGrantWrites === count", arg=expected_writes
            )
            expect(grant).to_be_disabled()
            grant.dispatch_event("click")
            close_and_reopen("models")
            expect(grant).to_be_disabled()
            expect(grant).to_have_text("refreshing…" if action == "refresh" else "revoking…")
            expect(oauth_draft).to_have_value("example-owner-draft")
            assert len(grant_writes) == expected_writes
            if rejected:
                grant_writes[-1].fulfill(
                    status=503, json={"detail": f"synthetic grant {action} rejected"}
                )
            else:
                grant_writes[-1].fulfill(json=oauth_endpoint)
            expect(grant).to_be_enabled()
            expect(grant).to_have_text("refresh grant" if action == "refresh" else "revoke")
            expect(page.locator("#toast-container .toast").last).to_have_text(
                f"synthetic grant {action} rejected"
                if rejected
                else "Gemini grant refreshed"
                if action == "refresh"
                else "Gemini grant revoked"
            )
            expect(oauth_draft).to_have_value("example-owner-draft")
    page.unroute("**/api/models/endpoint/example-oauth/auth/**", hold_grant_write)
    (destination / "provider-grant-lifecycle.json").write_text(
        json.dumps(
            {"writes": len(grant_writes), "draft_kept": True, "success_and_failure_released": True},
            indent=2,
        )
    )
    role_save = []

    def delayed_role_save(route):
        if route.request.method == "PATCH" and "model_roles" in (route.request.post_data or ""):
            response = route.fetch()
            assert response.ok
            role_save.append((route, response))
            page.evaluate("window.__settingsPaneRoleSaveReady = true")
        else:
            route.continue_()

    page.route("**/api/settings", delayed_role_save)
    page.locator("#s-role-save-btn").click()
    expect(page.locator("#s-role-save-btn")).to_be_disabled()
    page.wait_for_function("window.__settingsPaneRoleSaveReady === true")
    assert len(role_save) == 1
    role.focus()
    page.keyboard.press("Home")
    page.keyboard.press("Enter")
    role_save[0][0].fulfill(response=role_save[0][1])
    expect(page.locator("#s-role-save-btn")).to_be_enabled()
    expect(role).to_have_attribute("data-value", "")
    expect(page.locator("#s-role-save-state")).to_have_text("changes not saved")
    page.unroute("**/api/settings", delayed_role_save)
    assert api.get("/api/settings").json()["model_roles"]["aide_chat"]["model"] == "fixture-b"
    expect(editor.locator("[data-edit-models]")).to_have_value("fixture-b, newer-owner-edit")

    # Creates own their pending form and acknowledge only the submitted revision.
    creation_evidence = []

    def choose_edge(id, last=True):
        page.locator(f"#{id}").focus()
        page.keyboard.press("End" if last else "Home")
        page.keyboard.press("Enter")

    provider_fields = ["s-ep-name", "s-ep-url", "s-ep-key", "s-ep-vision", "s-ep-manual"]
    create_writes = []

    def hold_provider_create(route):
        assert route.request.method == "POST"
        create_writes.append(route)
        page.evaluate("count => window.__settingsCreateWrites = count", len(create_writes))

    page.route("**/api/models/endpoint", hold_provider_create)
    for outcome in ("newer", "failure", "unchanged"):
        pane("models")
        if page.locator("#s-ep-add-details").get_attribute("open") is None:
            page.locator("#s-ep-add-details summary").click()
        page.locator("#s-ep-name").fill(f"example provider {outcome}")
        page.locator("#s-ep-url").fill("http://127.0.0.1:1")
        choose_edge("s-ep-adapter")
        choose_edge("s-ep-auth")
        page.locator("#s-ep-manual").fill("example-submitted-model")
        page.locator("#s-ep-vision").fill("example-submitted-vision")
        button = page.locator("#s-ep-add-btn")
        count = len(create_writes) + 1
        button.click()
        page.wait_for_function("count => window.__settingsCreateWrites === count", arg=count)
        expect(button).to_be_disabled()
        button.dispatch_event("click")
        if outcome == "newer":
            page.locator("#s-ep-name").fill("example newer endpoint")
            page.locator("#s-ep-url").fill("http://127.0.0.1:2")
            page.locator("#s-ep-manual").fill("example-newer-model")
            page.locator("#s-ep-vision").fill("example-newer-vision")
            choose_edge("s-ep-auth", False)
            page.locator("#s-ep-key").fill("example")
            choose_edge("s-ep-provider")
        draft = {id: page.locator(f"#{id}").input_value() for id in provider_fields}
        dropdown_draft = {
            id: page.locator(f"#{id}").get_attribute("data-value")
            for id in ("s-ep-auth", "s-ep-adapter", "s-ep-provider")
        }
        close_and_reopen("models")
        expect(button).to_be_disabled()
        expect(button).to_have_text("probing…")
        button.dispatch_event("click")
        assert len(create_writes) == count
        assert {id: page.locator(f"#{id}").input_value() for id in provider_fields} == draft
        if outcome == "failure":
            create_writes[-1].fulfill(
                status=503, json={"detail": "synthetic provider create rejected"}
            )
        else:
            response = create_writes[-1].fetch()
            assert response.ok, response.text()
            created_id = response.json()["id"]
            create_writes[-1].fulfill(response=response)
        expect(button).to_be_enabled()
        if outcome in {"newer", "failure"}:
            assert {id: page.locator(f"#{id}").input_value() for id in provider_fields} == draft
            assert {
                id: page.locator(f"#{id}").get_attribute("data-value") for id in dropdown_draft
            } == dropdown_draft
            assert page.locator("#s-ep-add-details").get_attribute("open") is not None
        else:
            assert all(page.locator(f"#{id}").input_value() == "" for id in provider_fields)
            assert page.locator("#s-ep-add-details").get_attribute("open") is None
        if outcome != "failure":
            saved = next(ep for ep in api.get("/api/models").json() if ep["id"] == created_id)
            assert saved["models"] == ["example-submitted-model"]
            assert saved["vision_models"] == ["example-submitted-vision"]
            assert saved["name"] == f"example provider {outcome}"
            assert api.delete(f"/api/models/endpoint/{created_id}").ok
        creation_evidence.append({"form": "provider", "outcome": outcome, "one_post": True})
    # A failed vision acknowledgment retains the form and reports the partial create.
    page.locator("#s-ep-add-details summary").click()
    page.locator("#s-ep-name").fill("example partial vision endpoint")
    page.locator("#s-ep-url").fill("http://127.0.0.1:1")
    choose_edge("s-ep-adapter")
    choose_edge("s-ep-auth")
    page.locator("#s-ep-manual").fill("example-submitted-model")
    page.locator("#s-ep-vision").fill("example-submitted-vision")
    vision_failures = []

    def reject_vision(route):
        if route.request.method == "PATCH" and "vision_models" in route.request.post_data_json:
            vision_failures.append(route)
            route.fulfill(status=503, json={"detail": "synthetic vision save rejected"})
        else:
            route.continue_()

    page.route("**/api/models/endpoint/**", reject_vision)
    count = len(create_writes) + 1
    button.click()
    page.wait_for_function("count => window.__settingsCreateWrites === count", arg=count)
    page.locator("#s-ep-name").fill("example newer vision draft")
    response = create_writes[-1].fetch()
    assert response.ok
    partial_id = response.json()["id"]
    create_writes[-1].fulfill(response=response)
    expect(button).to_be_enabled()
    expect(page.locator("#toast-container .toast").last).to_have_text(
        "failed: synthetic vision save rejected"
    )
    expect(page.locator("#s-ep-vision")).to_have_value("example-submitted-vision")
    expect(page.locator("#s-ep-name")).to_have_value("example newer vision draft")
    assert len(vision_failures) == 1
    partial = next(ep for ep in api.get("/api/models").json() if ep["id"] == partial_id)
    assert partial["models"] == ["example-submitted-model"] and partial["vision_models"] == []
    assert partial["name"] == "example partial vision endpoint"
    assert api.delete(f"/api/models/endpoint/{partial_id}").ok
    page.unroute("**/api/models/endpoint/**", reject_vision)
    creation_evidence.append(
        {
            "form": "provider-vision",
            "http_failure_retains_draft": True,
            "partial_create_readback": True,
        }
    )
    page.unroute("**/api/models/endpoint", hold_provider_create)

    pane("tools")
    expect(page.locator("#conn-list")).to_contain_text("nothing connected")
    expect(page.locator("#mcp-server-list")).to_contain_text("no servers")
    expect(page.locator("#perm-rules-list")).to_contain_text("no rules")
    for form, route_url, button_id, fields in (
        ("connection", "**/api/connections", "conn-add-btn", ["conn-token"]),
        (
            "mcp",
            "**/api/mcp/servers",
            "mcp-add-btn",
            ["mcp-name", "mcp-command", "mcp-url", "mcp-env", "mcp-headers"],
        ),
        (
            "permission",
            "**/api/settings",
            "perm-rule-add-btn",
            ["perm-rule-tool", "perm-rule-path"],
        ),
    ):
        held = []

        def hold_form_create(route, request, form=form):
            if request.method == ("PATCH" if form == "permission" else "POST"):
                held.append(route)
                page.evaluate("count => window.__settingsFormCreateWrites = count", len(held))
            else:
                route.continue_()

        page.route(route_url, hold_form_create)
        for outcome in ("newer", "failure", "unchanged"):
            if form == "connection":
                choose_edge("conn-service")
                expect(page.locator("#conn-custom-row")).to_be_visible()
                page.locator("#conn-custom").fill("example-create-fixture")
                page.locator("#conn-token").fill("example-submitted")
            elif form == "mcp":
                page.locator("#mcp-name").fill(f"example MCP {outcome}")
                page.locator("#mcp-command").fill("example-nonexistent-command")
                if page.locator(".mcp-advanced").get_attribute("open") is None:
                    page.locator(".mcp-advanced summary").click()
                choose_edge("mcp-transport", False)
                page.locator("#mcp-url").fill("http://127.0.0.1:1/example")
                page.locator("#mcp-env").fill("EXAMPLE=example")
                page.locator("#mcp-headers").fill("Example=example")
            else:
                page.locator("#perm-rule-tool").fill(f"example_{outcome}")
                page.locator("#perm-rule-path").fill(f"/example/{outcome}")
            previous = (
                api.get("/api/settings").json()["permission_rules"]
                if form == "permission"
                else None
            )
            count = len(held) + 1
            button = page.locator(f"#{button_id}")
            button.click()
            page.wait_for_function(
                "count => window.__settingsFormCreateWrites === count", arg=count
            )
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            payload = held[-1].request.post_data_json
            if outcome == "newer":
                for id in fields:
                    page.locator(f"#{id}").fill(
                        "EXAMPLE=example-newer"
                        if id == "mcp-env"
                        else "Example=example-newer"
                        if id == "mcp-headers"
                        else "http://127.0.0.1:2/example"
                        if id == "mcp-url"
                        else f"example-newer-{id}"
                    )
                if form == "permission":
                    choose_edge("perm-rule-action")
            draft = {id: page.locator(f"#{id}").input_value() for id in fields}
            close_and_reopen("tools")
            expect(button).to_be_disabled()
            button.dispatch_event("click")
            assert len(held) == count
            assert {id: page.locator(f"#{id}").input_value() for id in fields} == draft
            if outcome == "failure":
                held[-1].fulfill(status=503, json={"detail": f"synthetic {form} create rejected"})
            else:
                response = held[-1].fetch()
                assert response.ok, response.text()
                result = response.json()
                held[-1].fulfill(response=response)
            expect(button).to_be_enabled()
            if outcome in {"newer", "failure"}:
                assert {id: page.locator(f"#{id}").input_value() for id in fields} == draft
            else:
                assert all(page.locator(f"#{id}").input_value() == "" for id in fields)
            if form == "permission":
                saved = api.get("/api/settings").json()["permission_rules"]
                assert saved == (previous if outcome == "failure" else payload["permission_rules"])
            elif outcome != "failure" and form == "connection":
                saved = [
                    c
                    for c in api.get("/api/connections").json()
                    if c["service"] == payload["service"]
                ]
                assert len(saved) == 1 and saved[0]["token_masked"] == "exam…tted"
                assert api.delete(f"/api/connections/{saved[0]['id']}").ok
            elif outcome != "failure":
                saved = [s for s in api.get("/api/mcp/servers").json() if s["id"] == result["id"]]
                assert len(saved) == 1 and saved[0]["name"] == payload["name"]
                assert saved[0]["command"] == payload["command"]
                assert api.delete(f"/api/mcp/servers/{result['id']}").ok
            creation_evidence.append({"form": form, "outcome": outcome, "one_write": True})
        page.unroute(route_url, hold_form_create)
    assert api.patch("/api/settings", data={"permission_rules": []}).ok

    pane("models")
    expect(page.locator("#s-local-ollama")).to_contain_text("Ollama:")
    pulls = []

    def hold_custom_pull(route):
        pulls.append(route)
        page.evaluate("count => window.__settingsPullWrites = count", len(pulls))

    page.route("**/api/local-models/download_model", hold_custom_pull)
    page.route(
        "**/api/local-models/jobs/example-failed",
        lambda route: route.fulfill(
            json={
                "status": "error",
                "error": "synthetic completed job failure",
            }
        ),
    )
    page.route(
        "**/api/local-models/jobs/example-done",
        lambda route: route.fulfill(
            json={
                "status": "done",
                "model": "example-submitted-model",
            }
        ),
    )
    for outcome in ("failure", "newer", "unchanged"):
        field = page.locator("#s-local-custom")
        field.fill(" example-submitted-model ")
        button = page.locator("#s-local-pull-btn")
        count = len(pulls) + 1
        button.click()
        page.wait_for_function("count => window.__settingsPullWrites === count", arg=count)
        expect(button).to_be_disabled()
        button.dispatch_event("click")
        if outcome == "newer":
            field.fill("example-newer-model")
        draft = field.input_value()
        close_and_reopen("models")
        expect(button).to_be_disabled()
        expect(field).to_have_value(draft)
        assert len(pulls) == count
        assert pulls[-1].request.post_data_json == {"model": "example-submitted-model"}
        if outcome == "failure":
            pulls[-1].fulfill(status=503, json={"detail": "synthetic custom pull rejected"})
            expect(button).to_be_enabled()
            expect(field).to_have_value(draft)
        else:
            pulls[-1].fulfill(
                json={"id": "example-failed" if outcome == "newer" else "example-done"}
            )
            expect(button).to_have_text("download" if outcome == "newer" else "downloaded")
            expect(field).to_have_value(draft if outcome == "newer" else "")
        creation_evidence.append({"form": "custom-pull", "outcome": outcome, "one_post": True})
    page.unroute("**/api/local-models/download_model", hold_custom_pull)
    page.unroute("**/api/local-models/jobs/example-failed")
    page.unroute("**/api/local-models/jobs/example-done")
    (destination / "creation-pending-drafts.json").write_text(
        json.dumps(creation_evidence, indent=2)
    )
    connection_failures = connection_write_cases(
        page, api, pane, close_and_reopen, choose_edge, destination
    )
    retained_failures = retained_write_cases(page, api, pane, close_and_reopen, destination)
    retained_list_failures = retained_list_cases(page, api, pane, close_and_reopen, destination)
    persona_failures = persona_write_cases(page, api, close_and_reopen, destination)
    action_failures = persona_token_action_cases(page, api, close_and_reopen, destination)
    local_failures = local_preset_cases(page, close_and_reopen, destination)
    developer_failures = developer_focus_webhook_cases(
        page, api, pane, close_and_reopen, destination
    )
    webhook_mutual_failures = webhook_mutual_action_cases(page, api, close_and_reopen, destination)
    # Failed connection checks retry independently, keeping newly typed backup fields.
    attempts = []

    def backup_fault(route):
        attempts.append(True)
        if len(attempts) == 1:
            route.fulfill(status=503, json={"detail": "synthetic backup check unavailable"})
        else:
            route.continue_()

    page.route("**/api/backup/webdav", backup_fault)
    pane("backup")
    expect(page.locator("#webdav-backup-status")).to_contain_text(
        "synthetic backup check unavailable"
    )
    expect(page.locator("#s3-backup-status")).to_have_text("not connected")
    expect(page.locator("#s3-backup-disconnect-btn")).to_be_hidden()
    page.locator("#webdav-backup-url").fill("https://backup.example.test/owner-draft")
    page.locator("#webdav-backup-username").fill("draft-user")
    page.locator("#s3-backup-endpoint").fill("https://storage.example.test")
    page.locator("#s3-backup-bucket").fill("draft-bucket")
    close_and_reopen("backup")
    expect(page.locator("#webdav-backup-status")).to_contain_text("unsaved connection changes")
    expect(page.locator("#webdav-backup-url")).to_have_value(
        "https://backup.example.test/owner-draft"
    )
    expect(page.locator("#webdav-backup-username")).to_have_value("draft-user")
    expect(page.locator("#s3-backup-bucket")).to_have_value("draft-bucket")
    assert len(attempts) == 2
    page.unroute("**/api/backup/webdav", backup_fault)
    backup_save = []

    def delayed_backup_save(route):
        if route.request.method == "PUT":
            backup_save.append(route)
            page.evaluate("window.__settingsPaneBackupSaveReady = true")
        else:
            route.continue_()

    page.route("**/api/backup/webdav/backups", lambda route: route.fulfill(json={"backups": []}))
    page.route("**/api/backup/webdav", delayed_backup_save)
    page.locator("#webdav-backup-password").fill("example")
    page.locator("#webdav-backup-url").fill("http://backup.example.test/owner-draft")
    page.locator("#webdav-backup-save-btn").click()
    expect(page.locator("#webdav-backup-status")).to_have_text("the WebDAV url must use https")
    expect(page.locator("#webdav-backup-password")).to_have_value("example")
    assert backup_save == []
    page.locator("#webdav-backup-url").fill("https://backup.example.test/owner-draft")
    page.locator("#webdav-backup-save-btn").click()
    expect(page.locator("#webdav-backup-save-btn")).to_be_disabled()
    expect(page.locator("#webdav-backup-password")).to_have_value("")
    page.wait_for_function("window.__settingsPaneBackupSaveReady === true")
    assert len(backup_save) == 1
    assert backup_save[0].request.post_data_json["password"] == "example"
    page.locator("#webdav-backup-url").fill("https://backup.example.test/newer-owner-edit")
    backup_save[0].fulfill(
        json={
            "configured": True,
            "url": "https://backup.example.test/owner-draft",
            "username": "draft-user",
        }
    )
    expect(page.locator("#webdav-backup-save-btn")).to_be_enabled()
    expect(page.locator("#webdav-backup-url")).to_have_value(
        "https://backup.example.test/newer-owner-edit"
    )
    expect(page.locator("#webdav-backup-status")).to_contain_text("newer connection edits kept")
    page.unroute("**/api/backup/webdav", delayed_backup_save)
    backup_disconnect = []

    def delayed_backup_disconnect(route):
        if route.request.method == "DELETE":
            backup_disconnect.append(route)
            page.evaluate("window.__settingsPaneBackupDisconnectReady = true")
        else:
            route.continue_()

    page.route("**/api/backup/webdav", delayed_backup_disconnect)
    page.locator("#webdav-backup-disconnect-btn").click()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    expect(page.locator("#webdav-backup-disconnect-btn")).to_be_disabled()
    page.wait_for_function("window.__settingsPaneBackupDisconnectReady === true")
    assert len(backup_disconnect) == 1
    page.locator("#webdav-backup-username").fill("typed-during-disconnect")
    backup_disconnect[0].fulfill(json={})
    expect(page.locator("#webdav-backup-disconnect-btn")).to_be_hidden()
    expect(page.locator("#webdav-backup-username")).to_have_value("typed-during-disconnect")
    expect(page.locator("#webdav-backup-url")).to_have_value(
        "https://backup.example.test/newer-owner-edit"
    )
    page.unroute("**/api/backup/webdav", delayed_backup_disconnect)
    page.unroute("**/api/backup/webdav/backups")

    # Each remote provider owns one write; reopening and status reads keep that lock.
    remote_configs = {
        "webdav": {
            "configured": True,
            "url": "https://backup.example.test/configured",
            "username": "example",
        },
        "s3": {
            "configured": True,
            "credentials_set": True,
            "endpoint": "https://storage.example.test/",
            "region": "us-east-1",
            "bucket": "example",
            "prefix": "",
            "addressing_style": "path",
        },
    }
    remote_writes = {provider: [] for provider in remote_configs}
    remote_backup_files = {provider: [] for provider in remote_configs}
    remote_lists = {provider: [] for provider in remote_configs}
    remote_list_reads = {provider: 0 for provider in remote_configs}
    remote_list_limits = {}
    hold_remote_lists = set()

    for provider in remote_configs:

        def remote_api(route, request, provider=provider):
            if route.request.method == "GET":
                if urlsplit(route.request.url).path.endswith("/backups"):
                    remote_list_reads[provider] += 1
                    if (
                        provider in remote_list_limits
                        and remote_list_reads[provider] > remote_list_limits[provider]
                    ):
                        route.fulfill(
                            status=503, json={"detail": "synthetic duplicate list rejected"}
                        )
                        return
                if provider in hold_remote_lists and urlsplit(route.request.url).path.endswith(
                    "/backups"
                ):
                    hold_remote_lists.remove(provider)
                    remote_lists[provider].append(route)
                    page.evaluate(
                        """provider => {
                            window.__settingsPaneRemoteLists ||= {};
                            window.__settingsPaneRemoteLists[provider] = true;
                        }""",
                        provider,
                    )
                    return
                payload = (
                    {"backups": remote_backup_files[provider]}
                    if urlsplit(route.request.url).path.endswith("/backups")
                    else remote_configs[provider]
                )
                route.fulfill(json=payload)
            else:
                remote_writes[provider].append((route.request.method, route))
                page.evaluate(
                    """([provider, count]) => {
                        window.__settingsPaneRemoteWrites ||= {};
                        window.__settingsPaneRemoteWrites[provider] = count;
                    }""",
                    [provider, len(remote_writes[provider])],
                )

        page.route(f"**/api/backup/{provider}**", remote_api)

    close_and_reopen("backup")
    for provider in remote_configs:
        expect(page.locator(f"#{provider}-backup-run-btn")).to_be_enabled()
    page.locator("#s3-backup-region").fill("")
    page.locator("#s3-backup-access-key-id").fill("example")
    page.locator("#s3-backup-secret-access-key").fill("example")
    page.locator("#s3-backup-save-btn").click()
    expect(page.locator("#s3-backup-status")).to_have_text("add the S3 region")
    expect(page.locator("#s3-backup-access-key-id")).to_have_value("example")
    expect(page.locator("#s3-backup-secret-access-key")).to_have_value("example")
    assert remote_writes["s3"] == []
    page.locator("#s3-backup-region").fill("us-east-1")
    page.locator("#webdav-backup-save-btn").click()
    page.wait_for_function("window.__settingsPaneRemoteWrites?.webdav === 1")
    expect(page.locator("#s3-backup-save-btn")).to_be_enabled()
    page.locator("#s3-backup-save-btn").click()
    page.wait_for_function("window.__settingsPaneRemoteWrites?.s3 === 1")
    assert remote_writes["s3"][0][1].request.post_data_json["access_key_id"] == "example"
    assert remote_writes["s3"][0][1].request.post_data_json["secret_access_key"] == "example"
    expect(page.locator("#s3-backup-access-key-id")).to_have_value("")
    expect(page.locator("#s3-backup-secret-access-key")).to_have_value("")
    pending_controls = {
        provider: {
            action: page.locator(f"#{provider}-backup-{action}-btn").is_disabled()
            for action in ("save", "disconnect", "run")
        }
        for provider in remote_configs
    }
    (destination / "backup-pending-controls.json").write_text(
        json.dumps(pending_controls, indent=2)
    )

    def assert_remote_pending(provider, expected_writes, action="save"):
        busy_status = {
            "webdav": {
                "save": "checking and saving…",
                "run": "creating and uploading encrypted backup…",
                "disconnect": "disconnecting…",
            },
            "s3": {
                "save": "creating and removing a probe object…",
                "run": "creating and copying encrypted backup…",
                "disconnect": "disconnecting…",
            },
        }
        expect(page.locator(f"#{provider}-backup-status")).to_have_text(
            busy_status[provider][action]
        )
        if action in ("save", "run"):
            expect(page.locator(f"#{provider}-backup-{action}-btn")).to_have_text(
                "backing up…"
                if action == "run"
                else "saving…"
                if provider == "webdav"
                else "checking…"
            )
        for action in ("save", "disconnect", "run"):
            expect(page.locator(f"#{provider}-backup-{action}-btn")).to_be_disabled()
        page.evaluate(
            """async provider => {
                for (const action of ['save', 'disconnect', 'run']) {
                    document.getElementById(`${provider}-backup-${action}-btn`)
                        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
                }
                await fetch(`/api/backup/${provider}`);
            }""",
            provider,
        )
        expect(page.locator(".dialog-overlay")).to_have_count(0)
        assert len(remote_writes[provider]) == expected_writes, remote_writes[provider]

    for provider in remote_configs:
        assert_remote_pending(provider, 1)
    page.locator("#webdav-backup-username").fill("example-newer-draft")
    page.locator("#s3-backup-bucket").fill("example-newer-draft")
    close_and_reopen("backup")
    for provider in remote_configs:
        assert_remote_pending(provider, 1)
        assert remote_writes[provider][0][0] == "PUT"
        hold_remote_lists.add(provider)
        remote_writes[provider][0][1].fulfill(json=remote_configs[provider])
        page.wait_for_function(
            "provider => window.__settingsPaneRemoteLists?.[provider] === true",
            arg=provider,
        )
        assert_remote_pending(provider, 1)
        remote_lists[provider][0].fulfill(json={"backups": []})
        for action in ("save", "disconnect", "run"):
            expect(page.locator(f"#{provider}-backup-{action}-btn")).to_be_enabled()

    for provider in remote_configs:
        draft = page.locator(
            f"#{provider}-backup-{'username' if provider == 'webdav' else 'bucket'}"
        )
        expect(draft).to_have_value("example-newer-draft")
        for action, method, rejected in (
            ("save", "PUT", True),
            ("run", "POST", False),
            ("disconnect", "DELETE", True),
        ):
            expected_writes = len(remote_writes[provider]) + 1
            page.locator(f"#{provider}-backup-{action}-btn").click()
            if action == "disconnect":
                page.locator(".dialog-overlay [data-dialog-confirm]").click()
            page.wait_for_function(
                """([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count""",
                arg=[provider, expected_writes],
            )
            assert_remote_pending(provider, expected_writes, action)
            expect(draft).to_be_editable()
            close_and_reopen("backup")
            assert_remote_pending(provider, expected_writes, action)
            assert remote_writes[provider][-1][0] == method
            if rejected:
                remote_writes[provider][-1][1].fulfill(
                    status=503, json={"detail": f"synthetic {provider} {action} rejected"}
                )
                expect(page.locator(f"#{provider}-backup-status")).to_have_text(
                    f"synthetic {provider} {action} rejected"
                )
            else:
                remote_writes[provider][-1][1].fulfill(json={})
            for button in ("save", "disconnect", "run"):
                expect(page.locator(f"#{provider}-backup-{button}-btn")).to_be_enabled()
            expect(draft).to_have_value("example-newer-draft")
            assert len(remote_writes[provider]) == expected_writes

        # A write started while confirmation is open prevents the later delete.
        page.locator(f"#{provider}-backup-disconnect-btn").click()
        expect(page.locator(".dialog-overlay")).to_be_visible()
        expected_writes = len(remote_writes[provider]) + 1
        page.locator(f"#{provider}-backup-save-btn").dispatch_event("click")
        page.wait_for_function(
            """([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count""",
            arg=[provider, expected_writes],
        )
        page.locator(".dialog-overlay [data-dialog-confirm]").click()
        assert_remote_pending(provider, expected_writes)
        assert remote_writes[provider][-1][0] == "PUT"
        remote_writes[provider][-1][1].fulfill(json=remote_configs[provider])
        for action in ("save", "disconnect", "run"):
            expect(page.locator(f"#{provider}-backup-{action}-btn")).to_be_enabled()

        # Successful removal and a failed first save keep unconfigured actions off.
        page.locator(f"#{provider}-backup-disconnect-btn").click()
        page.locator(".dialog-overlay [data-dialog-confirm]").click()
        expected_writes += 1
        page.wait_for_function(
            """([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count""",
            arg=[provider, expected_writes],
        )
        assert_remote_pending(provider, expected_writes, "disconnect")
        expect(draft).to_be_editable()
        draft.fill("example-after-disconnect-start")
        assert remote_writes[provider][-1][0] == "DELETE"
        remote_configs[provider] = {"configured": False}
        remote_writes[provider][-1][1].fulfill(json={})
        expect(page.locator(f"#{provider}-backup-save-btn")).to_be_enabled()
        expect(page.locator(f"#{provider}-backup-disconnect-btn")).to_be_hidden()
        expect(page.locator(f"#{provider}-backup-run-btn")).to_be_disabled()
        expect(draft).to_have_value("example-after-disconnect-start")
        if provider == "webdav":
            page.locator("#webdav-backup-password").fill("example")
        else:
            page.locator("#s3-backup-access-key-id").fill("example")
            page.locator("#s3-backup-secret-access-key").fill("example")
        page.locator(f"#{provider}-backup-save-btn").click()
        expected_writes += 1
        page.wait_for_function(
            """([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count""",
            arg=[provider, expected_writes],
        )
        assert_remote_pending(provider, expected_writes)
        close_and_reopen("backup")
        assert_remote_pending(provider, expected_writes)
        remote_writes[provider][-1][1].fulfill(
            status=503, json={"detail": f"synthetic {provider} first save rejected"}
        )
        expect(page.locator(f"#{provider}-backup-status")).to_have_text(
            f"synthetic {provider} first save rejected"
        )
        expect(page.locator(f"#{provider}-backup-save-btn")).to_be_enabled()
        expect(page.locator(f"#{provider}-backup-disconnect-btn")).to_be_hidden()
        expect(page.locator(f"#{provider}-backup-run-btn")).to_be_disabled()
        expect(draft).to_have_value("example-after-disconnect-start")
        assert len(remote_writes[provider]) == expected_writes

    (destination / "backup-mutation-order.json").write_text(
        json.dumps(
            {
                provider: [method for method, _ in writes]
                for provider, writes in remote_writes.items()
            },
            indent=2,
        )
    )

    # Remote restore owns the same provider lock and requires a verified staged receipt.
    remote_configs["webdav"] = {
        "configured": True,
        "url": "https://backup.example.test/configured",
        "username": "example",
    }
    remote_configs["s3"] = {
        "configured": True,
        "credentials_set": True,
        "endpoint": "https://storage.example.test/",
        "region": "us-east-1",
        "bucket": "example",
        "prefix": "",
        "addressing_style": "path",
    }
    for provider in remote_configs:
        remote_backup_files[provider] = [{"filename": "example-backup.enc", "bytes": 12}]
    close_and_reopen("backup")
    restore_evidence = {}
    for provider in remote_configs:
        restore = page.locator(f"#{provider}-backup-restore-btn")
        restore_status = page.locator(f"#{provider}-backup-restore-status")
        save = page.locator(f"#{provider}-backup-save-btn")
        expect(restore).to_be_enabled()
        expected_writes = len(remote_writes[provider]) + 1
        save.click()
        page.wait_for_function(
            "([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count",
            arg=[provider, expected_writes],
        )
        expect(restore).to_be_disabled()
        restore.dispatch_event("click")
        assert len(remote_writes[provider]) == expected_writes
        remote_writes[provider][-1][1].fulfill(json=remote_configs[provider])
        expect(save).to_be_enabled()
        expect(restore).to_be_enabled()
        for outcome in ("invalid", "failure", "success"):
            restore.click()
            expected_writes += 1
            page.wait_for_function(
                "([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count",
                arg=[provider, expected_writes],
            )
            expect(restore_status).to_have_text("downloading, verifying, and staging…")
            for action in ("save", "disconnect", "run", "restore"):
                expect(page.locator(f"#{provider}-backup-{action}-btn")).to_be_disabled()
                page.locator(f"#{provider}-backup-{action}-btn").dispatch_event("click")
            expect(page.locator(".dialog-overlay")).to_have_count(0)
            expect(page.locator(f"#{provider}-backup-list")).to_be_disabled()
            expect(page.locator(f"#{provider}-backup-recovery-key-btn")).to_be_disabled()
            page.locator(f"#{provider}-backup-refresh-btn").dispatch_event("click")
            close_and_reopen("backup")
            expect(restore).to_be_disabled()
            expect(restore).to_have_text("staging…")
            expect(restore_status).to_have_text("downloading, verifying, and staging…")
            assert len(remote_writes[provider]) == expected_writes
            method, request = remote_writes[provider][-1]
            assert method == "POST" and urlsplit(request.request.url).path.endswith("/restore")
            assert 'name="filename"' in request.request.post_data
            assert "example-backup.enc" in request.request.post_data
            if outcome == "invalid":
                request.fulfill(json={})
                expect(restore_status).to_have_text("could not verify the backup response")
            elif outcome == "failure":
                request.fulfill(
                    status=503, json={"detail": f"synthetic {provider} restore rejected"}
                )
                expect(restore_status).to_have_text(f"synthetic {provider} restore rejected")
            else:
                request.fulfill(
                    json={
                        "status": "staged",
                        "restore_id": "a" * 32,
                        "apply_command": "example mismatched command",
                    }
                )
                expect(restore_status).to_have_text(
                    f"verified and staged. live data is unchanged. stop Alles, then run: alles restore apply {'a' * 32}"
                )
            for action in ("save", "disconnect", "run", "restore"):
                expect(page.locator(f"#{provider}-backup-{action}-btn")).to_be_enabled()
            expect(restore).to_have_text("verify and stage selected restore")
            assert len(remote_writes[provider]) == expected_writes
        restore_evidence[provider] = {
            "malformed_receipt_rejected": True,
            "success_failure_released": True,
            "mutual_exclusion_on_reopen": True,
        }
    (destination / "remote-restore-lifecycle.json").write_text(
        json.dumps(restore_evidence, indent=2)
    )

    # Successful writes reconcile only the current opening after their list read is disposed.
    list_acknowledgments = []
    for provider in remote_configs:
        for action in ("save", "run"):
            for mode in ("reopen", "active", "closed_again"):
                old_file = {"filename": "example-old.enc", "bytes": 1}
                new_file = {
                    "filename": f"example-current-{provider}-{action}-{mode}.enc",
                    "bytes": 2,
                }
                stale_file = {"filename": "example-stale.enc", "bytes": 3}
                remote_backup_files[provider] = [old_file] if action == "save" else []
                page.locator(f"#{provider}-backup-refresh-btn").click()
                expect(page.locator(f"#{provider}-backup-list")).to_have_attribute(
                    "data-value", old_file["filename"] if action == "save" else ""
                )
                expect(page.locator(f"#{provider}-backup-selection")).to_contain_text(
                    old_file["filename"] if action == "save" else "no remote backups yet."
                )
                expect(page.locator(f"#{provider}-backup-refresh-btn")).to_be_enabled()
                reads_before = remote_list_reads[provider]
                expected_writes = len(remote_writes[provider]) + 1
                page.locator(f"#{provider}-backup-{action}-btn").click()
                page.wait_for_function(
                    "([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count",
                    arg=[provider, expected_writes],
                )
                page.evaluate(
                    "provider => window.__settingsPaneRemoteLists[provider] = false", provider
                )
                hold_remote_lists.add(provider)
                remote_writes[provider][-1][1].fulfill(json=remote_configs[provider])
                page.wait_for_function(
                    "provider => window.__settingsPaneRemoteLists[provider] === true", arg=provider
                )
                assert remote_list_reads[provider] == reads_before + 1
                assert_remote_pending(provider, expected_writes, action)
                other = "s3" if provider == "webdav" else "webdav"
                expect(page.locator(f"#{other}-backup-run-btn")).to_be_enabled()
                draft = page.locator(
                    f"#{provider}-backup-{'username' if provider == 'webdav' else 'bucket'}"
                )
                draft_value = f"example-list-draft-{mode}"
                draft.fill(draft_value)
                remote_backup_files[provider] = [new_file]
                if mode != "active":
                    close_and_reopen("backup")
                    assert_remote_pending(provider, expected_writes, action)
                    if mode == "closed_again":
                        page.locator("#settings-modal-close").click()
                        expect(page.locator("#settings-modal")).to_be_hidden()
                remote_lists[provider][-1].fulfill(
                    json={"backups": [new_file] if mode == "active" else [stale_file]}
                )
                expect(page.locator(f"#{provider}-backup-save-btn")).to_be_enabled()
                expect(draft).to_have_value(draft_value)
                if mode == "closed_again":
                    assert remote_list_reads[provider] == reads_before + 1
                    expect(page.locator("#settings-modal")).to_be_hidden()
                    page.locator("#today-settings").click()
                    pane("backup")
                expect(page.locator(f"#{provider}-backup-list")).to_have_attribute(
                    "data-value", new_file["filename"]
                )
                expect(page.locator(f"#{provider}-backup-selection")).to_contain_text(
                    new_file["filename"]
                )
                expect(page.locator(f"#{provider}-backup-list")).to_be_enabled()
                expect(page.locator(f"#{provider}-backup-restore-btn")).to_be_enabled()
                expect(page.locator(f"#{provider}-backup-refresh-btn")).to_be_enabled()
                assert "example-stale.enc" not in page.locator(
                    f"#{provider}-backup-list"
                ).get_attribute("data-options")
                assert remote_list_reads[provider] == reads_before + (1 if mode == "active" else 2)
                assert len(remote_writes[provider]) == expected_writes
                expect(draft).to_have_value(draft_value)
                if mode != "closed_again":
                    expect(page.locator(f"#{provider}-backup-status")).to_have_text(
                        "saved; newer connection edits kept here"
                        if action == "save"
                        else "backup uploaded and verified"
                        if provider == "webdav"
                        else "backup copied and verified by read-back"
                    )
                list_acknowledgments.append(
                    {
                        "provider": provider,
                        "action": action,
                        "mode": mode,
                        "current_file_published": True,
                        "stale_file_excluded": True,
                        "list_reads": remote_list_reads[provider] - reads_before,
                        "draft_kept": True,
                        "closed_opening_skipped": mode == "closed_again",
                    }
                )
    (destination / "backup-list-acknowledgments.json").write_text(
        json.dumps(list_acknowledgments, indent=2)
    )

    # Reopening during the mutation uses its one current post-write list acknowledgment.
    mutation_list_acknowledgments = []
    for provider in remote_configs:
        for action in ("save", "run"):
            baseline = {"filename": "example-before-mutation.enc", "bytes": 7}
            current_file = {
                "filename": f"example-{provider}-{action}-after-mutation.enc",
                "bytes": 12,
            }
            remote_backup_files[provider] = [baseline]
            page.locator(f"#{provider}-backup-refresh-btn").click()
            expect(page.locator(f"#{provider}-backup-list")).to_have_attribute(
                "data-value", baseline["filename"]
            )
            expect(page.locator(f"#{provider}-backup-selection")).to_contain_text(
                baseline["filename"]
            )
            expect(page.locator(f"#{provider}-backup-refresh-btn")).to_be_enabled()
            reads_before = remote_list_reads[provider]
            expected_writes = len(remote_writes[provider]) + 1
            page.locator(f"#{provider}-backup-{action}-btn").click()
            page.wait_for_function(
                "([provider, count]) => window.__settingsPaneRemoteWrites?.[provider] === count",
                arg=[provider, expected_writes],
            )
            assert_remote_pending(provider, expected_writes, action)
            draft = page.locator(
                f"#{provider}-backup-{'username' if provider == 'webdav' else 'bucket'}"
            )
            draft_value = f"example-{provider}-{action}-mutation-draft"
            draft.fill(draft_value)
            close_and_reopen("backup")
            assert_remote_pending(provider, expected_writes, action)
            expect(draft).to_have_value(draft_value)
            other = "s3" if provider == "webdav" else "webdav"
            expect(page.locator(f"#{other}-backup-run-btn")).to_be_enabled()
            assert remote_list_reads[provider] == reads_before
            remote_backup_files[provider] = [current_file]
            remote_list_limits[provider] = reads_before + 1
            remote_writes[provider][-1][1].fulfill(json=remote_configs[provider])
            expect(page.locator(f"#{provider}-backup-save-btn")).to_be_enabled()
            expect(page.locator(f"#{provider}-backup-list")).to_have_attribute(
                "data-value", current_file["filename"]
            )
            expect(page.locator(f"#{provider}-backup-selection")).to_contain_text(
                current_file["filename"]
            )
            expect(page.locator(f"#{provider}-backup-restore-btn")).to_be_enabled()
            expect(page.locator(f"#{provider}-backup-refresh-btn")).to_be_enabled()
            expect(page.locator(f"#{provider}-backup-status")).to_have_text(
                "saved; newer connection edits kept here"
                if action == "save"
                else "backup uploaded and verified"
                if provider == "webdav"
                else "backup copied and verified by read-back"
            )
            expect(draft).to_have_value(draft_value)
            page.wait_for_load_state("networkidle")
            assert remote_list_reads[provider] == reads_before + 1
            assert len(remote_writes[provider]) == expected_writes
            remote_list_limits.pop(provider)
            mutation_list_acknowledgments.append(
                {
                    "provider": provider,
                    "action": action,
                    "current_list_reads": 1,
                    "draft_and_success_kept": True,
                }
            )
    (destination / "backup-mutation-list-acknowledgments.json").write_text(
        json.dumps(mutation_list_acknowledgments, indent=2)
    )

    # Connection drafts survive status refresh; no provider credentials leave the test.
    discord = {
        "configured": False,
        "enabled": True,
        "bot_name": "fixture bot",
        "allowed_channel_ids": ["123"],
    }
    discord_reads = []
    discord_mutations = []
    discord_connect = []

    def discord_api(route):
        if route.request.method == "GET":
            discord_reads.append(True)
            route.fulfill(json=discord)
        elif route.request.method == "POST":
            assert route.request.post_data_json == {"bot_token": "example"}
            discord_mutations.append("connect")
            discord["configured"] = True
            discord_connect.append(route)
            page.evaluate("window.__settingsPaneDiscordConnectReady = true")
        elif route.request.method == "PATCH":
            discord_mutations.append("channels")
            discord.update(route.request.post_data_json)
            route.fulfill(json=discord)
        else:
            route.fulfill(status=418, json={"detail": "unexpected synthetic Discord write"})

    connection_name = '<strong id="example-connection-label">example</strong>'
    agent_status = {
        "tool_count": 17,
        "opencode": {"installed": True},
        "mcp": {"connected_tool_count": 3},
        "skills": {"count": 2},
        "sandbox": {"docker": True},
        "computer_use": {"pyautogui": False},
        "connections": ["github", connection_name],
        "tools": ["example-tool"],
    }
    agent_reads = []
    hold_agent_read = False
    held_agent_reads = []

    def agent_read(route):
        nonlocal hold_agent_read
        agent_reads.append(True)
        if hold_agent_read:
            hold_agent_read = False
            held_agent_reads.append(route)
            page.evaluate("window.__settingsPaneAgentReadHeld = true")
        else:
            route.fulfill(json={**agent_status, "tool_count": 16 + len(agent_reads)})

    page.route("**/api/agent/status", agent_read)
    page.route("**/api/jarvis/discord", discord_api)
    pane("tools")
    status_fields = page.locator("#agent-status-grid > div > strong")
    expect(status_fields).to_have_count(7)
    expect(page.locator("#agent-status-grid #example-connection-label")).to_have_count(0)
    expect(status_fields).to_have_text(
        ["17", "installed", "3", "2", "yes", "no", f"github, {connection_name}"]
    )
    expect(page.locator("#agent-tool-list")).to_have_text("example-tool")
    page.locator("#agent-status-refresh-btn").click()
    expect(status_fields.first).to_have_text("18")
    assert len(agent_reads) == 2
    hold_agent_read = True
    page.locator("#agent-status-refresh-btn").click()
    page.wait_for_function("window.__settingsPaneAgentReadHeld === true")
    close_and_reopen("tools")
    expect(status_fields.first).to_have_text("20")
    held_agent_reads[0].fulfill(json={**agent_status, "tool_count": 999})
    page.wait_for_load_state("networkidle")
    expect(status_fields.first).to_have_text("20")

    # Approved-root writes cannot overlap, and retain drafts through success/error/reopen.
    roots = page.locator("#s-agent-roots")
    roots_save = page.locator("#s-agent-roots-save")
    approved = Path(os.environ["ALLES_DATA"], "example-approved")
    approved.mkdir(exist_ok=True)
    root_writes = []

    def hold_roots_write(route):
        if route.request.method == "PATCH" and "agent_allowed_roots" in (
            route.request.post_data_json or {}
        ):
            root_writes.append(route)
            page.evaluate("count => window.__settingsPaneRootWrites = count", len(root_writes))
        else:
            route.continue_()

    page.route("**/api/settings", hold_roots_write)
    roots.fill(str(approved))
    roots_save.click()
    page.wait_for_function("window.__settingsPaneRootWrites === 1")
    roots.fill("")
    roots_save.dispatch_event("click")
    close_and_reopen("tools")
    expect(roots_save).to_be_disabled()
    expect(roots_save).to_have_text("saving…")
    expect(roots).to_have_value("")
    roots_save.dispatch_event("click")
    assert len(root_writes) == 1
    first_root_response = root_writes[0].fetch()
    assert first_root_response.ok
    root_writes[0].fulfill(response=first_root_response)
    expect(roots_save).to_be_enabled()
    expect(roots).to_have_value("")
    assert api.get("/api/settings").json()["agent_allowed_roots"] == [str(approved.resolve())]
    roots_save.click()
    page.wait_for_function("window.__settingsPaneRootWrites === 2")
    root_writes[1].fulfill(status=503, json={"detail": "synthetic approved roots rejected"})
    expect(roots_save).to_be_enabled()
    expect(page.locator("#toast-container .toast").last).to_have_text(
        "synthetic approved roots rejected"
    )
    expect(roots).to_have_value("")
    roots_save.click()
    page.wait_for_function("window.__settingsPaneRootWrites === 3")
    final_root_response = root_writes[2].fetch()
    assert final_root_response.ok
    root_writes[2].fulfill(response=final_root_response)
    expect(roots_save).to_be_enabled()
    assert api.get("/api/settings").json()["agent_allowed_roots"] == []
    page.unroute("**/api/settings", hold_roots_write)
    (destination / "agent-read-write-lifecycle.json").write_text(
        json.dumps(
            {
                "visible_refresh_reads": 2,
                "disposed_read_excluded": True,
                "root_writes": len(root_writes),
                "newer_draft_retained": True,
                "final_server_roots": [],
            },
            indent=2,
        )
    )
    expect(page.locator("#jarvis-discord-setup")).to_be_visible()
    page.locator("#jarvis-discord-token").fill("example")
    page.locator("#jarvis-discord-connect").click()
    page.wait_for_function("window.__settingsPaneDiscordConnectReady === true")
    close_and_reopen("tools")
    discord_connect[0].fulfill(json={**discord, "pairing_code": "example-connect-code"})
    expect(page.locator("#jarvis-discord-manage")).to_be_visible()
    expect(page.locator("#jarvis-pairing-code")).to_be_visible()
    expect(page.locator("#jarvis-pairing-code")).to_have_text("example-connect-code")
    expect(page.locator("#jarvis-discord-token")).to_have_value("")
    page.locator("#jarvis-discord-channels").fill("123\n456")
    page.locator("#s-agent-roots").fill("/synthetic/owner-draft")
    page.locator("#jarvis-discord-quiet").click()
    page.locator("#jarvis-discord-quiet-start").fill("22:30")
    discord_pair = []

    def delayed_discord_pair(route):
        assert route.request.method == "POST"
        assert route.request.post_data_json == {"revoke_owner": False}
        discord_mutations.append("pair")
        discord_pair.append(route)
        page.evaluate("window.__settingsPaneDiscordPairReady = true")

    page.route("**/api/jarvis/discord/pairing-code", delayed_discord_pair)
    page.locator("#jarvis-discord-pair").click()
    page.wait_for_function("window.__settingsPaneDiscordPairReady === true")
    page.locator("#jarvis-discord-channels").fill("123\n456\n789")
    page.locator("#jarvis-discord-save-channels").click()
    page.locator("#jarvis-discord-channels").fill("123\n456\n789\n999")
    close_and_reopen("tools")
    assert discord_mutations == ["connect", "pair"]
    discord_pair[0].fulfill(json={**discord, "pairing_code": "example-pair-code"})
    expect(page.locator("#jarvis-pairing-code")).to_have_text("example-pair-code")
    expect(page.locator("#toast-container .toast").last).to_have_text("approved channels saved")
    assert discord_mutations == ["connect", "pair", "channels"]
    expect(page.locator("#jarvis-discord-channels")).to_have_value("123\n456\n789\n999")
    expect(page.locator("#jarvis-discord-quiet-start")).to_have_value("22:30")
    expect(page.locator("#s-agent-roots")).to_have_value("/synthetic/owner-draft")
    reads_before = len(discord_reads)
    discord["connection_state"] = "fixture status reloaded"
    close_and_reopen("tools")
    expect(page.locator("#jarvis-discord-head-state")).to_have_text("fixture status reloaded")
    assert len(discord_reads) == reads_before + 1
    expect(page.locator("#jarvis-pairing-code")).to_have_text("example-pair-code")
    expect(page.locator("#jarvis-discord-channels")).to_have_value("123\n456\n789\n999")
    expect(page.locator("#jarvis-discord-quiet-start")).to_have_value("22:30")

    # Discord claims actions before queueing and keeps later drafts and one-time codes.
    page.unroute("**/api/jarvis/discord", discord_api)
    page.unroute("**/api/jarvis/discord/pairing-code", delayed_discord_pair)
    discord_action_evidence = []
    action_connects = []
    action_pairs = []
    action_patches = []
    action_state = {
        "configured": False,
        "enabled": True,
        "paired": False,
        "bot_name": "example bot",
        "allowed_channel_ids": [],
        "quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00", "timezone": "UTC"},
    }

    def hold_discord_action(route):
        method = route.request.method
        if method == "GET":
            route.fulfill(json=action_state)
        elif method == "POST":
            action_connects.append(route)
            page.evaluate("n => window.__settingsDiscordActionConnects = n", len(action_connects))
        elif method == "PATCH":
            action_patches.append(route)
            page.evaluate("n => window.__settingsDiscordActionPatches = n", len(action_patches))
        else:
            route.fulfill(status=418, json={"detail": "unexpected example Discord action"})

    def hold_discord_code(route):
        action_pairs.append(route)
        page.evaluate("n => window.__settingsDiscordActionPairs = n", len(action_pairs))

    page.route("**/api/jarvis/discord", hold_discord_action)
    page.route("**/api/jarvis/discord/pairing-code", hold_discord_code)
    token = page.locator("#jarvis-discord-token")
    connect = page.locator("#jarvis-discord-connect")
    for outcome in ("newer", "failure", "unchanged"):
        action_state["configured"] = False
        close_and_reopen("tools")
        expect(page.locator("#jarvis-discord-setup")).to_be_visible()
        token.fill("example-old")
        count = len(action_connects) + 1
        connect.click()
        page.wait_for_function("n => window.__settingsDiscordActionConnects === n", arg=count)
        expect(connect).to_be_disabled()
        connect.dispatch_event("click")
        if outcome == "newer":
            token.fill("example-newer-draft")
        close_and_reopen("tools")
        expect(connect).to_be_disabled()
        expect(token).to_be_editable()
        connect.dispatch_event("click")
        assert len(action_connects) == count
        assert action_connects[-1].request.post_data_json == {"bot_token": "example-old"}
        if outcome == "failure":
            action_connects[-1].fulfill(
                status=503, json={"detail": "synthetic Discord connect rejected"}
            )
            expect(connect).to_be_enabled()
            expect(token).to_have_value("example-old")
            expect(page.locator("#toast-container .toast").last).to_have_text(
                "synthetic Discord connect rejected"
            )
            connect.click()
            count += 1
            page.wait_for_function("n => window.__settingsDiscordActionConnects === n", arg=count)
        action_state["configured"] = True
        code = f"example-connect-{outcome}"
        action_connects[-1].fulfill(json={**action_state, "pairing_code": code})
        expect(connect).to_be_enabled()
        expect(page.locator("#jarvis-pairing-code")).to_have_text(code)
        expect(token).to_have_value("example-newer-draft" if outcome == "newer" else "")
        page.wait_for_load_state("networkidle")
        assert len(action_connects) == count
        discord_action_evidence.append(
            {
                "action": "connect",
                "outcome": outcome,
                "repeated_enqueue_excluded": True,
                "matching_token_only_cleared": True,
            }
        )

    pair = page.locator("#jarvis-discord-pair")
    revoke = page.locator("#jarvis-discord-revoke")
    channels = page.locator("#jarvis-discord-channels")
    quiet_start = page.locator("#jarvis-discord-quiet-start")
    action_state["paired"] = True
    close_and_reopen("tools")
    expect(revoke).to_be_visible()
    for rejected in (True, False):
        previous_code = page.locator("#jarvis-pairing-code").inner_text()
        count = len(action_pairs) + 1
        pair.click()
        page.wait_for_function("n => window.__settingsDiscordActionPairs === n", arg=count)
        expect(pair).to_be_disabled()
        expect(revoke).to_be_disabled()
        pair.dispatch_event("click")
        revoke.dispatch_event("click")
        expect(page.locator(".dialog-overlay")).to_have_count(0)
        channels.fill("123\n456")
        quiet_start.fill("21:30")
        close_and_reopen("tools")
        expect(pair).to_be_disabled()
        expect(revoke).to_be_disabled()
        assert len(action_pairs) == count
        assert action_pairs[-1].request.post_data_json == {"revoke_owner": False}
        if rejected:
            action_pairs[-1].fulfill(status=503, json={"detail": "synthetic pairing rejected"})
            expect(pair).to_be_enabled()
            expect(revoke).to_be_enabled()
            expect(page.locator("#jarvis-pairing-code")).to_have_text(previous_code)
            pair.click()
            count += 1
            page.wait_for_function("n => window.__settingsDiscordActionPairs === n", arg=count)
        code = "example-retry-pair" if rejected else "example-current-pair"
        action_pairs[-1].fulfill(json={**action_state, "pairing_code": code})
        expect(pair).to_be_enabled()
        expect(revoke).to_be_enabled()
        expect(page.locator("#jarvis-pairing-code")).to_have_text(code)
        expect(channels).to_have_value("123\n456")
        expect(quiet_start).to_have_value("21:30")
        page.wait_for_load_state("networkidle")
        assert len(action_pairs) == count
        discord_action_evidence.append(
            {
                "action": "pair",
                "rejected_then_retry": rejected,
                "one_time_code_retained": True,
                "newer_sibling_drafts_kept": True,
            }
        )

    # An independent pairing begun during confirmation wins the code action claim.
    count = len(action_pairs)
    revoke.click()
    page.locator("[data-dialog-cancel]").click()
    assert len(action_pairs) == count
    expect(pair).to_be_enabled()
    revoke.click()
    pair.dispatch_event("click")
    page.wait_for_function("n => window.__settingsDiscordActionPairs === n", arg=count + 1)
    page.locator("[data-dialog-confirm]").click()
    assert len(action_pairs) == count + 1
    action_pairs[-1].fulfill(json={**action_state, "pairing_code": "example-confirmation-pair"})
    expect(pair).to_be_enabled()
    expect(page.locator("#jarvis-pairing-code")).to_have_text("example-confirmation-pair")
    discord_action_evidence.append(
        {"action": "revoke", "cancel_no_write": True, "confirmation_rechecks_claim": True}
    )
    for rejected in (True, False):
        count = len(action_pairs) + 1
        revoke.click()
        page.locator("[data-dialog-confirm]").click()
        page.wait_for_function("n => window.__settingsDiscordActionPairs === n", arg=count)
        expect(pair).to_be_disabled()
        expect(revoke).to_be_disabled()
        pair.dispatch_event("click")
        revoke.dispatch_event("click")
        expect(page.locator(".dialog-overlay")).to_have_count(0)
        close_and_reopen("tools")
        assert len(action_pairs) == count
        assert action_pairs[-1].request.post_data_json == {"revoke_owner": True}
        if rejected:
            action_pairs[-1].fulfill(status=503, json={"detail": "synthetic owner revoke rejected"})
            expect(pair).to_be_enabled()
            expect(revoke).to_be_enabled()
            expect(page.locator("#jarvis-pairing-code")).to_have_text("example-confirmation-pair")
        else:
            action_pairs[-1].fulfill(json={**action_state, "pairing_code": "example-revoked-code"})
            expect(pair).to_be_enabled()
            expect(revoke).to_be_enabled()
            expect(page.locator("#jarvis-pairing-code")).to_have_text("example-revoked-code")
        discord_action_evidence.append(
            {"action": "revoke", "rejected": rejected, "pending_repeats_excluded": True}
        )

    # Their own PATCH acknowledgments still preserve independently edited forms.
    for field, button_id, submitted, newer in (
        (channels, "jarvis-discord-save-channels", "123", "123\n456"),
        (quiet_start, "jarvis-discord-save-quiet", "22:30", "21:30"),
    ):
        code = page.locator("#jarvis-pairing-code").inner_text()
        field.fill(submitted)
        count = len(action_patches) + 1
        page.locator(f"#{button_id}").click()
        page.wait_for_function("n => window.__settingsDiscordActionPatches === n", arg=count)
        field.fill(newer)
        close_and_reopen("tools")
        action_state.update(action_patches[-1].request.post_data_json)
        action_patches[-1].fulfill(json=action_state)
        expect(field).to_have_value(newer)
        expect(page.locator("#jarvis-pairing-code")).to_have_text(code)
        expect(page.locator("#toast-container .toast").last).to_have_text(
            "approved channels saved" if button_id.endswith("channels") else "quiet hours saved"
        )
        discord_action_evidence.append(
            {"action": button_id, "newer_revision_kept": True, "pair_code_kept": True}
        )
    page.unroute("**/api/jarvis/discord", hold_discord_action)
    page.unroute("**/api/jarvis/discord/pairing-code", hold_discord_code)
    (destination / "discord-action-pending.json").write_text(
        json.dumps(discord_action_evidence, indent=2)
    )

    pane("credits")
    expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
    page.locator("#credits-search").fill("python")
    close_and_reopen("credits")
    expect(page.locator("#credits-search")).to_have_value("python")
    expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
    page.screenshot(path=str(destination / "credits.png"), full_page=True)
    page.locator("#credits-search").fill("")
    credit_entry = {
        "id": "example-entry",
        "name": "example entry",
        "summary": "example summary",
        "category": "application",
        "version": "example",
        "license": "example",
        "source_url": "https://example.test",
        "license_texts": [],
        "notice_texts": [],
    }
    page.route(
        "**/api/credits",
        lambda route: route.fulfill(
            json={"entries": [credit_entry], "coverage": {"complete": True, "gap_count": 0}}
        ),
    )
    credit_reads = []

    def hold_credit_detail(route):
        credit_reads.append(route)
        page.evaluate("count => window.__settingsPaneCreditReads = count", len(credit_reads))

    page.route("**/api/credits/example-entry", hold_credit_detail)
    for current_first in (True, False):
        old_index = len(credit_reads)
        close_and_reopen("credits")
        page.wait_for_function(
            "count => window.__settingsPaneCreditReads === count", arg=old_index + 1
        )
        close_and_reopen("credits")
        page.wait_for_function(
            "count => window.__settingsPaneCreditReads === count", arg=old_index + 2
        )
        fresh = {**credit_entry, "name": "example current detail"}
        stale = {**credit_entry, "name": "example stale detail"}
        if current_first:
            credit_reads[old_index + 1].fulfill(json=fresh)
            expect(page.locator("#credits-detail h3")).to_have_text("example current detail")
            credit_reads[old_index].fulfill(json=stale)
            page.wait_for_load_state("networkidle")
        else:
            credit_reads[old_index].fulfill(json=stale)
            page.locator('[data-credit-id="example-entry"]').click()
            expect(page.locator("#credits-detail h3")).to_have_count(0)
            assert len(credit_reads) == old_index + 2
            credit_reads[old_index + 1].fulfill(json=fresh)
            expect(page.locator("#credits-detail h3")).to_have_text("example current detail")
        page.locator('[data-credit-id="example-entry"]').click()
        expect(page.locator("#credits-detail h3")).to_have_text("example current detail")
        assert len(credit_reads) == old_index + 2
    page.unroute("**/api/credits/example-entry", hold_credit_detail)
    page.unroute("**/api/credits")
    (destination / "credits-cache-lifecycle.json").write_text(
        json.dumps(
            {
                "reads": len(credit_reads),
                "late_cache_publication_excluded": True,
                "new_pending_deduplicated": True,
            },
            indent=2,
        )
    )
    for name in ("home", "notifications", "models", "backup", "tools"):
        pane(name)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(destination / f"{name}.png"), full_page=True)
    page.locator("#settings-modal-close").click()
    page.goto(f"http://finance.localhost:{urlsplit(page.url).port}/", wait_until="networkidle")
    expect(page.locator("#finance-view")).to_be_visible()
    page.screenshot(path=str(destination / "finance-boot.png"), full_page=True)
    assert events["pageerrors"] == [], events
    expected_errors = {
        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)": 39
        + connection_failures["503"]
        + retained_failures["503"]
        + retained_list_failures
        + persona_failures["503"]
        + action_failures["503"]
        + local_failures["503"]
        + developer_failures["503"]
        + webhook_mutual_failures["503"],
        "Failed to load resource: the server responded with a status of 404 (Not Found)": 1
        + persona_failures["404"],
        "Failed to load resource: the server responded with a status of 403 (Forbidden)": connection_failures[
            "403"
        ]
        + action_failures["403"]
        + developer_failures["403"],
        "Failed to load resource: net::ERR_FAILED": connection_failures["network"]
        + retained_failures["network"]
        + persona_failures["network"]
        + action_failures["network"]
        + local_failures["network"]
        + developer_failures["network"]
        + webhook_mutual_failures["network"],
    }
    assert {
        message: events["console_errors"].count(message) for message in expected_errors
    } == expected_errors, events
    assert len(events["console_errors"]) == sum(expected_errors.values()), events
    (destination / "events.json").write_text(json.dumps(events, indent=2))


def run():
    port = os.environ["PORT"]
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(f"http://127.0.0.1:{port}", run_id)
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, theme, zoom in (
                (1440, "dark", 1),
                (1440, "light", 1),
                (390, "dark", 1),
                (390, "light", 2),
            ):
                destination = output / f"{width}-{theme}-{zoom}"
                destination.mkdir(exist_ok=True)
                context = browser.new_context(
                    base_url=f"http://127.0.0.1:{port}",
                    viewport={"width": width, "height": 900},
                    reduced_motion="reduce",
                    service_workers="block",
                )
                try:
                    api = context.request
                    assert api.post("/api/setup/dismiss").ok
                    assert api.patch(
                        "/api/settings",
                        data={"clock_format": "auto", "region": "", "model_roles": {}},
                    ).ok
                    assert api.put("/api/appearance", data=from_legacy(theme, None)).ok
                    response = api.post(
                        "/api/models/endpoint",
                        data={
                            "name": "pane fixture",
                            "base_url": "http://127.0.0.1:1",
                            "provider_adapter": "manual",
                            "provider_id": "custom",
                            "auth_type": "none",
                        },
                    )
                    assert response.ok, response.text()
                    endpoint = response.json()["id"]
                    assert api.patch(
                        f"/api/models/endpoint/{endpoint}",
                        data={"models": ["fixture-a", "fixture-b"]},
                    ).ok
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    if zoom != 1:
                        page.add_init_script(
                            f"document.addEventListener('DOMContentLoaded', () => document.documentElement.style.zoom = '{zoom}')"
                        )
                    try:
                        exercise(page, api, endpoint, destination)
                    except BaseException:
                        page.screenshot(path=str(destination / "failure.png"), full_page=True)
                        raise
                    assert api.delete(f"/api/models/endpoint/{endpoint}").ok
                    records.append(
                        {
                            "scenario_id": "settings-pane-lifecycle",
                            "profile": destination.name,
                            "status": "passed",
                        }
                    )
                    (output / "scenarios.json").write_text(json.dumps(records, indent=2))
                finally:
                    context.close()
        finally:
            browser.close()
    print(json.dumps({"status": "passed", "profiles": len(records)}))


if __name__ == "__main__":
    run()
