"""Real Phase 7 Files browser gate using only throwaway storage roots."""

from __future__ import annotations

import base64
import os
import shutil
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Browser, Page, sync_playwright

PORT = os.environ.get("PORT", "8971")
DATA = Path(os.environ["ALLES_DATA"]).resolve()
BASE = f"http://files.localhost:{PORT}/"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _require_throwaway_data_root() -> None:
    sentinel = os.environ.get("ALLES_TEST_DATA", "").strip().lower()
    if sentinel not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated Phase 7 browser gate")
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        relative = DATA.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError("ALLES_DATA must be inside the system temporary directory") from exc
    if not relative.parts:
        raise RuntimeError("ALLES_DATA cannot be the system temporary directory itself")
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "").strip()
    if len(run_id) < 16:
        raise RuntimeError("set a unique ALLES_TEST_RUN_ID for this browser run")
    owner_file = DATA / ".alles-test-owner"
    try:
        owner = owner_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(BASE, run_id)


def _errors(page: Page, errors: list[str], label: str) -> None:
    page.on("pageerror", lambda error: errors.append(f"{label} page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"{label} console: {message.text}") if message.type == "error" else None
        ),
    )


def _no_overflow(page: Page) -> None:
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _open(page: Page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("#files-view:visible", timeout=15_000)
    page.wait_for_selector("#files-list .file-row", timeout=15_000)


def _add_location(page: Page, name: str, path: Path, managed: bool) -> None:
    page.locator("#files-add-location").click()
    page.locator("#files-location-name").fill(name)
    page.locator("#files-location-root").fill(str(path))
    if managed:
        page.locator('#files-location-access [data-value="managed"]').click()
    page.locator("#files-location-form").locator('button[type="submit"]').click()
    page.wait_for_function("document.querySelector('#files-location-dialog')?.hidden")
    page.wait_for_selector(f'#files-location-list .files-location-button:has-text("{name}")')


def _desktop(browser: Browser, errors: list[str], second: Path, read_only: Path) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 920},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(12_000)
    page.route(
        "https://fonts.googleapis.com/**",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    _errors(page, errors, "desktop")
    _open(page)

    assert page.locator(".main > .topbar").evaluate(
        "element => getComputedStyle(element).display === 'none'"
    )
    assert page.locator("#files-app-header").is_visible()
    assert page.locator(".files-phase7-wordmark").inner_text() == "files"
    assert "on this server" in page.locator("#files-breadcrumb").inner_text()
    assert page.locator("#files-app-status").inner_text() == "local · managed"
    page.locator("#files-settings-btn").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#settings-modal:visible")
    page.locator("#settings-modal-close").click()
    assert page.evaluate("document.activeElement?.id") == "files-settings-btn"
    workbench_home = page.locator("#files-workbench-view [data-specialist-home]")
    assert workbench_home.is_visible()
    workbench_home.click()
    page.wait_for_url(f"http://localhost:{PORT}/", timeout=12_000)
    assert page.locator("#files-view").is_hidden()
    _open(page)

    assert page.locator("#files-view select").count() == 0
    assert (
        page.locator('#files-view input[type="checkbox"], #files-view input[type="radio"]').count()
        == 0
    )
    assert page.locator("#files-location-list .files-location-button").count() == 1
    assert page.locator("#files-list .file-row").count() >= 3
    header_box = page.locator(".files-phase7-table-head").bounding_box()
    first_row_box = page.locator("#files-list .file-row").first.bounding_box()
    assert header_box and first_row_box
    assert abs(header_box["x"] - first_row_box["x"]) < 1
    assert abs(header_box["width"] - first_row_box["width"]) < 1
    _no_overflow(page)

    # A reload between enqueue and run must leave an obvious, working way to
    # resume the durable operation instead of stranding it forever.
    queued = page.request.post(
        f"{BASE}api/files/operations",
        data={
            "action": "copy",
            "source_location_id": "default-local",
            "source_path": "alpha.txt",
            "destination_location_id": "default-local",
            "destination_path": "queued-start.txt",
            "run_now": False,
        },
    )
    assert queued.ok, queued.text()
    queued_id = queued.json()["id"]
    page.reload(wait_until="domcontentloaded")
    start = page.locator(
        f'#files-operation-list [data-operation-id="{queued_id}"] [data-operation-action="run"]'
    )
    start.wait_for()
    start.click()
    page.wait_for_selector('#files-list .file-row[data-path="queued-start.txt"]')

    # Rows are directly operable from the keyboard without double-triggering
    # their nested buttons.
    alpha_row = page.locator('#files-list .file-row[data-path="alpha.txt"]')
    assert alpha_row.get_attribute("tabindex") == "0"
    alpha_row.focus()
    page.keyboard.press("Space")
    assert alpha_row.locator("[data-file-select]").get_attribute("aria-checked") == "true"
    page.keyboard.press("Space")
    assert alpha_row.locator("[data-file-select]").get_attribute("aria-checked") == "false"
    page.keyboard.press("Enter")
    assert page.locator("#files-detail-panel").is_visible()
    assert page.locator('[data-detail-action="photos"]').count() == 0
    assert page.evaluate("document.activeElement?.id") == "files-detail-close"
    page.keyboard.press("Enter")
    assert page.locator("#files-detail-panel").is_hidden()
    assert page.evaluate("document.activeElement?.dataset?.path") == "alpha.txt"

    # Searching inside Starred must never leak ordinary location-wide results
    # beneath the still-active Starred view.
    alpha_row.focus()
    page.keyboard.press("Enter")
    page.locator('[data-detail-action="star"]').click()
    page.wait_for_function(
        "document.querySelector('[data-detail-action=\"star\"]')?.textContent === 'unstar'"
    )
    page.locator("#files-detail-close").click()
    page.locator('[data-files-view="starred"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]')
    page.locator("#files-search").fill("budget")
    page.wait_for_function(
        "document.querySelector('#files-partial-note')?.textContent === '0 starred results'"
    )
    assert page.locator("#files-list .file-row").count() == 0
    page.locator("#files-search").fill("alpha")
    page.wait_for_function(
        "document.querySelector('#files-partial-note')?.textContent === '1 starred result'"
    )
    assert page.locator('#files-list .file-row[data-path="alpha.txt"]').count() == 1
    page.locator('[data-files-view="all"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]')

    # The shared prompt is a labelled custom dialog, closes with Escape, and
    # restores focus to the control that opened it.
    page.locator("#files-mkdir-btn").click()
    prompt = page.locator('.dialog-overlay [role="dialog"]')
    assert prompt.is_visible()
    assert prompt.get_attribute("aria-modal") == "true"
    page.keyboard.press("Escape")
    page.wait_for_selector(".dialog-overlay", state="detached")
    assert page.evaluate("document.activeElement?.id") == "files-mkdir-btn"

    # Create, upload, search, rename, send media to Photos, delete, and restore
    # all run through the real Files controls.
    page.locator("#files-mkdir-btn").click()
    page.locator(".dialog-overlay input").fill("phase-seven-folder")
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_selector('#files-list .file-row[data-path="phase-seven-folder"]')
    page.locator("#files-upload-input").set_input_files(
        files=[{"name": "tiny.png", "mimeType": "image/png", "buffer": PNG}]
    )
    page.wait_for_selector('#files-list .file-row[data-path="tiny.png"]')
    page.locator("#files-search").fill("budget")
    page.wait_for_function(
        "document.querySelector('#files-partial-note')?.textContent === '1 result'"
    )
    assert page.locator('#files-list .file-row[data-path="budget.md"]').count() == 1
    assert page.locator("#files-list .file-row").count() == 1
    page.locator("#files-search").fill("")
    page.wait_for_selector('#files-list .file-row[data-path="tiny.png"]')
    assert page.locator("#files-partial-note").is_hidden()

    tiny_row = page.locator('#files-list .file-row[data-path="tiny.png"]')
    tiny_row.focus()
    page.keyboard.press("Enter")
    assert page.locator('[data-detail-action="photos"]').is_visible()
    assert page.locator('[data-detail-action="open"]').is_visible()
    assert page.locator("#files-detail-content a[download]").is_visible()
    page.locator('[data-detail-action="open"]').click()
    assert page.locator("#files-preview-modal").is_visible()
    assert page.locator("#files-preview-modal").get_attribute("role") == "dialog"
    assert page.locator("#files-preview-modal").get_attribute("aria-modal") == "true"
    assert page.evaluate("document.activeElement?.id") == "files-preview-close"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement?.id") == "files-preview-dl"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement?.id") == "files-preview-close"
    page.locator("#files-preview-close").click()
    assert page.evaluate("document.activeElement?.dataset?.detailAction") == "open"
    page.locator('[data-detail-action="star"]').click()
    page.wait_for_function(
        "document.querySelector('[data-detail-action=\"star\"]')?.textContent === 'unstar'"
    )
    page.locator('[data-detail-action="photos"]').click()
    page.wait_for_function(
        "document.querySelector('#toast-container')?.textContent.includes('Photos')"
    )
    page.locator('[data-detail-action="rename"]').click()
    page.locator(".dialog-overlay input").fill("renamed.png")
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_selector('#files-list .file-row[data-path="renamed.png"]', timeout=15_000)

    renamed_row = page.locator('#files-list .file-row[data-path="renamed.png"]')
    renamed_row.focus()
    page.keyboard.press("Enter")
    page.locator('[data-detail-action="delete"]').click()
    assert page.locator('.dialog-overlay [role="alertdialog"]').is_visible()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_function(
        "!document.querySelector('#files-list .file-row[data-path=\"renamed.png\"]')",
        timeout=15_000,
    )
    page.locator('[data-files-view="trash"]').click()
    assert page.locator("#files-mkdir-btn").is_hidden()
    assert page.locator("#files-mkdir-btn").is_disabled()
    assert page.locator("#files-upload-btn").is_hidden()
    assert page.locator("#files-upload-btn").is_disabled()
    trashed_row = (
        page.locator("#files-list .file-row[data-trash-id]").filter(has_text="renamed.png").first
    )
    trashed_row.wait_for(timeout=15_000)
    trash_id = trashed_row.get_attribute("data-trash-id")
    assert trash_id
    trashed_row.focus()
    page.keyboard.press("Enter")
    page.locator('[data-detail-action="restore"]').click()
    page.wait_for_selector(
        f'#files-list .file-row[data-trash-id="{trash_id}"]',
        state="detached",
        timeout=15_000,
    )
    page.locator('[data-files-view="all"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="renamed.png"]', timeout=15_000)

    page.locator("#files-select-all").click()
    assert page.locator("#files-selection-bar").is_visible()
    assert page.locator("#files-selection-count").inner_text().endswith(" selected")
    page.locator('[data-files-bulk="clear"]').click()
    assert page.locator("#files-selection-bar").is_hidden()

    page.locator('[data-location-action="index"]').click()
    page.wait_for_function(
        "document.querySelector('.files-location-index-state')?.textContent.includes('files indexed')",
        timeout=30_000,
    )

    # The add-location dialog is custom, keyboard operable, and exposes every backend kind.
    page.locator("#files-add-location").click()
    assert page.locator("#files-location-dialog").get_attribute("aria-modal") == "true"
    close_button = page.locator('[data-files-dialog-close="location"]').first
    close_button.focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement?.textContent?.trim()") == "add location"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement?.getAttribute('aria-label')") == "close"
    page.locator('#files-location-kind [data-value="local"]').focus()
    page.keyboard.press("ArrowRight")
    assert (
        page.locator('#files-location-kind [data-value="webdav"]').get_attribute("aria-checked")
        == "true"
    )
    assert page.locator("#files-location-username").is_visible()
    page.keyboard.press("ArrowRight")
    assert (
        page.locator('#files-location-kind [data-value="s3"]').get_attribute("aria-checked")
        == "true"
    )
    assert page.locator("#files-location-bucket").is_visible()
    close_button.click()
    assert page.evaluate("document.activeElement?.id") == "files-add-location"

    _add_location(page, "work archive", second, True)
    _add_location(page, "reference", read_only, False)
    assert page.locator("#files-location-list .files-location-button").count() == 3

    # The read-only location states why changes are unavailable.
    page.locator('.files-location-button:has-text("reference")').click()
    assert page.locator("#files-mkdir-btn").is_disabled()
    assert page.locator("#files-upload-btn").is_disabled()

    # Location health, access changes, and safe removal are all live controls.
    page.locator('[data-location-action="test"]').click()
    page.wait_for_function(
        "document.querySelector('#files-location-status')?.textContent.includes('ready')"
    )
    page.locator('[data-location-action="access"]').click()
    page.wait_for_function("!document.querySelector('#files-mkdir-btn').disabled")
    page.locator('[data-location-action="access"]').click()
    page.wait_for_function("document.querySelector('#files-mkdir-btn').disabled")
    page.locator('[data-location-action="remove"]').click()
    assert page.locator('.dialog-overlay [role="alertdialog"]').is_visible()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_function(
        "document.querySelectorAll('#files-location-list .files-location-button').length === 2"
    )

    # Copy a real file through the durable operation queue.
    page.locator("#files-location-list .files-location-button").first.click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]')
    page.locator('#files-list .file-row[data-path="alpha.txt"] [data-file-select]').click()
    assert page.locator("#files-selection-bar").is_visible()
    assert page.locator("#files-selection-count").inner_text() == "1 selected"
    page.locator('[data-files-bulk="copy"]').click()
    page.locator('#files-transfer-locations [role="radio"]:has-text("work archive")').click()
    page.locator("#files-transfer-form").locator('button[type="submit"]').click()
    page.wait_for_selector(
        '#files-operation-list [data-operation-action="undo"]',
        timeout=15_000,
    )
    page.locator('.files-location-button:has-text("work archive")').click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]')

    # Cached folders remain fully browsable after their live source disappears.
    page.locator('#files-list .file-row[data-path="offline-folder"] .file-main svg').click()
    page.locator('[data-detail-action="offline"]').click()
    page.wait_for_function(
        "document.querySelector('#files-detail-content')?.textContent.includes('remove offline copy')"
    )
    page.locator("#files-detail-close").click()
    shutil.rmtree(second / "offline-folder")
    forbidden_live_requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            forbidden_live_requests.append(request.url)
            if any(
                endpoint in request.url
                for endpoint in (
                    "/api/files/list",
                    "/api/files/search",
                    "/api/files/read",
                    "/api/files/raw",
                )
            )
            else None
        ),
    )
    page.locator('[data-files-view="offline"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="offline-folder"]')
    assert page.locator("#files-mkdir-btn").is_hidden()
    assert page.locator("#files-upload-btn").is_hidden()
    page.locator('#files-list .file-row[data-path="offline-folder"] [data-file-open]').click()
    page.wait_for_selector('#files-list .file-row[data-path="offline-folder/notes"]')
    page.locator('#files-list .file-row[data-path="offline-folder/notes"] [data-file-open]').click()
    page.wait_for_selector('#files-list .file-row[data-path="offline-folder/notes/readme.txt"]')
    page.locator("#files-search").fill("readme")
    page.wait_for_function(
        "document.querySelector('#files-partial-note')?.textContent === '1 cached result'"
    )
    assert page.locator("#files-list .file-row").count() == 1
    page.locator(
        '#files-list .file-row[data-path="offline-folder/notes/readme.txt"] [data-file-open]'
    ).click()
    page.wait_for_selector("#files-detail-panel:not([hidden])")
    page.locator('[data-detail-action="open"]').click()
    page.wait_for_selector("#files-preview-modal:visible")
    page.locator("#files-preview-body").get_by_text("cached browser proof").wait_for()
    page.locator("#files-preview-close").click()
    assert forbidden_live_requests == []
    page.locator('[data-files-view="all"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]')

    # A queued copy has an undo action, and the UI refreshes from durable state.
    page.locator("#files-operation-dock").get_by_text("undo").first.click()
    page.wait_for_function(
        "!document.querySelector('#files-list .file-row[data-path=\"alpha.txt\"]')",
        timeout=15_000,
    )
    page.wait_for_selector("#files-list .files-empty", timeout=15_000)
    assert page.locator("#files-detail-panel").is_hidden()
    assert page.locator("#toast-container .toast").count() <= 3
    assert page.evaluate(
        """() => {
          const dock = document.querySelector('#files-operation-dock');
          const toasts = [...document.querySelectorAll('#toast-container .toast')];
          if (!dock || dock.hidden) return true;
          const a = dock.getBoundingClientRect();
          return toasts.every(toast => {
            const b = toast.getBoundingClientRect();
            return b.right <= a.left || b.left >= a.right || b.bottom <= a.top || b.top >= a.bottom;
          });
        }"""
    )

    # Read-only locations cannot expose or run Restore, even for an item that
    # entered trash while the same location was managed.
    page.locator("#files-upload-input").set_input_files(
        files=[{"name": "restore-check.txt", "mimeType": "text/plain", "buffer": b"restore"}]
    )
    restore_row = page.locator('#files-list .file-row[data-path="restore-check.txt"]')
    restore_row.wait_for()
    restore_row.focus()
    page.keyboard.press("Enter")
    page.locator('[data-detail-action="delete"]').click()
    page.locator(".dialog-overlay [data-dialog-confirm]").click()
    page.wait_for_selector('#files-list .file-row[data-path="restore-check.txt"]', state="detached")
    location_id = page.locator('.files-location-button:has-text("work archive")').get_attribute(
        "data-location-id"
    )
    assert location_id
    response = page.request.patch(
        f"{BASE}api/storage-locations/{location_id}", data={"access": "read_only"}
    )
    assert response.ok, response.text()
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#files-view:visible")
    page.locator('[data-files-view="trash"]').click()
    restore_trash_row = page.locator("#files-list .file-row[data-trash-id]").filter(
        has_text="restore-check.txt"
    )
    restore_trash_row.wait_for()
    restore_trash_row.focus()
    page.keyboard.press("Enter")
    assert page.locator('[data-detail-action="restore"]').count() == 0
    assert page.locator("#files-detail-content").get_by_text("read only", exact=True).is_visible()
    response = page.request.patch(
        f"{BASE}api/storage-locations/{location_id}", data={"access": "managed"}
    )
    assert response.ok, response.text()
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#files-view:visible")
    page.locator('[data-files-view="trash"]').click()
    restore_trash_row = page.locator("#files-list .file-row[data-trash-id]").filter(
        has_text="restore-check.txt"
    )
    restore_trash_row.wait_for()
    restore_trash_row.focus()
    page.keyboard.press("Enter")
    page.locator('[data-detail-action="restore"]').click()
    page.wait_for_selector(
        '#files-list .file-row:has-text("restore-check.txt")', state="detached", timeout=15_000
    )
    page.locator('[data-files-view="all"]').click()
    page.wait_for_selector('#files-list .file-row[data-path="restore-check.txt"]')

    page.screenshot(path="/tmp/alles-phase7-files-real-desktop.png", full_page=True)
    # Exercise the real appearance engine. Flipping only data-theme leaves the
    # engine's inline color tokens in place and can produce a false dark-theme
    # screenshot even though the user-facing theme control works correctly.
    page.evaluate(
        "() => import('/static/js/theme.js').then(({ resetToDefault }) => resetToDefault('light'))"
    )
    page.wait_for_timeout(100)
    colors = page.locator("#files-view").evaluate(
        "element => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor })"
    )
    assert colors["color"] != colors["background"]
    assert page.locator("#files-view").evaluate(
        "element => getComputedStyle(element).backgroundColor.match(/\\d+/g).slice(0, 3).every(value => Number(value) > 200)"
    )
    page.screenshot(path="/tmp/alles-phase7-files-real-light.png", full_page=True)
    _no_overflow(page)

    # A 720 CSS-pixel viewport represents 200% browser zoom on the 1440px
    # desktop frame. Text resizing is checked separately so neither path can
    # hide the location rail or the primary Files actions.
    page.set_viewport_size({"width": 720, "height": 920})
    _no_overflow(page)
    assert page.locator("#files-add-location").is_visible()
    assert page.locator("#files-upload-btn").is_visible()
    page.evaluate("document.documentElement.style.fontSize = '200%'")
    _no_overflow(page)
    assert page.locator("#files-add-location").is_visible()
    assert page.locator("#files-upload-btn").is_visible()
    context.close()


