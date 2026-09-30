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

    # The settings shortcut disposes a portal menu from the previous pane.
    pane("models")
    menu = page.locator('[data-role-select="aide_chat"]')
    menu.click()
    expect(page.locator(".custom-dropdown-panel")).to_be_visible()
    page.keyboard.press("Control+,")
    expect(page.locator("#s-pane-general")).to_be_visible()
    expect(page.locator(".custom-dropdown-panel")).to_have_count(0)
    expect(menu).to_have_attribute("aria-expanded", "false")

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
    page.locator("#webdav-backup-password").fill("synthetic-test-password")
    page.locator("#webdav-backup-save-btn").click()
    expect(page.locator("#webdav-backup-save-btn")).to_be_disabled()
    expect(page.locator("#webdav-backup-password")).to_have_value("")
    page.wait_for_function("window.__settingsPaneBackupSaveReady === true")
    assert len(backup_save) == 1
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
    remote_lists = {provider: [] for provider in remote_configs}
    hold_remote_lists = set()

    for provider in remote_configs:

        def remote_api(route, request, provider=provider):
            if route.request.method == "GET":
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
                    {"backups": []}
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
    page.locator("#s3-backup-region").fill("us-east-1")
    page.locator("#webdav-backup-save-btn").click()
    page.wait_for_function("window.__settingsPaneRemoteWrites?.webdav === 1")
    expect(page.locator("#s3-backup-save-btn")).to_be_enabled()
    page.locator("#s3-backup-save-btn").click()
    page.wait_for_function("window.__settingsPaneRemoteWrites?.s3 === 1")
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
    page.route("**/api/agent/status", lambda route: route.fulfill(json=agent_status))
    page.route("**/api/jarvis/discord", discord_api)
    pane("tools")
    status_fields = page.locator("#agent-status-grid > div > strong")
    expect(status_fields).to_have_count(7)
    expect(page.locator("#agent-status-grid #example-connection-label")).to_have_count(0)
    expect(status_fields).to_have_text(
        ["17", "installed", "3", "2", "yes", "no", f"github, {connection_name}"]
    )
    expect(page.locator("#agent-tool-list")).to_have_text("example-tool")
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

    pane("credits")
    expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
    page.locator("#credits-search").fill("python")
    close_and_reopen("credits")
    expect(page.locator("#credits-search")).to_have_value("python")
    expect(page.locator("#credits-settings-workbench")).to_have_attribute("aria-busy", "false")
    page.screenshot(path=str(destination / "credits.png"), full_page=True)
    for name in ("home", "notifications", "models", "backup", "tools"):
        pane(name)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(destination / f"{name}.png"), full_page=True)
    page.locator("#settings-modal-close").click()
    page.goto(f"http://finance.localhost:{urlsplit(page.url).port}/", wait_until="networkidle")
    expect(page.locator("#finance-view")).to_be_visible()
    page.screenshot(path=str(destination / "finance-boot.png"), full_page=True)
    assert events["pageerrors"] == [], events
    assert (
        events["console_errors"]
        == [
            "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
        ]
        * 7
    ), events
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
