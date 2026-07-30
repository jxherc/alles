"""Rendered Phase 6 Docs, scoped Aide, and Journal browser gate.

Run against an isolated Alles server, for example:

    test_root="$(python3 -c 'import tempfile; print(tempfile.mkdtemp(prefix="alles-phase6-docs-"))')"
    test_run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    printf '%s\n' "$test_run_id" > "$test_root/.alles-test-owner"
    ALLES_DATA="$test_root" ALLES_TEST_DATA=1 ALLES_TEST_RUN_ID="$test_run_id" \
      PORT=8968 AUTH_ENABLED=false python3 app.py
    ALLES_DATA="$test_root" ALLES_TEST_DATA=1 ALLES_TEST_RUN_ID="$test_run_id" \
      PORT=8968 python3 tests/pw_phase6_docs.py
"""

import os
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8968")
DOCS = f"http://docs.localhost:{PORT}/"
FIXTURE = """---
title: Phase 6 proof
tags:
  - afterlife
---

# Phase 6 proof

Exact Markdown stays exact, including [[linked note]].

- [ ] preserve this task
"""
SAVED = FIXTURE + "\nEdited safely inside Alles.\n"
LOCAL_CONFLICT = SAVED + "\nKeep this local draft.\n"
EXTERNAL_CONFLICT = SAVED + "\nChanged outside Alles.\n"


