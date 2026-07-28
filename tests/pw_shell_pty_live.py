"""Live browser gate for the vendored xterm renderer and scoped PTY."""

import os
import tempfile
from pathlib import Path

try:
    from browser_gate_safety import require_server_ownership
except ModuleNotFoundError:
    from tests.browser_gate_safety import require_server_ownership

PORT = os.environ.get("PORT", "8942")
URL = f"http://aide.localhost:{PORT}/"


def _require_throwaway_data_root() -> Path:
    sentinel = os.environ.get("ALLES_TEST_DATA", "").strip().lower()
    if sentinel not in {"1", "true", "yes"}:
        raise RuntimeError("set ALLES_TEST_DATA=1 for the isolated PTY browser gate")
    raw_data = os.environ.get("ALLES_DATA", "").strip()
    if not raw_data:
        raise RuntimeError("set ALLES_DATA to the isolated PTY browser data root")
    data = Path(raw_data).resolve()
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
        owner = (data / ".alles-test-owner").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("ALLES_DATA is missing its browser-test ownership sentinel") from exc
    if owner != run_id:
        raise RuntimeError("ALLES_DATA ownership sentinel does not match this browser run")
    require_server_ownership(URL, run_id)
    return data


def run_case(browser, width: int, height: int, label: str) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        service_workers="block",
    )
    page = context.new_page()
    page.set_default_timeout(8_000)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.goto(URL, wait_until="networkidle")
    print(f"{label}: page ready", flush=True)
    if label == "desktop":
        page.evaluate(
            """async () => {
              const sessions = await import('/static/js/sessions.js');
              sessions.newChat();
              window._pendingProjectId = '';
              window._pendingWorkingDir = '/tmp';
              window._syncAideNewTaskContext?.(null);
            }"""
        )
        session_id = ""
    else:
        session_id = page.evaluate(
            """async () => {
          const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({working_dir: '/tmp'}),
          });
          const session = await response.json();
          const sessions = await import('/static/js/sessions.js');
          await sessions.selectSession(session.id);
          return session.id;
        }"""
        )
        assert session_id
        print(f"{label}: session {session_id}", flush=True)
    if width < 700 and not page.locator("body").evaluate(
        "el => el.classList.contains('sidebar-hidden')"
    ):
        page.mouse.click(width - 10, height // 2)
        page.wait_for_selector("body.sidebar-hidden")
    page.locator("#aide-work-panel-toggle").click()
    page.locator('[data-aide-tool="terminal"]').click()
    page.wait_for_selector("#aide-terminal-mount .xterm", state="visible")
    if label == "desktop":
        page.wait_for_function(
            "window._currentSession?.id && window._currentSession?.environment?.kind === 'legacy_folder'"
        )
        session_id = page.evaluate("window._currentSession.id")
        assert session_id
        print(f"{label}: temporary-folder session {session_id}", flush=True)
    print(f"{label}: xterm ready", flush=True)
    assert page.locator("#aide-terminal").locator(":scope > *").count() == 1
    assert "clean terminal" not in page.locator("#aide-work-panel").inner_text().lower()
    mount = page.locator("#aide-terminal-mount")
    mount.click()
    page.keyboard.type("printf '__PTY_OK__:%s\\n' \"$PWD\"")
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('#aide-terminal-mount .xterm-rows')?.textContent.includes('__PTY_OK__:/')"
    )
    terminal_text = page.locator("#aide-terminal-mount .xterm-rows").inner_text()
    assert "/private/tmp" in terminal_text or "/tmp" in terminal_text, terminal_text
    print(f"{label}: command round-trip", flush=True)
    page.keyboard.type(
        "python3 -c 'import time; print(\"__PTY_INTERRUPT_READY__\", flush=True); time.sleep(30)'"
    )
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('#aide-terminal-mount .xterm-rows')?.textContent.includes('__PTY_INTERRUPT_READY__')"
    )
    page.keyboard.press("Control+C")
    page.keyboard.type("printf '__PTY_INTERRUPT_OK__\\n'")
    page.keyboard.press("Enter")
    page.wait_for_function(
        "document.querySelector('#aide-terminal-mount .xterm-rows')?.textContent.includes('__PTY_INTERRUPT_OK__')"
    )
    print(f"{label}: interrupt delivery", flush=True)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    page.screenshot(path=f"/tmp/alles-live-terminal-{label}.png", full_page=True)
    assert not errors, errors
    context.close()


def main() -> None:
    from playwright.sync_api import sync_playwright

    _require_throwaway_data_root()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        run_case(browser, 1440, 1000, "desktop")
        run_case(browser, 390, 844, "mobile")
        browser.close()
    print("live xterm PTY browser gate passed")


if __name__ == "__main__":
    main()
