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
CHECKOUT_URL = f"http://127.0.0.1:{FIXTURE_PORT}/checkout.html"
FIXTURE_HOST = f"127.0.0.1:{FIXTURE_PORT}"
DATA = Path(os.environ.get("ALLES_DATA", "")).expanduser().resolve()
RUN_ID = os.environ.get("ALLES_TEST_RUN_ID", "")
ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
OUTPUT: Path


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


def _assert_targets(page: Page) -> None:
    failures = page.locator("button:visible, input:visible").evaluate_all(
        """elements => elements.filter(element => {
          if (element.disabled) return false;
          const box = element.getBoundingClientRect();
          return box.width < 43.5 || box.height < 43.5;
        }).map(element => ({
          label: element.textContent.trim() || element.getAttribute('aria-label'),
          box: element.getBoundingClientRect().toJSON(),
        }))"""
    )
    assert not failures, failures


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
    global OUTPUT

    _verify_test_root()
    OUTPUT = Path(tempfile.mkdtemp(prefix="phase9-extension-artifacts-", dir=DATA))
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
        for item in (
            {
                "name": "visa",
                "type": "card",
                "fields": {
                    "cardholder": "eric hou",
                    "number": "4242 4242 4242 4242",
                    "expiry": "08/29",
                    "cvv": "123",
                },
            },
            {
                "name": "home",
                "type": "identity",
                "fields": {
                    "fullname": "eric hou",
                    "email": "eric@example.test",
                    "phone": "416 555 0100",
                    "home_address": "1 king st w\nsuite 400\ntoronto, on m5h 1a1\ncanada",
                },
            },
        ):
            added = owner.post("/api/vault", headers={"X-Vault-Token": owner_token}, data=item)
            assert added.ok, added.text()

        context = _launch(playwright, profile, runtime_extension)
        sealed_seen: list = []

        def _watch(response):
            if (
                "/api/auth/browser/match" in response.url
                or "/api/auth/browser/release" in response.url
            ):
                try:
                    sealed_seen.append(response.json())
                except Exception:  # a refused request has its own assertions
                    pass

        context.on("response", _watch)
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
        expect(popup.locator("h1")).to_have_text("connect to alles")
        assert popup.locator('select, input[type="checkbox"], input[type="radio"]').count() == 0
        _assert_targets(popup)
        popup.screenshot(path=str(OUTPUT / "extension-connect.png"), full_page=True)
        popup.locator("#origin").fill(BASE)
        popup.locator("#pair").click()
        expect(popup.locator("h1")).to_have_text("approve in alles", timeout=10_000)
        pair_code = popup.locator(".code").inner_text()
        popup.screenshot(path=str(OUTPUT / "extension-pairing.png"), full_page=True)
        assert _owner_state(owner, owner_token)["pairings"][0]["code"] == pair_code
        # The background inactivity boundary can clear extension session
        # storage while the owner is approving an otherwise valid request.
        worker.evaluate("chrome.storage.session.remove('pairing')")
        assert not worker.evaluate("chrome.storage.session.get('pairing')").get("pairing")
        _approve_pair(owner, owner_token)
        expect(popup.locator("h1")).to_have_text("locked", timeout=10_000)

        stored = worker.evaluate(
            "chrome.storage.local.get(['allesOrigin', 'connectionId', 'deviceSecret'])"
        )
        assert stored["allesOrigin"] == BASE
        assert stored["connectionId"] and stored["deviceSecret"]
        permissions = worker.evaluate("chrome.permissions.getAll()")
        assert "<all_urls>" not in permissions.get("origins", [])
        assert any(origin.startswith("http://127.0.0.1/") for origin in permissions["origins"])

        popup.locator("#unlock").click()
        expect(popup.locator("h1")).to_have_text("approve in alles", timeout=10_000)
        unlock_code = popup.locator(".code").inner_text()
        assert _owner_state(owner, owner_token)["unlock_requests"][0]["code"] == unlock_code
        login.bring_to_front()
        _approve_unlock(owner, owner_token)
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        logins = popup.locator('.item[data-kind="logins"]')
        expect(logins).to_have_count(1)
        expect(logins).to_contain_text("fixture account")
        expect(logins).to_contain_text("owner@example.test")
        # the card and the address show on every secure page, the login only on its own site
        expect(popup.locator('.item[data-kind="cards"]')).to_contain_text("•••• 4242")
        expect(popup.locator('.item[data-kind="addresses"]')).to_contain_text("1 king st w")
        _assert_targets(popup)
        popup.screenshot(path=str(OUTPUT / "extension-matches.png"), full_page=True)
        popup.locator('.item[data-kind="logins"]').click()
        expect(login.locator("#login-email")).to_have_value("owner@example.test")
        expect(login.locator("#login-password")).to_have_value("phase9 selected secret")
        assert login.evaluate("window.submitCount") == 0

        # Hold one already-successful credential release after Alles has returned
        # the plaintext, then lock the browser before the popup can inject it.
        # The old session must no longer own the fill and the locked view must
        # remain authoritative.
        popup = _popup_page(context, extension_id)
        login.bring_to_front()
        popup.evaluate("loadMatches()")
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        login.locator("#login-email").fill("")
        login.locator("#login-password").fill("")
        popup.evaluate(
            """() => {
              const liveRequest = request;
              const liveFillSelected = fillSelected;
              let holdNextRelease = true;
              window.__heldReleaseReady = false;
              window.__heldReleaseDone = false;
              request = async (origin, path, body) => {
                const result = await liveRequest(origin, path, body);
                if (path === '/api/auth/browser/release' && holdNextRelease) {
                  holdNextRelease = false;
                  window.__heldReleaseReady = true;
                  document.body.dataset.heldReleaseReady = 'true';
                  await new Promise(resolve => { window.__releaseHeldRelease = resolve; });
                }
                return result;
              };
              fillSelected = async (...args) => {
                try {
                  return await liveFillSelected(...args);
                } finally {
                  window.__heldReleaseDone = true;
                  document.body.dataset.heldReleaseDone = 'true';
                }
              };
            }"""
        )
        popup.locator('.item[data-kind="logins"]').click()
        expect(popup.locator("body")).to_have_attribute(
            "data-held-release-ready", "true", timeout=10_000
        )
        popup.locator("#lock").click()
        expect(popup.locator("h1")).to_have_text("locked", timeout=10_000)
        assert not worker.evaluate("chrome.storage.session.get('sessionToken')").get("sessionToken")
        assert _owner_state(owner, owner_token)["connections"][0]["locked"] is True
        popup.evaluate("window.__releaseHeldRelease()")
        expect(popup.locator("body")).to_have_attribute(
            "data-held-release-done", "true", timeout=10_000
        )
        expect(popup.locator("h1")).to_have_text("locked")
        expect(popup.locator("#unlock")).to_be_visible()
        expect(login.locator("#login-email")).to_have_value("")
        expect(login.locator("#login-password")).to_have_value("")
        assert login.evaluate("window.submitCount") == 0

        # Restore a short session before racing a stale match render against
        # the extension's own local and server lock boundary.
        popup.locator("#unlock").click()
        expect(popup.locator("h1")).to_have_text("approve in alles", timeout=10_000)
        login.bring_to_front()
        _approve_unlock(owner, owner_token)
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        popup = _popup_page(context, extension_id)
        login.bring_to_front()
        popup.evaluate("loadMatches()")
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        # Hold one already-successful match response across explicit lock, and
        # hold the lock response after the server has applied it. The locked
        # transition must own the view and finish server authority before it
        # exposes another unlock action.
        popup.evaluate(
            """() => {
              const liveRequest = request;
              let holdNextMatch = true;
              window.__heldMatchReady = false;
              window.__heldMatchDone = false;
              window.__heldLockReady = false;
              request = async (origin, path, body) => {
                const result = await liveRequest(origin, path, body);
                if (path === '/api/auth/browser/match' && holdNextMatch) {
                  holdNextMatch = false;
                  window.__heldMatchReady = true;
                  document.body.dataset.heldMatchReady = 'true';
                  await new Promise(resolve => { window.__releaseHeldMatch = resolve; });
                }
                if (path === '/api/auth/browser/lock') {
                  window.__heldLockReady = true;
                  document.body.dataset.heldLockReady = 'true';
                  await new Promise(resolve => { window.__releaseHeldLock = resolve; });
                }
                return result;
              };
              loadMatches().finally(() => {
                window.__heldMatchDone = true;
                document.body.dataset.heldMatchDone = 'true';
              });
            }"""
        )
        expect(popup.locator("body")).to_have_attribute(
            "data-held-match-ready", "true", timeout=10_000
        )
        lock = popup.locator("#lock")
        lock.focus()
        expect(lock).to_be_focused()
        popup.keyboard.press("Enter")
        expect(popup.locator("body")).to_have_attribute(
            "data-held-lock-ready", "true", timeout=10_000
        )
        expect(popup.locator("#lock")).to_have_attribute("aria-busy", "true")
        expect(popup.locator("#lock")).to_have_text("locking…")
        expect(popup.locator("#unlock")).to_have_count(0)
        popup.evaluate("window.__releaseHeldMatch()")
        expect(popup.locator("body")).to_have_attribute(
            "data-held-match-done", "true", timeout=10_000
        )
        expect(popup.locator("#lock")).to_have_attribute("aria-busy", "true")
        popup.evaluate("window.__releaseHeldLock()")
        expect(popup.locator("h1")).to_have_text("locked")
        state = _owner_state(owner, owner_token)
        assert state["connections"][0]["locked"] is True

        # Restore a short session, then prove a real browser restart drops it
        # while retaining the persistent paired-device secret.
        popup.locator("#unlock").click()
        expect(popup.locator("h1")).to_have_text("approve in alles", timeout=10_000)
        login.bring_to_front()
        _approve_unlock(owner, owner_token)
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        # cards and addresses on a checkout page: sealed to this browser, filled into the forms
        checkout = context.new_page()
        checkout.goto(CHECKOUT_URL, wait_until="domcontentloaded")
        popup = _popup_page(context, extension_id)
        checkout.bring_to_front()
        popup.evaluate("loadMatches()")
        expect(popup.locator("h1")).to_have_text(FIXTURE_HOST, timeout=10_000)
        expect(popup.locator('.item[data-kind="logins"]')).to_have_count(1)
        popup.locator('.item[data-kind="addresses"]').click()
        expect(checkout.locator("#ship-name")).to_have_value("eric hou")
        expect(checkout.locator("#ship-email")).to_have_value("eric@example.test")
        expect(checkout.locator("#ship-phone")).to_have_value("416 555 0100")
        expect(checkout.locator("#ship-line1")).to_have_value("1 king st w")
        expect(checkout.locator("#ship-line2")).to_have_value("suite 400")
        expect(checkout.locator("#ship-city")).to_have_value("toronto")
        expect(checkout.locator("#ship-region")).to_have_value("ON")
        expect(checkout.locator("#ship-postal")).to_have_value("m5h 1a1")
        expect(checkout.locator("#ship-country")).to_have_value("canada")
        popup = _popup_page(context, extension_id)
        checkout.bring_to_front()
        popup.evaluate("loadMatches()")
        expect(popup.locator('.item[data-kind="cards"]')).to_have_count(1, timeout=10_000)
        popup.locator('.item[data-kind="cards"]').click()
        expect(checkout.locator("#card-name")).to_have_value("eric hou")
        expect(checkout.locator("#card-number")).to_have_value("4242424242424242")
        expect(checkout.locator("#card-month")).to_have_value("08")
        expect(checkout.locator("#card-year")).to_have_value("2029")
        expect(checkout.locator("#card-cvc")).to_have_value("123")
        checkout.screenshot(path=str(OUTPUT / "extension-checkout-filled.png"), full_page=True)
        # what crossed the wire was sealed: the network log holds no card number or password
        assert "4242424242424242" not in json.dumps(sealed_seen)
        assert sealed_seen and all(set(body) == {"sealed"} for body in sealed_seen), sealed_seen

        # "al <words>" in the address bar runs andromeda on the paired alles
        worker.evaluate("searchAndromeda('black holes', 'newForegroundTab')")
        search = context.wait_for_event(
            "page", predicate=lambda page: "app=andromeda" in page.url, timeout=10_000
        )
        assert search.url.startswith(f"{BASE}/?app=andromeda&q=black%20holes"), search.url
        search.close()
        login.bring_to_front()

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
        expect(popup.locator("h1")).to_have_text("locked", timeout=10_000)
        popup.screenshot(path=str(OUTPUT / "extension-locked-after-restart.png"), full_page=True)

        connection_id = _owner_state(owner, owner_token)["connections"][0]["id"]
        revoked = owner.delete(
            f"/api/vault/browsers/{connection_id}",
            headers={"X-Vault-Token": owner_token},
        )
        assert revoked.ok, revoked.text()
        popup.locator("#unlock").click()
        expect(popup.locator(".error")).to_contain_text("invalid or revoked", timeout=10_000)
        popup.screenshot(path=str(OUTPUT / "extension-revoked.png"), full_page=True)

        context.close()
        owner.dispose()

    if errors:
        raise AssertionError("extension console errors:\n" + "\n".join(errors))
    print(f"Phase 9 unpacked extension gate passed for {extension_origin}; captures: {OUTPUT}")


if __name__ == "__main__":
    run()