def _require_throwaway_data_root() -> None:
    if os.environ.get("ALLES_TEST_DATA", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated Docs browser gate")
    raw = os.environ.get("ALLES_DATA", "").strip()
    if not raw:
        raise RuntimeError("set ALLES_DATA to this browser run's temporary data folder")
    data = Path(raw).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        relative = data.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if not relative.parts:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser run")
    try:
        owner = (data / ".alles-test-owner").read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(DOCS, run_id)


def _post(page, url: str, body: dict) -> dict:
    return page.evaluate(
        """async ([url, body]) => {
            const response = await fetch(url, {
                method: 'POST',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify(body),
            });
            return {status: response.status, body: await response.json()};
        }""",
        [url, body],
    )


def run() -> None:
    _require_throwaway_data_root()
    console_errors: list[str] = []
    native_dialogs: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            reduced_motion="reduce",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error" and "409 (Conflict)" not in message.text
                else None
            ),
        )
        page.on(
            "dialog",
            lambda dialog: (native_dialogs.append(dialog.message), dialog.dismiss()),
        )

        page.goto(DOCS, wait_until="domcontentloaded")
        page.wait_for_selector("#wiki-view:visible", timeout=15_000)
        page.wait_for_timeout(500)

        # The unified Docs workbench owns the full viewport. Its 52px identity
        # row replaces the legacy shared breadcrumb, while the mounted Docs
        # canvas fills the exact remaining slot. Empty Docs and Notes also must
        # not reserve the hidden document-details column.
        assert page.locator(".topbar").is_hidden()
        workbench = page.locator("#docs-workbench-view").bounding_box()
        identity = page.locator("#docs-workbench-view .specialist-app-brand").bounding_box()
        docs_view = page.locator("#wiki-view").bounding_box()
        docs_main = page.locator("#docs-reader-main").bounding_box()
        assert workbench and identity and docs_view and docs_main
        assert abs(workbench["y"]) <= 1
        assert abs(workbench["height"] - page.viewport_size["height"]) <= 1
        assert abs(docs_view["y"] - (identity["y"] + identity["height"])) <= 1
        assert abs(docs_view["height"] - (workbench["height"] - identity["height"])) <= 1
        assert (
            abs((docs_main["x"] + docs_main["width"]) - (docs_view["x"] + docs_view["width"])) <= 1
        )
        page.locator('#docs-sections [data-section="notes"]').click()
        page.wait_for_selector("#wiki-notes:visible")
        notes_main = page.locator("#docs-reader-main").bounding_box()
        assert notes_main
        assert (
            abs((notes_main["x"] + notes_main["width"]) - (docs_view["x"] + docs_view["width"]))
            <= 1
        )
        assert page.locator("#docs-context-panel").is_hidden()
        page.locator('#docs-sections [data-section="docs"]').click()
        page.wait_for_selector("#wiki-empty-state:visible")
        assert page.locator(".docs-reader-head").is_hidden()

        # An external Markdown write should appear without refreshing the page.
        # This is the same path used by Obsidian and other local editors.
        live_path = "live-refresh-proof.md"
        context.request.delete(f"{DOCS}api/vault-md/file?path={live_path}")
        started = page.evaluate("performance.now()")
        live_created = _post(
            page,
            "/api/vault-md/file",
            {"path": "live-refresh-proof", "content": "# live"},
        )
        assert live_created["status"] == 200, live_created
        page.wait_for_selector(f'#wiki-tree .wiki-file[data-file="{live_path}"]', timeout=1_500)
        elapsed = page.evaluate("performance.now()") - started
        assert elapsed < 1_500, elapsed

        recent_card = page.locator(f'#wiki-empty-recent .docs-home-card[data-file="{live_path}"]')
        assert recent_card.is_visible()
        # The watcher may have observed both the cleanup and create events. Settle
        # on the latest tree before proving identical refreshes keep hit targets.
        page.evaluate("window._reloadDocs()")
        stable_card = recent_card.element_handle()
        assert stable_card
        page.evaluate("window._reloadDocs()")
        page.wait_for_function(
            "node => node.isConnected",
            arg=stable_card,
            timeout=1_500,
        )
        recent_copy = recent_card.locator(".docs-home-card-copy")
        recent_icon = recent_card.locator(".docs-nav-icon")
        assert recent_copy.count() == 1
        card_box = recent_card.bounding_box()
        copy_box = recent_copy.bounding_box()
        icon_box = recent_icon.bounding_box()
        assert card_box and copy_box and icon_box
        assert copy_box["x"] < icon_box["x"], (copy_box, icon_box)
        assert abs(copy_box["x"] - (card_box["x"] + 12)) <= 1, (card_box, copy_box)
        assert (
            abs((icon_box["x"] + icon_box["width"]) - (card_box["x"] + card_box["width"] - 12)) <= 1
        ), (card_box, icon_box)
        page.screenshot(path="/tmp/alles-phase6-docs-home-card.png", full_page=True)

        # This gate is safe to rerun against the same throwaway server. Remove only
        # its own fixture so vault create does not choose a suffixed duplicate path.
        cleanup_status = context.request.delete(
            f"{DOCS}api/vault-md/file?path=phase-6-proof.md"
        ).status
        assert cleanup_status in {200, 404}, cleanup_status

        created = _post(
            page,
            "/api/vault-md/file",
            {"path": "phase-6-proof", "content": FIXTURE},
        )
        assert created["status"] == 200, created
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(
            '#wiki-tree .wiki-file[data-file="phase-6-proof.md"]', timeout=15_000
        )

        # The product opens as a quiet vault viewer with semantic, non-placeholder icons.
        assert page.locator("#wiki-empty-state").is_visible()
        assert page.locator("#wiki-editor").is_hidden()
        assert page.locator("#wiki-empty-obsidian").is_visible()
        assert page.locator(".docs-library-item svg path").count() >= 3

        # Sidebar icons lead their labels and ordinary labels are never squeezed
        # into the old 16px trailing column.
        library_item = page.locator('.docs-library-item[data-section="docs"]')
        library_icon = library_item.locator(".docs-nav-icon")
        library_label = library_item.locator("span")
        item_box = library_item.bounding_box()
        item_icon_box = library_icon.bounding_box()
        item_label_box = library_label.bounding_box()
        assert item_box and item_icon_box and item_label_box
        assert item_icon_box["x"] < item_label_box["x"], (item_icon_box, item_label_box)
        assert item_label_box["x"] + item_label_box["width"] <= item_box["x"] + item_box["width"]
        assert library_label.evaluate("el => el.scrollWidth <= el.clientWidth")

        # Library, recent, and vault can be hidden independently. The state is
        # persistent, but every heading remains available so the section can be restored.
        for group, panel_id in [
            ("library", "docs-sections"),
            ("recent", "docs-recent"),
            ("vault", "docs-vault-content"),
        ]:
            toggle = page.locator(f'[data-docs-collapse="{group}"]')
            assert toggle.get_attribute("aria-expanded") == "true"
            if group == "library":
                toggle.focus()
                page.keyboard.press("Enter")
            else:
                toggle.click()
            assert page.locator(f"#{panel_id}").is_hidden()
            assert toggle.get_attribute("aria-expanded") == "false"
            toggle.click()
            assert page.locator(f"#{panel_id}").is_visible()

        page.locator('#wiki-tree .wiki-file[data-file="phase-6-proof.md"]').click()
        page.wait_for_selector("#wiki-document:visible")
        preview_text = page.locator("#wiki-preview").inner_text()
        assert "Exact Markdown stays exact" in preview_text
        assert "title: Phase 6 proof" not in preview_text
        assert page.locator("#wiki-obsidian-btn").is_visible()
        assert page.locator("#wiki-preview").is_visible()
        assert page.locator("#wiki-editor").is_hidden()

        # Edit is opt-in and loads the bundled CodeMirror editor only when requested.
        page.locator("#wiki-edit-btn").click()
        page.wait_for_selector("#wiki-editor:visible .cm-editor", timeout=15_000)
        editor_bar = page.locator(".docs-editor-bar").bounding_box()
        mode_switch = page.locator(".docs-mode-switch").bounding_box()
        editor_actions = page.locator(".docs-editor-actions").bounding_box()
        assert editor_bar and mode_switch and editor_actions
        mode_center = mode_switch["y"] + mode_switch["height"] / 2
        actions_center = editor_actions["y"] + editor_actions["height"] / 2
        assert abs(mode_center - actions_center) <= 1, (mode_switch, editor_actions)
        assert (
            editor_actions["x"] + editor_actions["width"] <= editor_bar["x"] + editor_bar["width"]
        )
        done_padding = page.locator("#wiki-done-btn").evaluate(
            """element => {
                const style = getComputedStyle(element);
                return [parseFloat(style.paddingLeft), parseFloat(style.paddingRight)];
            }"""
        )
        assert min(done_padding) >= 10, done_padding

        # Frontmatter used to be interpreted as a horizontal rule. Moving the
        # selection then reflowed the document after pointer mapping and placed
        # the caret one or two lines away from the click.
        editor_lines = page.locator(".cm-line")
        for line_index in range(editor_lines.count()):
            target_line = editor_lines.nth(line_index)
            if not target_line.inner_text().strip():
                continue
            line_before = target_line.bounding_box()
            assert line_before
            target_x = line_before["x"] + min(100, max(8, line_before["width"] - 8))
            target_y = line_before["y"] + line_before["height"] / 2
            page.mouse.click(target_x, target_y)
            page.wait_for_timeout(50)
            line_after = target_line.bounding_box()
            cursor = page.locator(".cm-cursor-primary").bounding_box()
            assert line_after and cursor
            assert abs(line_after["y"] - line_before["y"]) <= 1, (
                line_index,
                line_before,
                line_after,
            )
            cursor_center = cursor["y"] + cursor["height"] / 2
            assert abs(cursor_center - target_y) <= 2, (line_index, target_y, cursor)
        page.screenshot(path="/tmp/alles-phase6-docs-editor.png", full_page=True)
        page.locator("#wiki-source-btn").click()
        source = page.locator("#wiki-source")
        assert source.input_value() == FIXTURE
        source.fill(SAVED)
        page.wait_for_function(
            "document.getElementById('wiki-save-state')?.textContent.includes('local draft')"
        )
        page.locator("#wiki-save-btn").click()
        page.wait_for_function(
            "document.getElementById('wiki-save-state')?.textContent === 'saved'"
        )
        disk = page.evaluate(
            "fetch('/api/vault-md/file?path=phase-6-proof.md').then(r => r.json())"
        )
        assert disk["content"] == SAVED

        # A stale save fails closed and the local draft remains visible and recoverable.
        source.fill(LOCAL_CONFLICT)
        external = _post(
            page,
            "/api/vault-md/safety/save",
            {
                "path": "phase-6-proof.md",
                "content": EXTERNAL_CONFLICT,
                "expected_hash": disk["hash"],
            },
        )
        assert external["status"] == 200, external
        page.locator("#wiki-save-btn").click()
        page.wait_for_function(
            "document.getElementById('wiki-inline-message')?.textContent.includes('changed in Obsidian')"
        )
        assert source.input_value() == LOCAL_CONFLICT
        assert "conflict" in page.locator("#wiki-save-state").inner_text()
        page.get_by_role("button", name="compare copies").click()
        page.wait_for_selector("#docs-dialog:not([hidden])")
        assert "local draft" in page.locator("#docs-dialog-body").inner_text()
        page.get_by_role("button", name="keep my draft").click()

        # Keeping the draft intentionally leaves the conflict unresolved, so
        # navigation must stay blocked. Resolve the reviewed copies before the
        # Aide handoff and prove the visible draft is the saved revision.
        page.get_by_role("button", name="compare copies").click()
        page.wait_for_selector("#docs-dialog:not([hidden])")
        page.get_by_role("button", name="replace file with my draft").click()
        page.wait_for_function(
            "document.getElementById('wiki-save-state')?.textContent.startsWith('saved')"
        )

        # The selected document is carried visibly into Aide for one scoped question.
        page.locator("#wiki-ask-btn").click()
        page.locator("#wiki-ask-input").fill("what is the main point?")
        page.locator("#wiki-ask-go").click()
        page.wait_for_url(f"http://aide.localhost:{PORT}/**", timeout=15_000)
        page.wait_for_function(
            """() => Boolean(
                window._pendingDocumentScope
                || document.querySelector('.user-context-scope')
            )""",
            timeout=15_000,
        )
        scope_debug = page.evaluate("""() => ({
            navigation: performance.getEntriesByType('navigation')[0]?.name,
            pending: window._pendingDocumentScope || null,
            chipHidden: document.getElementById('aide-document-scope')?.hidden,
            chipName: document.getElementById('aide-document-scope-name')?.textContent,
            userScopes: [...document.querySelectorAll('.user-context-scope')].map(el => el.textContent),
        })""")
        assert scope_debug["pending"] or scope_debug["userScopes"], scope_debug
        if scope_debug["pending"]:
            assert scope_debug["pending"]["path"] == "phase-6-proof.md", scope_debug
            assert scope_debug["chipName"] == "phase-6-proof", scope_debug
        else:
            assert "phase-6-proof.md" in scope_debug["userScopes"][-1], scope_debug
            assert scope_debug["chipHidden"], scope_debug

        # Journal stays inside Docs and keeps the previously useful journal surfaces.
        journal_seed = page.evaluate("""async () => {
            const response = await fetch('/api/journal/2026-07-01', {
                method: 'PUT',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify({content: 'exact journal body', mood: '🙂', tags: 'proof'}),
            });
            return response.status;
        }""")
        assert journal_seed == 200
        page.goto(DOCS, wait_until="domcontentloaded")
        page.wait_for_selector("#wiki-view:visible", timeout=15_000)
        page.evaluate(
            "document.getElementById('docs-nav-panel').dataset.identityProof = 'same-shell'"
        )
        page.locator('#docs-tabs [data-group-section="journal"]').click()
        page.wait_for_selector("#docs-journal-section:visible", timeout=15_000)
        page.wait_for_selector("#jrnl-heatmap", timeout=15_000)
        assert page.locator("#wiki-view").is_visible()
        assert page.locator("#docs-reader-main").is_hidden()
        assert page.locator("#docs-nav-panel").get_attribute("data-identity-proof") == "same-shell"
        journal_workbench = page.locator("#docs-workbench-view").bounding_box()
        journal_identity = page.locator(
            "#docs-workbench-view .specialist-app-brand"
        ).bounding_box()
        journal_view = page.locator("#wiki-view").bounding_box()
        assert journal_workbench and journal_identity and journal_view
        assert abs(journal_workbench["y"]) <= 1
        assert abs(journal_workbench["height"] - page.viewport_size["height"]) <= 1
        assert (
            abs(journal_view["y"] - (journal_identity["y"] + journal_identity["height"]))
            <= 1
        )
        assert (
            abs(
                journal_view["height"]
                - (journal_workbench["height"] - journal_identity["height"])
            )
            <= 1
        )
        assert page.locator(".topbar").is_hidden()
        for selector in (
            "#jrnl-search",
            "#jrnl-heatmap",
            "#jrnl-moods",
            "#jrnl-moodcorr",
            "#jrnl-topics",
            "#jrnl-otd",
            "#jrnl-recent",
            "#journal-migrate",
        ):
            assert page.locator(selector).count() == 1, selector

        # The explicit copy flow prepares privately, applies, and rolls back without
        # removing or changing the original Journal entry.
        page.locator("#journal-migrate").click()
        page.wait_for_selector(".jrnl-migration-layer")
        confirmation = page.locator(".jrnl-migration-confirm code").inner_text()
        page.locator(".jrnl-migration-confirm input").fill(confirmation)
        page.locator("[data-prepare]").click()
        page.wait_for_function(
            "document.querySelector('.jrnl-migration-status')?.textContent.includes('prepared privately')"
        )
        staged_file = page.evaluate(
            "fetch('/api/vault-md/file?path=Journal%2F2026-07-01.md').then(r => r.json())"
        )
        assert not staged_file["exists"]
        page.locator("[data-apply]").click()
        page.wait_for_function(
            "document.querySelector('.jrnl-migration-status')?.textContent.includes('copied')"
        )
        copied_file = page.evaluate(
            "fetch('/api/vault-md/file?path=Journal%2F2026-07-01.md').then(r => r.json())"
        )
        assert copied_file["exists"] and "exact journal body" in copied_file["content"]
        journal_source = page.evaluate("fetch('/api/journal/2026-07-01').then(r => r.json())")
        assert journal_source["content"] == "exact journal body"
        page.locator("[data-rollback]").click()
        page.wait_for_function(
            "document.querySelector('.jrnl-migration-status')?.textContent.includes('rolled back')"
        )
        rolled_back_file = page.evaluate(
            "fetch('/api/vault-md/file?path=Journal%2F2026-07-01.md').then(r => r.json())"
        )
        assert not rolled_back_file["exists"]
        page.locator(".jrnl-migration-actions [data-close]").click()
        page.screenshot(path="/tmp/alles-phase6-journal-desktop.png", full_page=True)

        # Desktop and mobile must not spill horizontally or squash the reader.
        page.goto(DOCS, wait_until="domcontentloaded")
        page.wait_for_selector("#wiki-view:visible", timeout=15_000)
        page.locator('#wiki-tree .wiki-file[data-file="phase-6-proof.md"]').click()
        page.wait_for_selector("#wiki-document:visible")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        reader = page.locator("#docs-reader-main").bounding_box()
        assert reader and reader["width"] >= 650, reader
        page.screenshot(path="/tmp/alles-phase6-docs-desktop.png", full_page=True)

        page.evaluate("""() => {
            const root = document.documentElement;
            root.dataset.theme = 'light';
            root.style.setProperty('--bg', '#f5f4f1');
            root.style.setProperty('--text', '#111111');
            root.style.setProperty('--panel', '#efede9');
            root.style.setProperty('--faint', '#d4d2ce');
            root.style.setProperty('--muted', '#767676');
        }""")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path="/tmp/alles-phase6-docs-light.png", full_page=True)
        page.evaluate("""() => {
            const root = document.documentElement;
            delete root.dataset.theme;
            for (const token of ['--bg', '--text', '--panel', '--faint', '--muted']) {
                root.style.removeProperty(token);
            }
        }""")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert page.locator("#wiki-tree-toggle").is_visible()
        page.screenshot(path="/tmp/alles-phase6-docs-mobile.png", full_page=True)

        context.close()
        browser.close()

    assert not native_dialogs, f"native dialogs used: {native_dialogs}"
    assert not console_errors, "browser console errors:\n" + "\n".join(console_errors)
    print("phase 6 Docs browser gate passed")


if __name__ == "__main__":
    run()