def _recovery(browser: Browser, errors: list[str]) -> None:
    context = browser.new_context(
        viewport={"width": 1100, "height": 760},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(12_000)
    page.on("pageerror", lambda error: errors.append(f"recovery page: {error}"))
    page.on(
        "console",
        lambda message: (
            errors.append(f"recovery console: {message.text}")
            if message.type == "error" and "503 (Service Unavailable)" not in message.text
            else None
        ),
    )
    failures = {"remaining": 1}

    def fail_once(route):
        if failures["remaining"]:
            failures["remaining"] -= 1
            route.fulfill(
                status=503,
                content_type="application/json",
                body='{"detail":"location temporarily unavailable"}',
            )
        else:
            route.continue_()

    page.route("**/api/files/list*", fail_once)
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("#files-list [data-files-retry]", timeout=15_000)
    assert page.locator("#files-list").get_by_text("location temporarily unavailable").is_visible()
    page.locator("#files-list [data-files-retry]").click()
    page.wait_for_selector('#files-list .file-row[data-path="alpha.txt"]', timeout=15_000)
    assert page.locator("#files-list [data-files-retry]").count() == 0
    context.close()


def _mobile(browser: Browser, errors: list[str]) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        reduced_motion="reduce",
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(12_000)
    page.route(
        "https://fonts.googleapis.com/**",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    _errors(page, errors, "mobile")
    _open(page)
    _no_overflow(page)
    assert page.locator(".main > .topbar").evaluate(
        "element => getComputedStyle(element).display === 'none'"
    )
    assert page.locator("#files-app-header").is_visible()
    assert page.locator(".files-phase7-wordmark").inner_text() == "files"
    assert "on this server" in page.locator("#files-breadcrumb").inner_text()
    assert page.locator("#files-app-status").inner_text() == "local · managed"
    header_box = page.locator("#files-app-header").bounding_box()
    home_selector = "#files-workbench-view [data-specialist-home]"
    home_box = page.locator(home_selector).bounding_box()
    sidebar_box = page.locator(
        "#files-workbench-view [data-specialist-sidebar-toggle]"
    ).bounding_box()
    settings_box = page.locator("#files-settings-btn").bounding_box()
    up_box = page.locator("#files-up-btn").bounding_box()
    assert header_box and header_box["height"] <= 100
    assert home_box and sidebar_box and abs(home_box["y"] - sidebar_box["y"]) < 1
    assert settings_box and up_box and abs(settings_box["y"] - up_box["y"]) < 1
    for selector in (home_selector, "#files-settings-btn", "#files-up-btn"):
        box = page.locator(selector).bounding_box()
        assert box and box["height"] >= 44
    assert page.locator("#files-add-location").is_visible()
    assert page.locator(".files-phase7-location-panel").evaluate(
        "element => getComputedStyle(element).overflowX === 'auto'"
    )
    assert page.locator("#files-location-list").evaluate(
        "element => getComputedStyle(element).flexDirection === 'row'"
    )
    check = page.locator("#files-list .file-row [data-file-select]").first
    check_box = check.bounding_box()
    assert check_box and check_box["width"] >= 44 and check_box["height"] >= 44
    check.focus()
    page.keyboard.press("Space")
    assert check.get_attribute("aria-checked") == "true"
    assert page.locator("#files-selection-bar").is_visible()
    assert page.locator(".files-phase7-selection-actions").is_visible()
    page.locator('#files-list .file-row[data-path="alpha.txt"] [data-file-open]').click()
    assert page.locator("#files-detail-panel").is_visible()
    page.locator("#files-detail-close").click()
    assert page.locator("#files-detail-panel").is_hidden()
    page.screenshot(path="/tmp/alles-phase7-files-real-mobile.png", full_page=True)
    context.close()


def run() -> None:
    _require_throwaway_data_root()
    files = DATA / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / "alpha.txt").write_text("alpha phase seven", encoding="utf-8")
    (files / "budget.md").write_text("# budget\n", encoding="utf-8")
    (files / "photos").mkdir(exist_ok=True)
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="alles-phase7-browser-locations-") as owned:
        owned_root = Path(owned).resolve()
        second = owned_root / "second-location"
        read_only = owned_root / "read-only-location"
        second.mkdir()
        read_only.mkdir()
        cached = second / "offline-folder" / "notes"
        cached.mkdir(parents=True)
        (cached / "readme.txt").write_text("cached browser proof", encoding="utf-8")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            _desktop(browser, errors, second, read_only)
            _recovery(browser, errors)
            _mobile(browser, errors)
            browser.close()
    if errors:
        raise AssertionError("browser errors:\n" + "\n".join(errors))
    print("real Phase 7 Files browser gate passed")


if __name__ == "__main__":
    run()
