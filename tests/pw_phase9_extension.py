"""Real unpacked-extension gate for Afterlife Phase 9B.

Run with an isolated Alles server on ``PORT`` and the login fixture server on
``FIXTURE_PORT``. The browser profile and Alles data must both be owned
system-temporary directories.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import BrowserContext, Page, expect, sync_playwright

PORT = os.environ.get("PORT", "8059")
FIXTURE_PORT = os.environ.get("FIXTURE_PORT", "8060")
BASE = f"http://127.0.0.1:{PORT}"
LOGIN_URL = f"http://127.0.0.1:{FIXTURE_PORT}/login.html"
DATA = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "")
ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


def _verify_test_root() -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if os.environ.get("ALLES_TEST_DATA") != "1" or not RUN_ID:
        raise RuntimeError("set the isolated ALLES_TEST_DATA ownership proof")
    if DATA == temp_root or temp_root not in DATA.parents:
        raise RuntimeError("ALLES_DATA must be a system-temporary child")
    if (DATA / ".alles-test-owner").read_text("utf-8").strip() != RUN_ID:
        raise RuntimeError("the ALLES_DATA ownership sentinel does not match")
    require_server_ownership(BASE, RUN_ID)
    if not (EXTENSION / "manifest.json").is_file():
        raise RuntimeError("the unpacked extension is missing")


def _headless_extension_copy() -> Path:
    """Pregrant only the fixture host because headless cannot answer Chrome UI."""
    runtime_root = Path(tempfile.mkdtemp(prefix="alles-phase9-extension-runtime-"))
    runtime_extension = runtime_root / "extension"
    shutil.copytree(EXTENSION, runtime_extension)
    manifest_path = runtime_extension / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert "host_permissions" not in manifest
    fixture_permission = "http://127.0.0.1/*"
    assert fixture_permission in manifest["optional_host_permissions"]
    manifest["optional_host_permissions"].remove(fixture_permission)
    manifest["host_permissions"] = [fixture_permission]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return runtime_extension


def _launch(playwright, profile: Path, runtime_extension: Path) -> BrowserContext:
    return playwright.chromium.launch_persistent_context(
        str(profile),
        channel="chromium",
        headless=True,
        viewport={"width": 1100, "height": 760},
        args=[
            f"--disable-extensions-except={runtime_extension}",
            f"--load-extension={runtime_extension}",
        ],
    )


def _worker(context: BrowserContext):
    if context.service_workers:
        return context.service_workers[0]
    return context.wait_for_event("serviceworker", timeout=15_000)


def _popup_page(context: BrowserContext, extension_id: str) -> Page:
    """Load the real action document as a tab because headless hides popup targets."""
    popup = context.new_page()
    popup.goto(f"chrome-extension://{extension_id}/popup.html", wait_until="domcontentloaded")
    return popup


def _owner_state(owner, token: str) -> dict:
    response = owner.get("/api/vault/browsers", headers={"X-Vault-Token": token})
    assert response.ok, response.text()
    return response.json()


def _approve_pair(owner, token: str) -> None:
    state = _owner_state(owner, token)
    assert len(state["pairings"]) == 1, state
    response = owner.post(
        f"/api/vault/browsers/pairings/{state['pairings'][0]['id']}/approve",
        headers={"X-Vault-Token": token},
    )
    assert response.ok, response.text()


def _approve_unlock(owner, token: str) -> None:
    state = _owner_state(owner, token)
    assert len(state["unlock_requests"]) == 1, state
    response = owner.post(
        f"/api/vault/browsers/unlock-requests/{state['unlock_requests'][0]['id']}/approve",
        headers={"X-Vault-Token": token},
    )
    assert response.ok, response.text()


def run() -> None:
    _verify_test_root()
    profile = Path(tempfile.mkdtemp(prefix="alles-phase9-extension-profile-"))
    runtime_extension = _headless_extension_copy()
    if Path(tempfile.gettempdir()).resolve() not in profile.resolve().parents:
        raise RuntimeError("extension profile must be system-temporary")
    errors: list[str] = []

    with sync_playwright() as playwright:
        owner = playwright.request.new_context(base_url=BASE)
        unlock = owner.post("/api/vault/unlock", data={"password": "phase9-extension-master"})
        assert unlock.ok, unlock.text()
        owner_token = unlock.json()["token"]
        created = owner.post(
            "/api/vault",
            headers={"X-Vault-Token": owner_token},
            data={
                "name": "fixture account",
                "type": "login",
                "username": "owner@example.test",
                "fields": {
                    "username": "owner@example.test",
                    "password": "phase9 selected secret",
                    "url": LOGIN_URL,
                },
            },
        )
        assert created.ok, created.text()

        context = _launch(playwright, profile, runtime_extension)
        worker = _worker(context)
        extension_id = worker.url.split("/")[2]
        extension_origin = f"chrome-extension://{extension_id}"
        worker.on(
            "console",
            lambda message: (
                errors.append(f"worker: {message.text}") if message.type == "error" else None
            ),
        )

        login = context.pages[0] if context.pages else context.new_page()
        login.goto(LOGIN_URL, wait_until="domcontentloaded")
        popup = _popup_page(context, extension_id)
        popup.on("pageerror", lambda error: errors.append(f"popup: {error}"))
        popup.on(
            "console",
            lambda message: (
                errors.append(f"popup: {message.text}") if message.type == "error" else None
            ),
        )
        expect(popup.locator("h1")).to_have_text("connect this browser")
        popup.locator("#origin").fill(BASE)
        popup.locator("#pair").click()
        expect(popup.locator("h1")).to_have_text("approve in Passwords", timeout=10_000)
        pair_code = popup.locator(".code").inner_text()
        assert _owner_state(owner, owner_token)["pairings"][0]["code"] == pair_code
        _approve_pair(owner, owner_token)
        expect(popup.locator("h1")).to_have_text("browser locked", timeout=10_000)

        stored = worker.evaluate(
            "chrome.storage.local.get(['allesOrigin', 'connectionId', 'deviceSecret'])"
        )
        assert stored["allesOrigin"] == BASE
        assert stored["connectionId"] and stored["deviceSecret"]
        permissions = worker.evaluate("chrome.permissions.getAll()")
        assert "<all_urls>" not in permissions.get("origins", [])
        assert any(origin.startswith("http://127.0.0.1/") for origin in permissions["origins"])

        popup.locator("#unlock").click()
        expect(popup.locator("h1")).to_have_text("approve short access", timeout=10_000)
        unlock_code = popup.locator(".code").inner_text()
        assert _owner_state(owner, owner_token)["unlock_requests"][0]["code"] == unlock_code
        login.bring_to_front()
        _approve_unlock(owner, owner_token)
        expect(popup.locator("h1")).to_have_text("choose one login", timeout=10_000)
        expect(popup.locator(".site")).to_have_text(f"http://127.0.0.1:{FIXTURE_PORT}")
        expect(popup.locator(".credential")).to_have_count(1)
        expect(popup.locator(".credential")).to_contain_text("fixture account")
        expect(popup.locator(".credential")).to_contain_text("owner@example.test")
        popup.locator(".credential").click()
        expect(login.locator("#login-email")).to_have_value("owner@example.test")
        expect(login.locator("#login-password")).to_have_value("phase9 selected secret")
        assert login.evaluate("window.submitCount") == 0

        # The extension's own lock action removes local and server authority.
        popup = _popup_page(context, extension_id)
        login.bring_to_front()
        popup.evaluate("loadMatches()")
        expect(popup.locator("h1")).to_have_text("choose one login", timeout=10_000)
        popup.locator("#lock").click()
        expect(popup.locator("h1")).to_have_text("browser locked")
        state = _owner_state(owner, owner_token)
        assert state["connections"][0]["locked"] is True

        # Restore a short session, then prove a real browser restart drops it
        # while retaining the persistent paired-device secret.
        popup.locator("#unlock").click()
        expect(popup.locator("h1")).to_have_text("approve short access", timeout=10_000)
        login.bring_to_front()
        _approve_unlock(owner, owner_token)
        expect(popup.locator("h1")).to_have_text("choose one login", timeout=10_000)
        persistent_before = worker.evaluate(
            "chrome.storage.local.get(['connectionId', 'deviceSecret'])"
        )
        context.close()

        context = _launch(playwright, profile, runtime_extension)
        worker = _worker(context)
        extension_id = worker.url.split("/")[2]
        login = context.pages[0] if context.pages else context.new_page()
        login.goto(LOGIN_URL, wait_until="domcontentloaded")
        persistent_after = worker.evaluate(
            "chrome.storage.local.get(['connectionId', 'deviceSecret'])"
        )
        session_after = worker.evaluate("chrome.storage.session.get(['sessionToken'])")
        assert persistent_after == persistent_before
        assert not session_after.get("sessionToken")
        popup = _popup_page(context, extension_id)
        expect(popup.locator("h1")).to_have_text("browser locked", timeout=10_000)

        connection_id = _owner_state(owner, owner_token)["connections"][0]["id"]
        revoked = owner.delete(
            f"/api/vault/browsers/{connection_id}",
            headers={"X-Vault-Token": owner_token},
        )
        assert revoked.ok, revoked.text()
        popup.locator("#unlock").click()
        expect(popup.locator(".error")).to_contain_text("invalid or revoked", timeout=10_000)

        context.close()
        owner.dispose()

    if errors:
        raise AssertionError("extension console errors:\n" + "\n".join(errors))
    print(f"Phase 9 unpacked extension gate passed for {extension_origin}")


if __name__ == "__main__":
    run()
