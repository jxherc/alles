import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import core.settings
import routes.vault as vault_routes
from core import rate_limit
from core.database import BrowserConnection, Vault, VaultEntry
from services import browser_passwords
from services.crypto import encrypt, make_verifier
from tests._client import ApiTest


class BrowserPasswordsApiTest(ApiTest):
    ORIGIN = "chrome-extension://" + "a" * 32

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-browser-passwords-")
        self.settings_patch = mock.patch.object(
            core.settings, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        self.settings_patch.start()
        core.settings._clear_settings_cache()
        rate_limit._events.clear()
        browser_passwords.reset_ephemeral_state()
        vault_routes._unlock_tokens.clear()
        self.vault_token = self.client.post(
            "/api/vault/unlock", json={"password": "master-password"}
        ).json()["token"]
        self.owner_headers = {"X-Vault-Token": self.vault_token}

    def tearDown(self):
        browser_passwords.reset_ephemeral_state()
        rate_limit._events.clear()
        vault_routes._unlock_tokens.clear()
        core.settings._clear_settings_cache()
        self.settings_patch.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _extension(self, path, body):
        return self.client.post(path, json=body, headers={"Origin": self.ORIGIN})

    def _pair(self):
        started = self._extension("/api/auth/browser/pair/start", {"name": "work chrome"})
        self.assertEqual(started.status_code, 200)
        pairing = started.json()
        owner = self.client.get("/api/vault/browsers", headers=self.owner_headers).json()
        self.assertEqual(owner["pairings"][0]["code"], pairing["code"])
        approved = self.client.post(
            f"/api/vault/browsers/pairings/{pairing['pairing_id']}/approve",
            headers=self.owner_headers,
        )
        self.assertEqual(approved.status_code, 200)
        polled = self._extension(
            "/api/auth/browser/pair/poll",
            {
                "pairing_id": pairing["pairing_id"],
                "pairing_secret": pairing["pairing_secret"],
            },
        )
        self.assertEqual(polled.status_code, 200)
        return polled.json()

    def _unlock_browser(self, connection):
        started = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(started.status_code, 200)
        request = started.json()
        owner = self.client.get("/api/vault/browsers", headers=self.owner_headers).json()
        self.assertEqual(owner["unlock_requests"][0]["code"], request["code"])
        approved = self.client.post(
            f"/api/vault/browsers/unlock-requests/{request['request_id']}/approve",
            headers=self.owner_headers,
        )
        self.assertEqual(approved.status_code, 200)
        polled = self._extension(
            "/api/auth/browser/unlock/poll",
            {
                "request_id": request["request_id"],
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(polled.status_code, 200)
        return polled.json()["session_token"]

    def _add_login(self):
        result = self.client.post(
            "/api/vault",
            headers=self.owner_headers,
            json={
                "name": "GitHub work",
                "type": "login",
                "username": "octocat",
                "fields": {
                    "username": "octocat",
                    "password": "correct horse battery staple",
                    "url": "https://github.com/login",
                },
            },
        )
        self.assertEqual(result.status_code, 200)
        return result.json()["id"]

    def _page_body(self, connection, session, **overrides):
        body = {
            "connection_id": connection["connection_id"],
            "device_secret": connection["device_secret"],
            "session_token": session,
            "page_url": "https://github.com/login",
            "top_url": "https://github.com/login",
            "frame_url": "https://github.com/login",
        }
        body.update(overrides)
        return body

    def test_pairing_persists_only_a_secret_hash(self):
        connection = self._pair()
        db = self.db()
        row = db.get(BrowserConnection, connection["connection_id"])
        self.assertNotEqual(row.secret_hash, connection["device_secret"])
        self.assertEqual(
            row.secret_hash,
            hashlib.sha256(connection["device_secret"].encode()).hexdigest(),
        )
        self.assertEqual(row.extension_origin, self.ORIGIN)
        db.close()

    def test_approved_pair_is_retryable_until_ack_and_unlock_poll_is_retryable(self):
        started = self._extension("/api/auth/browser/pair/start", {"name": "retry browser"})
        pairing = started.json()
        approved = self.client.post(
            f"/api/vault/browsers/pairings/{pairing['pairing_id']}/approve",
            headers=self.owner_headers,
        )
        self.assertEqual(approved.status_code, 200)
        pair_body = {
            "pairing_id": pairing["pairing_id"],
            "pairing_secret": pairing["pairing_secret"],
        }
        first_pair = self._extension("/api/auth/browser/pair/poll", pair_body)
        second_pair = self._extension("/api/auth/browser/pair/poll", pair_body)
        self.assertEqual(first_pair.status_code, 200)
        self.assertEqual(second_pair.json(), first_pair.json())
        acknowledged = self._extension("/api/auth/browser/pair/ack", pair_body)
        self.assertEqual(acknowledged.status_code, 200)
        consumed = self._extension("/api/auth/browser/pair/poll", pair_body)
        self.assertEqual(consumed.status_code, 404)
        self.assertEqual(consumed.json()["code"], "pairing_not_found")

        connection = first_pair.json()
        started_unlock = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        request = started_unlock.json()
        approved_unlock = self.client.post(
            f"/api/vault/browsers/unlock-requests/{request['request_id']}/approve",
            headers=self.owner_headers,
        )
        self.assertEqual(approved_unlock.status_code, 200)
        unlock_body = {
            "request_id": request["request_id"],
            "connection_id": connection["connection_id"],
            "device_secret": connection["device_secret"],
        }
        first_unlock = self._extension("/api/auth/browser/unlock/poll", unlock_body)
        second_unlock = self._extension("/api/auth/browser/unlock/poll", unlock_body)
        self.assertEqual(first_unlock.status_code, 200)
        self.assertEqual(second_unlock.json(), first_unlock.json())

    def test_owner_can_deny_pending_pairing_and_unlock_requests(self):
        started = self._extension("/api/auth/browser/pair/start", {"name": "denied browser"})
        pairing = started.json()
        denied = self.client.delete(
            f"/api/vault/browsers/pairings/{pairing['pairing_id']}",
            headers=self.owner_headers,
        )
        self.assertEqual(denied.status_code, 200)
        polled = self._extension(
            "/api/auth/browser/pair/poll",
            {
                "pairing_id": pairing["pairing_id"],
                "pairing_secret": pairing["pairing_secret"],
            },
        )
        self.assertEqual(polled.status_code, 404)

        connection = self._pair()
        started = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        request = started.json()
        denied = self.client.delete(
            f"/api/vault/browsers/unlock-requests/{request['request_id']}",
            headers=self.owner_headers,
        )
        self.assertEqual(denied.status_code, 200)
        polled = self._extension(
            "/api/auth/browser/unlock/poll",
            {
                "request_id": request["request_id"],
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(polled.status_code, 404)

    def test_exact_site_metadata_then_single_selected_release(self):
        entry_id = self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        matched = self._extension("/api/auth/browser/match", self._page_body(connection, session))
        self.assertEqual(matched.status_code, 200)
        self.assertEqual(
            matched.json()["matches"],
            [{"id": entry_id, "name": "GitHub work", "username": "octocat"}],
        )
        self.assertNotIn("correct horse", matched.text)

        released = self._extension(
            "/api/auth/browser/release",
            {**self._page_body(connection, session), "entry_id": entry_id},
        )
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["username"], "octocat")
        self.assertEqual(released.json()["password"], "correct horse battery staple")

    def test_legacy_bare_password_entry_does_not_block_structured_matches(self):
        db = self.db()
        vault = db.query(Vault).first()
        db.add(
            VaultEntry(
                vault_id=vault.id,
                name="legacy password",
                type="password",
                value_encrypted=encrypt("master-password", "legacy bare value"),
            )
        )
        db.commit()
        db.close()

        entry_id = self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        matched = self._extension("/api/auth/browser/match", self._page_body(connection, session))

        self.assertEqual(matched.status_code, 200, matched.text)
        self.assertEqual(
            matched.json()["matches"],
            [{"id": entry_id, "name": "GitHub work", "username": "octocat"}],
        )

    def test_match_scans_past_one_thousand_nonmatching_entries(self):
        connection = self._pair()
        session = self._unlock_browser(connection)
        db = self.db()
        vault = db.query(Vault).first()
        fillers = [
            VaultEntry(
                vault_id=vault.id,
                name=f"filler-{index:04d}",
                type="login",
                value_encrypted="synthetic",
            )
            for index in range(1001)
        ]
        target = VaultEntry(
            vault_id=vault.id,
            name="z-target",
            type="login",
            username="owner",
            value_encrypted="synthetic",
        )
        db.add_all([*fillers, target])
        db.commit()
        target_id = target.id

        def fields(entry, _password):
            if entry.id == target_id:
                return {
                    "url": "https://github.com/sign-in",
                    "username": "owner",
                    "password": "available",
                }
            return {"url": "https://other.example", "password": "unrelated"}

        with mock.patch.object(browser_passwords, "_entry_fields", side_effect=fields):
            matched = browser_passwords.matches(
                db,
                connection["connection_id"],
                connection["device_secret"],
                session,
                self.ORIGIN,
                page_url="https://github.com/login",
                top_url="https://github.com/login",
                frame_url="https://github.com/login",
            )

        self.assertEqual(
            matched,
            [{"id": target_id, "name": "z-target", "username": "owner"}],
        )
        db.close()

    def test_process_restart_clears_short_session_but_keeps_pairing(self):
        self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        browser_passwords.reset_ephemeral_state()

        denied = self._extension("/api/auth/browser/match", self._page_body(connection, session))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_locked")

        started = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(started.status_code, 200)

    def test_browser_activity_does_not_extend_the_absolute_unlock_deadline(self):
        self._add_login()
        connection = self._pair()
        session_token = self._unlock_browser(connection)
        deadline = browser_passwords._sessions[session_token].expires
        with mock.patch.object(browser_passwords.time, "monotonic", return_value=deadline - 1):
            matched = self._extension(
                "/api/auth/browser/match",
                self._page_body(connection, session_token),
            )
        self.assertEqual(matched.status_code, 200, matched.text)
        self.assertEqual(browser_passwords._sessions[session_token].expires, deadline)

        with mock.patch.object(browser_passwords.time, "monotonic", return_value=deadline + 1):
            denied = self._extension(
                "/api/auth/browser/match",
                self._page_body(connection, session_token),
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_locked")

    def test_travel_mode_revokes_and_blocks_unsafe_vault_browser_access(self):
        created = self.client.post(
            "/api/vault/vaults",
            json={"name": "Work", "password": "work-password-one"},
            headers=self.owner_headers,
        )
        self.assertEqual(created.status_code, 200, created.text)
        vault_id = created.json()["id"]
        unlocked = self.client.post(
            "/api/vault/unlock",
            json={"vault_id": vault_id, "password": "work-password-one"},
        )
        self.assertEqual(unlocked.status_code, 200, unlocked.text)
        unsafe_headers = {"X-Vault-Token": unlocked.json()["token"]}
        safe_headers = self.owner_headers
        self.owner_headers = unsafe_headers
        try:
            self._add_login()
            connection = self._pair()
            session = self._unlock_browser(connection)
        finally:
            self.owner_headers = safe_headers

        enabled = self.client.put("/api/vault/travel-mode", json={"on": True}, headers=safe_headers)
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(self.client.get("/api/vault", headers=unsafe_headers).status_code, 403)

        denied = self._extension("/api/auth/browser/match", self._page_body(connection, session))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "vault_unavailable_in_travel_mode")
        denied_unlock = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(denied_unlock.status_code, 403)
        self.assertEqual(denied_unlock.json()["code"], "vault_unavailable_in_travel_mode")

    def test_scheme_port_and_top_frame_must_match_exactly(self):
        self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        port = self._extension(
            "/api/auth/browser/match",
            self._page_body(
                connection,
                session,
                page_url="https://github.com:444/login",
                top_url="https://github.com:444/login",
                frame_url="https://github.com:444/login",
            ),
        )
        self.assertEqual(port.status_code, 200)
        self.assertEqual(port.json()["matches"], [])
        frame = self._extension(
            "/api/auth/browser/match",
            self._page_body(connection, session, frame_url="https://evil.example/frame"),
        )
        self.assertEqual(frame.status_code, 403)
        self.assertEqual(frame.json()["code"], "third_party_frame_refused")
        insecure = self._extension(
            "/api/auth/browser/match",
            self._page_body(
                connection,
                session,
                page_url="http://github.com/login",
                top_url="http://github.com/login",
                frame_url="http://github.com/login",
            ),
        )
        self.assertEqual(insecure.status_code, 403)
        self.assertEqual(insecure.json()["code"], "insecure_page")

    def test_lock_and_revoke_immediately_remove_browser_authority(self):
        self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        locked = self.client.post(
            f"/api/vault/browsers/{connection['connection_id']}/lock",
            headers=self.owner_headers,
        )
        self.assertEqual(locked.status_code, 200)
        denied = self._extension("/api/auth/browser/match", self._page_body(connection, session))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_locked")

        session = self._unlock_browser(connection)
        revoked = self.client.delete(
            f"/api/vault/browsers/{connection['connection_id']}",
            headers=self.owner_headers,
        )
        self.assertEqual(revoked.status_code, 200)
        denied = self._extension("/api/auth/browser/match", self._page_body(connection, session))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_not_connected")

    def test_vault_rekey_immediately_locks_existing_browser_sessions(self):
        self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)

        changed = self.client.post(
            "/api/vault/vaults/password",
            json={"new_password": "new-master-password"},
            headers=self.owner_headers,
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        denied = self._extension(
            "/api/auth/browser/match",
            self._page_body(connection, session),
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_locked")

    def test_current_vault_verifier_is_rechecked_before_password_release(self):
        self._add_login()
        connection = self._pair()
        session = self._unlock_browser(connection)
        db = self.db()
        vault = db.get(Vault, "default")
        vault.verifier = make_verifier("restored-master-password")
        db.commit()
        db.close()

        denied = self._extension(
            "/api/auth/browser/release",
            self._page_body(connection, session, entry_id="login-1"),
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_locked")

    def test_extension_can_revoke_its_own_connection(self):
        connection = self._pair()
        disconnected = self._extension(
            "/api/auth/browser/disconnect",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(disconnected.status_code, 200)

        db = self.db()
        row = db.get(BrowserConnection, connection["connection_id"])
        self.assertIsNotNone(row.revoked_at)
        db.close()
        denied = self._extension(
            "/api/auth/browser/unlock/start",
            {
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "browser_not_connected")

    def test_extension_origin_is_bound_at_pairing(self):
        connection = self._pair()
        wrong = self.client.post(
            "/api/auth/browser/unlock/start",
            json={
                "connection_id": connection["connection_id"],
                "device_secret": connection["device_secret"],
            },
            headers={"Origin": "chrome-extension://" + "b" * 32},
        )
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.json()["code"], "browser_not_connected")

    def test_extension_download_contains_only_the_reviewed_runtime_files(self):
        response = self.client.get("/api/vault/browsers/extension", headers=self.owner_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("alles-passwords-extension.zip", response.headers["content-disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"manifest.json", "popup.html", "popup.css", "popup.js", "background.js"},
            )
            source = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
        self.assertNotIn("X-Vault-Token", source)
        self.assertNotIn(self.vault_token, source)

    def test_origin_normalization_treats_idna_and_default_https_port_as_exact(self):
        self.assertEqual(
            browser_passwords.exact_page_origin(
                "https://bücher.example/login",
                "https://xn--bcher-kva.example:443/account",
                "https://BÜCHER.example/",
            ),
            ("https", "xn--bcher-kva.example", 443),
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
