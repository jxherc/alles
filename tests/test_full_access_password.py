"""full access runs without asking, so every way into it wants a recent owner password: a chat
turn, background work handed off in that mode. the detached agent run forces auto mode, so it has
no such check."""

import inspect
from unittest import mock

from core import auth
from core.api_errors import ApiError
from core.database import Session
from routes import chat
from tests._client import ApiTest


class FullAccessPasswordTests(ApiTest):
    def stale_owner(self):
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        self.addCleanup(self.client.cookies.clear)
        self.addCleanup(auth.revoke_token, token)
        for target in ("app.auth_enabled", "core.settings.auth_enabled"):
            patcher = mock.patch(target, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        return token

    def session(self):
        with self.db() as db:
            row = Session(name="full access")
            db.add(row)
            db.commit()
            return row.id

    def test_handoff_in_full_access_wants_the_password(self):
        self.stale_owner()
        session_id = self.session()
        body = {
            "session_id": session_id,
            "request": "tidy the folder",
            "permission_mode": "full_access",
        }
        refused = self.client.post("/api/jarvis/handoffs", json=body)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(refused.json()["code"], "recent_auth_required")

    def test_handoff_in_other_modes_does_not(self):
        self.stale_owner()
        session_id = self.session()
        for mode in ("approve", "plan", "full_auto"):
            with self.subTest(mode=mode):
                response = self.client.post(
                    "/api/jarvis/handoffs",
                    json={
                        "session_id": session_id,
                        "request": "look around",
                        "permission_mode": mode,
                    },
                )
                self.assertNotEqual(
                    response.json().get("code"), "recent_auth_required", response.text
                )

    def test_a_confirmed_password_lets_the_handoff_past_the_check(self):
        token = self.stale_owner()
        session_id = self.session()
        auth.mark_session_recent(token)
        response = self.client.post(
            "/api/jarvis/handoffs",
            json={"session_id": session_id, "request": "tidy", "permission_mode": "full_access"},
        )
        self.assertNotEqual(response.json().get("code"), "recent_auth_required", response.text)

    def test_a_chat_turn_in_full_access_wants_it_and_other_modes_do_not(self):
        from starlette.requests import Request

        token = self.stale_owner()
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [(b"cookie", f"aide_session={token}".encode())],
            "client": ("127.0.0.1", 1),
            "query_string": b"",
        }
        with self.assertRaises(ApiError) as caught:
            chat._require_turn_authority(Request(scope), {"agent_permission_mode": "full_access"})
        self.assertEqual(caught.exception.code, "recent_auth_required")
        for mode in ("approve", "plan", "full_auto"):
            chat._require_turn_authority(Request(scope), {"agent_permission_mode": mode})

    def test_the_detached_run_forces_auto_so_it_asks_nothing_it_can_never_need(self):
        source = inspect.getsource(chat.chat_background)
        self.assertIn('"full_auto"', source)
        self.assertNotIn("_require_turn_authority", source)
